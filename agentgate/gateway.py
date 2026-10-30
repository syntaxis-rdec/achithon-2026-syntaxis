"""Gateway: evaluate first, execute only on allow, audit every decision."""

from __future__ import annotations

from . import tools
from .models import ActionRequest, Decision, PolicySet
from .policy import evaluate


def run_action(request: ActionRequest, state, policies: PolicySet) -> tuple[Decision, object | None]:
    decision = evaluate(request, state, policies)
    result: object | None = None
    if decision.allowed:
        result = _dispatch(request, state)
    state.record_audit(
        actor=request.actor_id,
        tool=request.tool,
        resource=request.resource_id or ",".join(request.source_ids) or None,
        recipient=request.recipient,
        allowed=decision.allowed,
        rule_id=decision.rule_id,
        reason=decision.reason,
        label=decision.label,
    )
    return decision, result


def _dispatch(request: ActionRequest, state):
    if request.tool == "read_document":
        return tools.read_document(request.actor_id, request.resource_id or "", state)
    if request.tool == "save_report":
        return tools.save_report(request.actor_id, request.source_ids,
                                 request.title or "Untitled report", state)
    if request.tool == "deliver_inbox":
        return tools.deliver_inbox(request.actor_id, request.resource_id or "",
                                   request.recipient or "", state)
    raise ValueError(f"unknown tool {request.tool}")
