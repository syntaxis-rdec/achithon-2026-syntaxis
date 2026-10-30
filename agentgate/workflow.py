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

STATUSES = ("pending", "done", "blocked", "halted")


def create(state, steps: list[ActionRequest], title: str = "workflow",
           workflow_id: str | None = None) -> str:
    """Store an ordered list of proposals. No policy is consulted until a run."""
    requests = [step.model_dump() if isinstance(step, ActionRequest) else dict(step)
                for step in steps]
    if not requests:
        raise ValueError("a workflow needs at least one step")
    wf = workflow_id or "wf-" + uuid.uuid4().hex[:8]
    state.save_workflow(wf, "active", {"title": title, "step_count": len(requests)})
    state.add_steps(wf, requests)
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
           policies_path: str | Path) -> dict[str, Any]:
    """Run the workflow from the first step that is not done."""
    policies = load_policy_set(principals_path, policies_path)
    steps = state.steps_for(workflow_id)
    payload = state.get_workflow(workflow_id)["payload"]
    outputs = {step["idx"]: step["output"] for step in steps}
    report: dict[str, Any] = {"workflow_id": workflow_id,
                              "policy_fingerprint": policies.fingerprint,
                              "status": "", "steps": []}

    for position, step in enumerate(steps):
        if step["status"] == "done":
            continue

        request = _chain(ActionRequest(**step["request"]), outputs)
        session = Session(state, policies, request.actor_id, request.origin)
        decision, result = session.submit(request, workflow_id=workflow_id,
                                          step_index=step["idx"])

        if decision.allowed:
            output = str(result) if request.tool == "save_report" else ""
            state.set_step(workflow_id, step["idx"], "done", decision.reason, output)
            outputs[step["idx"]] = output
            report["steps"].append(_row(step["idx"], describe(step), request.tool, "done",
                                        decision.rule_id, decision.reason, True))
            continue

        state.set_step(workflow_id, step["idx"], "blocked", decision.reason)
        report["steps"].append(_row(step["idx"], describe(step), request.tool, "blocked",
                                    decision.rule_id, decision.reason, False))
        for later in steps[position + 1:]:
            reason = f"Not run: step {step['idx']} was blocked."
            state.set_step(workflow_id, later["idx"], "halted", reason)
            report["steps"].append(_row(later["idx"], describe(later),
                                        ActionRequest(**later["request"]).tool, "halted",
                                        "WORKFLOW-HALTED", reason, False))
        report["status"] = "halted"
        state.save_workflow(workflow_id, "halted", payload)
        return report

    report["status"] = "completed"
    state.save_workflow(workflow_id, "completed", payload)
    return report


def _row(idx: int, proposal: str, tool: str, status: str, rule_id: str, reason: str,
         allowed: bool) -> dict[str, Any]:
    return {"idx": idx, "step": proposal, "tool": tool, "status": status,
            "allowed": allowed, "rule_id": rule_id, "reason": reason}
