"""The only authorization authority in AGENTGATE.

Deterministic, pure, and blind to document text. A rule either matches or the
action is denied. Nothing here reads `body`, `note`, or any model output.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import labels
from .models import ActionRequest, Decision, PolicySet, SecurityLabel


def load_policy_set(principals_path: str | Path, policies_path: str | Path) -> PolicySet:
    principals = json.loads(Path(principals_path).read_text(encoding="utf-8"))
    rules = json.loads(Path(policies_path).read_text(encoding="utf-8"))
    return PolicySet(principals=principals, rules=rules)


def evaluate(request: ActionRequest, state, policies: PolicySet) -> Decision:
    actor = policies.principal(request.actor_id)
    if actor is None:
        return _deny("RULE-UNKNOWN-ACTOR",
                     f"Actor '{request.actor_id}' is not in the trusted directory.")
    if actor.kind == "recipient":
        return _deny("RULE-RECIPIENT-NOT-ACTOR",
                     f"'{actor.id}' is a delivery target, not an actor.")

    matching = policies.rules_for(actor.role, request.tool)
    if not matching:
        return _deny("RULE-NO-GRANT",
                     f"Role '{actor.role}' has no rule allowing '{request.tool}'. "
                     "Default deny applies.")
    rule = max(matching, key=lambda r: labels.rank(r.max_classification))

    if request.tool == "read_document":
        return _check_read(request, state, actor, rule)
    if request.tool == "save_report":
        return _check_save(request, state, actor, rule)
    return _check_deliver(request, state, actor, rule, policies)


# -- per-tool checks -------------------------------------------------------


def _check_read(request, state, actor, rule) -> Decision:
    doc = state.get_document(request.resource_id or "")
    if doc is None:
        return _deny("RULE-NO-SUCH-DOCUMENT",
                     f"Document '{request.resource_id}' does not exist.")
    ceiling = _ceiling(actor.clearance, rule.max_classification)
    if not labels.at_least(ceiling, doc.classification):
        return _deny(
            "RULE-READ-CLEARANCE",
            f"Blocked: '{doc.title}' is {doc.classification}; {actor.id} holds "
            f"{actor.clearance} and rule {rule.id} caps reads at {rule.max_classification}. "
            "The document text was never opened.",
        )
    return _allow(
        rule.id,
        f"Allowed: {actor.id} holds {actor.clearance}, '{doc.title}' is "
        f"{doc.classification}, within rule {rule.id}.",
        SecurityLabel(classification=doc.classification, provenance=[doc.id],
                      tags=[f"owner:{doc.owner}"]),
    )


def _check_save(request, state, actor, rule) -> Decision:
    if not request.source_ids:
        return _deny("RULE-NO-SOURCES", "A report must cite at least one source document.")
    found = []
    for doc_id in request.source_ids:
        doc = state.get_document(doc_id)
        if doc is None:
            return _deny("RULE-NO-SUCH-DOCUMENT", f"Source '{doc_id}' does not exist.")
        ceiling = _ceiling(actor.clearance, rule.max_classification)
        if not labels.at_least(ceiling, doc.classification):
            return _deny(
                "RULE-SOURCE-TOO-SENSITIVE",
                f"Blocked: source '{doc.title}' is {doc.classification}, above what "
                f"{actor.id} may summarise under rule {rule.id}. No report was written.",
            )
        found.append(doc)
    derived = labels.combine([
        SecurityLabel(classification=d.classification, provenance=[d.id], tags=[f"owner:{d.owner}"])
        for d in found
    ])
    return _allow(
        rule.id,
        f"Allowed: report inherits {derived.classification} — the highest of its sources "
        f"({', '.join(d.classification for d in found)}) — and keeps provenance "
        f"{', '.join(derived.provenance)}.",
        derived,
    )


def _check_deliver(request, state, actor, rule, policies: PolicySet) -> Decision:
    artifact = state.get_artifact(request.resource_id or "")
    if artifact is None:
        return _deny("RULE-NO-SUCH-ARTIFACT",
                     f"Artifact '{request.resource_id}' does not exist. Nothing was sent.")
    recipient_id = request.recipient or ""
    if recipient_id not in actor.allowed_recipients:
        return _deny(
            "RULE-RECIPIENT-NOT-PERMITTED",
            f"Blocked: rule {rule.id} does not permit {actor.id} to send to "
            f"'{recipient_id}'. The message never reached the inbox.",
            artifact.label,
        )
    recipient = policies.principal(recipient_id)
    if recipient is None:
        return _deny("RULE-UNKNOWN-RECIPIENT",
                     f"Blocked: '{recipient_id}' is not in the trusted directory.",
                     artifact.label)
    if not labels.at_least(recipient.clearance, artifact.label.classification):
        return _deny(
            "RULE-RECIPIENT-CLEARANCE",
            f"Blocked: '{artifact.title}' is {artifact.label.classification} but "
            f"{recipient_id} holds only {recipient.clearance}. Labels travelled with the "
            f"report from {', '.join(artifact.label.provenance)}.",
            artifact.label,
        )
    if not labels.at_least(_ceiling(actor.clearance, rule.max_classification),
                           artifact.label.classification):
        return _deny(
            "RULE-ACTOR-CANNOT-RELEASE",
            f"Blocked: {actor.id} may not release {artifact.label.classification} material "
            f"under rule {rule.id}.",
            artifact.label,
        )
    return _allow(
        rule.id,
        f"Allowed: {recipient_id} holds {recipient.clearance}, report is "
        f"{artifact.label.classification}, and {recipient_id} is an approved recipient "
        f"for {actor.id}.",
        artifact.label,
    )


# -- helpers ---------------------------------------------------------------


def _ceiling(actor_clearance: str, rule_max: str) -> str:
    """The stricter of personal clearance and the rule's cap."""
    return actor_clearance if labels.rank(actor_clearance) <= labels.rank(rule_max) else rule_max


def _allow(rule_id: str, reason: str, label: SecurityLabel | None = None) -> Decision:
    return Decision(allowed=True, rule_id=rule_id, reason=reason, label=label)


def _deny(rule_id: str, reason: str, label: SecurityLabel | None = None) -> Decision:
    return Decision(allowed=False, rule_id=rule_id, reason=reason, label=label)
