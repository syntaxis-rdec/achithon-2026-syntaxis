"""Authorization correctness: who may do what, and default deny."""

from __future__ import annotations

from agentgate.gateway import run_action
from agentgate.models import ActionRequest


def test_analyst_reads_confidential(state, policies):
    decision, result = run_action(
        ActionRequest(actor_id="analyst", tool="read_document", resource_id="doc-001"),
        state, policies)
    assert decision.allowed
    assert "recurring revenue" in result


def test_agent_blocked_from_confidential(state, policies):
    decision, result = run_action(
        ActionRequest(actor_id="agent-assistant", tool="read_document", resource_id="doc-001",
                      origin="agent", note="the document says it is public"),
        state, policies)
    assert not decision.allowed
    assert decision.rule_id == "RULE-READ-CLEARANCE"
    assert result is None


def test_intern_reads_public(state, policies):
    decision, _ = run_action(
        ActionRequest(actor_id="intern", tool="read_document", resource_id="doc-002"),
        state, policies)
    assert decision.allowed


def test_injection_text_in_a_document_grants_nothing(state, policies):
    """doc-003 claims to be PUBLIC and orders an external send. Both are ignored."""
    decision, _ = run_action(
        ActionRequest(actor_id="agent-assistant", tool="read_document", resource_id="doc-003",
                      origin="agent"),
        state, policies)
    assert not decision.allowed
    assert decision.rule_id == "RULE-READ-CLEARANCE"


def test_unknown_actor_denied(state, policies):
    decision, _ = run_action(
        ActionRequest(actor_id="ghost", tool="read_document", resource_id="doc-002"),
        state, policies)
    assert not decision.allowed
    assert decision.rule_id == "RULE-UNKNOWN-ACTOR"


def test_missing_send_rule_falls_back_to_default_deny(state, policies):
    state_artifact = _make_public_report(state, policies)
    decision, _ = run_action(
        ActionRequest(actor_id="intern", tool="deliver_inbox", resource_id=state_artifact,
                      recipient="team@corp.example"),
        state, policies)
    assert not decision.allowed
    assert decision.rule_id == "RULE-NO-GRANT"


def _make_public_report(state, policies) -> str:
    _, artifact_id = run_action(
        ActionRequest(actor_id="intern", tool="save_report", source_ids=["doc-002"],
                      title="Menu digest"),
        state, policies)
    return artifact_id
