"""Workflow runner: the database stores proposals, never decisions.

A workflow is an ordered list of stored action proposals. `resume` re-reads the policy
files from disk and re-evaluates every step that is not done through the same Session
path a live click uses, so nothing carries over an earlier ALLOW. A rulebook that
tightened while the app was closed therefore blocks a step an earlier run was glad to
run, and the steps behind it are marked halted rather than skipped in silence.

A step marked `done` is a record of an effect that already happened, not a cached
permission: it is not re-executed, and it authorises nothing on its own. Each executed
step is audited with its workflow id and step index, and its delivery carries that pair
as an idempotency key, so a crash between the tool and the status write cannot put the
same message in the inbox twice.

`$<index>` in a later step's resource refers to the id that step produced, which is how
"read this, summarise it, send the summary" survives a restart without hard-coding an
artifact id that does not exist yet.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .gateway import Session
from .models import ActionRequest
from .policy import load_policy_set
from .policy_guard import PolicyDrift


def create(state, steps: list[ActionRequest], title: str = "workflow") -> str:
    """Store an ordered list of proposals. No policy is consulted until a run."""
    if not steps:
        raise ValueError("a workflow needs at least one step")
    wf = "wf-" + uuid.uuid4().hex[:8]
    state.save_workflow(wf, "active", {"title": title, "step_count": len(steps)})
    state.add_steps(wf, [step.model_dump() for step in steps])
    return wf


def describe(step: dict) -> str:
    """One line for a stored proposal, safe to show next to the status."""
    request = ActionRequest(**step["request"])
    target = request.resource_id or ",".join(request.source_ids) or "-"
    text = f"{request.actor_id}: {request.tool} {target}"
    return f"{text} → {request.recipient}" if request.recipient else text


def _chain(request: ActionRequest, outputs: dict[int, str]) -> ActionRequest:
    """Replace a `$<index>` resource with the id that step actually produced.

    An unresolved reference stays empty: the step is then denied as a missing artifact
    instead of the runner guessing what was meant.
    """
    resource = request.resource_id or ""
    if resource.startswith("$") and resource[1:].isdigit():
        return request.model_copy(update={"resource_id": outputs.get(int(resource[1:]), "")})
    return request


def resume(state, workflow_id: str, principals_path: str | Path,
           policies_path: str | Path, guard=None, token: str | None = None) -> dict[str, Any]:
    """Run the workflow from the first step that is not done.

    If a policy guard is supplied, a rulebook that moved since the pin refuses the run
    unless the operator's reload token is presented. Resume is a decision point like any
    other; it must not be a way to adopt a rulebook nobody approved. Drift is refused as a
    denied decision — audited, every open step halted, nothing executed — not as an
    exception out of the runner.
    """
    steps = state.steps_for(workflow_id)
    if guard is not None:
        if token is not None:
            policies = guard.reload(token)
        else:
            try:
                guard.check()
            except PolicyDrift as drift:
                return _refuse_drift(state, workflow_id, steps, drift)
            policies = load_policy_set(principals_path, policies_path)
    else:
        policies = load_policy_set(principals_path, policies_path)
    payload = state.get_workflow(workflow_id)["payload"]
    outputs = {step["idx"]: step["output"] for step in steps}
    report: dict[str, Any] = {"workflow_id": workflow_id,
                              "policy_fingerprint": policies.fingerprint,
                              "status": "", "steps": []}

    for position, step in enumerate(steps):
        if step["status"] == "done":
            continue

        request = _chain(ActionRequest(**step["request"]), outputs)
        session = Session(state, policies, request.actor_id, request.origin, guard)
        decision, result = session.submit(request, workflow_id=workflow_id,
                                          step_index=step["idx"])

        if decision.allowed:
            output = str(result) if request.tool == "save_report" else ""
            state.set_step(workflow_id, step["idx"], "done", decision.reason, output)
            outputs[step["idx"]] = output
            report["steps"].append(_row(step["idx"], describe(step), request.tool, "done",
                                        decision.rule_id, decision.reason, allowed=True))
            continue

        state.set_step(workflow_id, step["idx"], "blocked", decision.reason)
        report["steps"].append(_row(step["idx"], describe(step), request.tool, "blocked",
                                    decision.rule_id, decision.reason, allowed=False))
        for later in steps[position + 1:]:
            if later["status"] == "done":
                continue  # it ran on an earlier pass; never claim it did not
            reason = f"Not run: step {step['idx']} was blocked."
            state.set_step(workflow_id, later["idx"], "halted", reason)
            report["steps"].append(_row(later["idx"], describe(later),
                                        ActionRequest(**later["request"]).tool, "halted",
                                        "WORKFLOW-HALTED", reason, allowed=False))
        report["status"] = "halted"
        state.save_workflow(workflow_id, "halted", payload)
        return report

    report["status"] = "completed"
    state.save_workflow(workflow_id, "completed", payload)
    return report


def _refuse_drift(state, workflow_id: str, steps: list[dict], drift: PolicyDrift) \
        -> dict[str, Any]:
    """Refuse a run whose rulebook moved since the pin: denied, audited, nothing executed.

    Each open step gets the same denial the gateway would give it mid-session — its own tool
    and index in the trail — and the run is summarised as one `resume` row. No step is
    evaluated and no tool runs.
    """
    reason = (f"Refused: the rulebook on disk no longer matches the one this workflow was "
              f"pinned to (pinned {drift.expected}, found {drift.found}). No step was evaluated "
              "and no tool ran. A reload with the operator token is required to accept the "
              "new rules.")
    open_steps = [step for step in steps if step["status"] != "done"]
    report: dict[str, Any] = {"workflow_id": workflow_id,
                              "policy_fingerprint": drift.expected,
                              "status": "refused", "steps": []}
    for step in open_steps:
        request = ActionRequest(**step["request"])
        state.record_audit(
            actor=request.actor_id, origin=request.origin, tool=request.tool,
            resource=request.resource_id or ",".join(request.source_ids) or None,
            recipient=request.recipient, allowed=False, rule_id="RULE-POLICY-DRIFT",
            reason=reason, label=None, policy_hash=drift.expected,
            workflow_id=workflow_id, step_index=step["idx"])
        state.set_step(workflow_id, step["idx"], "halted", reason)
        report["steps"].append(_row(step["idx"], describe(step), request.tool, "halted",
                                    "RULE-POLICY-DRIFT", reason, allowed=False))
    actor = ActionRequest(**open_steps[0]["request"]).actor_id if open_steps else "workflow"
    state.record_audit(actor=actor, origin="human", tool="resume", resource=workflow_id,
                       recipient=None, allowed=False, rule_id="RULE-POLICY-DRIFT",
                       reason=reason, label=None, policy_hash=drift.expected,
                       workflow_id=workflow_id)
    return report


def _row(idx: int, proposal: str, tool: str, status: str, rule_id: str, reason: str,
         allowed: bool) -> dict[str, Any]:
    return {"idx": idx, "step": proposal, "tool": tool, "status": status,
            "allowed": allowed, "rule_id": rule_id, "reason": reason}
