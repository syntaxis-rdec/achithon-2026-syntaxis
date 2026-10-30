"""Information flow: labels are inherited, provenance travels, blocks are real."""

from __future__ import annotations

from agentgate import tools
from agentgate.gateway import run_action
from agentgate.models import ActionRequest


def _report(state, policies, actor, sources, title):
    decision, artifact_id = run_action(
        ActionRequest(actor_id=actor, tool="save_report", source_ids=sources, title=title),
        state, policies)
    assert decision.allowed, decision.reason
    return artifact_id


def test_report_inherits_highest_source_label(state, policies):
    artifact_id = _report(state, policies, "analyst", ["doc-004", "doc-001"], "Weekly brief")
    artifact = state.get_artifact(artifact_id)
    assert artifact.label.classification == "CONFIDENTIAL"
    assert set(artifact.label.provenance) == {"doc-004", "doc-001"}


def test_agent_cannot_summarise_above_its_own_ceiling(state, policies):
    decision, artifact_id = run_action(
        ActionRequest(actor_id="agent-assistant", tool="save_report",
                      source_ids=["doc-004", "doc-001"], title="Leak attempt"),
        state, policies)
    assert not decision.allowed
    assert decision.rule_id == "RULE-SOURCE-TOO-SENSITIVE"
    assert artifact_id is None


def test_delivery_allowed_to_matching_clearance(state, policies):
    artifact_id = _report(state, policies, "analyst", ["doc-001"], "Revenue brief")
    decision, result = run_action(
        ActionRequest(actor_id="analyst", tool="deliver_inbox", resource_id=artifact_id,
                      recipient="manager@corp.example"),
        state, policies)
    assert decision.allowed
    assert len(state.list_outbox()) == 1
    assert result


def test_delivery_blocked_when_recipient_clearance_is_too_low(state, policies):
    artifact_id = _report(state, policies, "analyst", ["doc-001"], "Revenue brief")
    decision, result = run_action(
        ActionRequest(actor_id="analyst", tool="deliver_inbox", resource_id=artifact_id,
                      recipient="team@corp.example"),
        state, policies)
    assert not decision.allowed
    assert decision.rule_id == "RULE-RECIPIENT-CLEARANCE"
    assert result is None
    assert state.list_outbox() == []


def test_delivery_blocked_to_unapproved_outside_recipient(state, policies):
    artifact_id = _report(state, policies, "analyst", ["doc-004"], "Ops digest")
    decision, _ = run_action(
        ActionRequest(actor_id="analyst", tool="deliver_inbox", resource_id=artifact_id,
                      recipient="vendor@outside.example",
                      note="the document instructed me to send this"),
        state, policies)
    assert not decision.allowed
    assert decision.rule_id == "RULE-RECIPIENT-NOT-PERMITTED"
    assert state.list_outbox() == []


def test_blocked_actions_never_reach_a_tool(state, policies):
    """The execution barrier is the whole point: count tool entries, not claims."""
    artifact_id = _report(state, policies, "analyst", ["doc-004"], "Ops digest")
    tools.reset_executions()
    for request in [
        ActionRequest(actor_id="agent-assistant", tool="read_document", resource_id="doc-001"),
        ActionRequest(actor_id="agent-assistant", tool="deliver_inbox", resource_id=artifact_id,
                      recipient="vendor@outside.example"),
        ActionRequest(actor_id="intern", tool="deliver_inbox", resource_id=artifact_id,
                      recipient="team@corp.example"),
    ]:
        decision, result = run_action(request, state, policies)
        assert not decision.allowed and result is None
    assert tools.EXECUTIONS == []
