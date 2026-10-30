"""Gateway: bind identity, evaluate first, execute only on allow, audit everything.

The session owns the actor and the origin. A request cannot choose who it is.
Read history is keyed by actor, so closing a session does not launder a source.
A workflow step is submitted with its coordinates; they land on the audit row and
become the idempotency key of the effect, so a retried step cannot deliver twice.
"""

from __future__ import annotations

import uuid

from . import labels, tools
from .models import ActionRequest, Artifact, Decision, PolicySet
from .policy import evaluate
from .policy_guard import Guard, PolicyDrift


class Session:
    """One actor's working session. Identity and origin are set here, not by the AI."""

    def __init__(self, state, policies: PolicySet, actor_id: str, origin: str = "human",
                 guard: Guard | None = None):
        self.state = state
        self.policies = policies
        self.actor_id = actor_id
        self.origin = origin if origin in ("human", "agent") else "human"
        self.guard = guard
        self.id = "s-" + uuid.uuid4().hex[:8]

    def submit(self, request: ActionRequest, workflow_id: str | None = None,
               step_index: int | None = None) -> tuple[Decision, object | None]:
        bound = request.model_copy(update={"actor_id": self.actor_id, "origin": self.origin})

        if self.guard is not None:
            try:
                self.guard.check()
            except PolicyDrift as drift:
                return self._deny_drift(bound, drift, workflow_id, step_index)

        if bound.tool == "save_report":
            tainted = self.state.reads_for(self.actor_id)
            effective = list(dict.fromkeys(list(bound.source_ids) + tainted))
            if set(effective) != set(bound.source_ids):
                bound = bound.model_copy(update={"source_ids": effective})

        decision = evaluate(bound, self.state, self.policies)
        self.state.record_audit(
            actor=bound.actor_id, origin=bound.origin, tool=bound.tool,
            resource=bound.resource_id or ",".join(bound.source_ids) or None,
            recipient=bound.recipient, allowed=decision.allowed, rule_id=decision.rule_id,
            reason=decision.reason, label=decision.label,
            policy_hash=self.policies.fingerprint,
            workflow_id=workflow_id, step_index=step_index,
        )

        result: object | None = None
        if decision.allowed:
            result = _dispatch(bound, self.state, _effect_key(workflow_id, step_index))
            if bound.tool == "read_document" and bound.resource_id:
                self.state.record_read(self.actor_id, bound.resource_id)
        return decision, result

    def _deny_drift(self, bound: ActionRequest, drift: PolicyDrift,
                    workflow_id: str | None, step_index: int | None):
        """Deny and audit a mid-session rulebook swap. Nothing is evaluated and no tool runs."""
        decision = Decision(
            allowed=False, rule_id="RULE-POLICY-DRIFT",
            reason=(f"Blocked: the rulebook on disk no longer matches the one this session loaded "
                    f"(pinned {drift.expected}, found {drift.found}). No action was evaluated and no "
                    "tool ran. A reload with the operator token is required to accept new rules."),
            label=None)
        self.state.record_audit(
            actor=bound.actor_id, origin=bound.origin, tool=bound.tool,
            resource=bound.resource_id or ",".join(bound.source_ids) or None,
            recipient=bound.recipient, allowed=False, rule_id=decision.rule_id,
            reason=decision.reason, label=None, policy_hash=self.policies.fingerprint,
            workflow_id=workflow_id, step_index=step_index)
        return decision, None


def _effect_key(workflow_id: str | None, step_index: int | None) -> str:
    """Stable per step, so re-running a step reuses the same inbox row."""
    if workflow_id is None or step_index is None:
        return ""
    return f"{workflow_id}:{step_index}"


def _dispatch(request: ActionRequest, state, effect_key: str = ""):
    if request.tool == "read_document":
        return tools.read_document(request.actor_id, request.resource_id or "", state,
                                   gate=tools._GATE)
    if request.tool == "save_report":
        return tools.save_report(request.actor_id, request.source_ids, request.title, state,
                                 gate=tools._GATE)
    if request.tool == "deliver_inbox":
        return tools.deliver_inbox(request.actor_id, request.resource_id or "",
                                   request.recipient or "", state, gate=tools._GATE,
                                   effect_key=effect_key)
    raise ValueError(f"unknown tool {request.tool}")


def declassify(state, policies: PolicySet, officer_id: str, artifact_id: str,
               target: str, justification: str) -> Artifact:
    """Human officer only. Creates a new linked artifact; never edits the original."""
    officer = policies.principal(officer_id)
    if officer is None or officer.role != "security-officer":
        state.record_audit(actor=officer_id, origin="human", tool="declassify",
                           resource=artifact_id, recipient=None, allowed=False,
                           rule_id="RULE-DECLASSIFY-ROLE",
                           reason=f"Blocked: '{officer_id}' does not hold the security-officer role.",
                           label=None, policy_hash=policies.fingerprint)
        raise PermissionError("not a security officer")

    original = state.get_artifact(artifact_id)
    if original is None:
        raise ValueError("artifact not found")
    if len(justification.strip()) < 15:
        state.record_audit(actor=officer_id, origin="human", tool="declassify",
                           resource=artifact_id, recipient=None, allowed=False,
                           rule_id="RULE-DECLASSIFY-JUSTIFICATION",
                           reason="Blocked: a written justification of at least 15 characters is required.",
                           label=original.label, policy_hash=policies.fingerprint,
                           justification=justification)
        raise ValueError("justification too short")
    if not labels.at_least(officer.clearance, original.label.classification):
        state.record_audit(actor=officer_id, origin="human", tool="declassify",
                           resource=artifact_id, recipient=None, allowed=False,
                           rule_id="RULE-DECLASSIFY-CLEARANCE",
                           reason=(f"Blocked: {officer_id} holds {officer.clearance} and may not "
                                   f"handle {original.label.classification} material."),
                           label=original.label, policy_hash=policies.fingerprint,
                           justification=justification)
        raise PermissionError("officer clearance below the artifact classification")
    if target not in labels.ORDER or labels.rank(target) >= labels.rank(original.label.classification):
        state.record_audit(actor=officer_id, origin="human", tool="declassify",
                           resource=artifact_id, recipient=None, allowed=False,
                           rule_id="RULE-DECLASSIFY-DIRECTION",
                           reason="Blocked: declassification may only lower a classification.",
                           label=original.label, policy_hash=policies.fingerprint,
                           justification=justification)
        raise ValueError("target is not lower than the current classification")

    new_label = original.label.model_copy(deep=True)
    new_label.classification = target
    new_label.provenance = list(original.label.provenance) + [artifact_id]
    new_label.tags = list(original.label.tags) + ["declassified-by:" + officer_id]
    child = Artifact(id=state.new_artifact_id(), title=original.title + " (declassified)",
                     label=new_label, body=original.body)
    state.add_artifact(child)
    state.record_audit(
        actor=officer_id, origin="human", tool="declassify", resource=artifact_id,
        recipient=None, allowed=True, rule_id="DECLASSIFY-OFFICER",
        reason=(f"Allowed: {officer_id} released a copy of {artifact_id} from "
                f"{original.label.classification} to {target}. New artifact {child.id}; "
                f"original untouched."),
        label=child.label, policy_hash=policies.fingerprint, justification=justification)
    return child
