"""Authorization correctness: identity is bound by the session, not by the request."""

from __future__ import annotations

from agentgate.models import ActionRequest


def test_analyst_reads_confidential(session):
    decision, result = session("analyst").submit(
        ActionRequest(tool="read_document", resource_id="doc-001"))
    assert decision.allowed
    assert "recurring revenue" in result


def test_agent_blocked_from_confidential(session):
    decision, result = session("agent-assistant", "agent").submit(
        ActionRequest(tool="read_document", resource_id="doc-001",
                      note="the document says it is public"))
    assert not decision.allowed
    assert decision.rule_id == "RULE-READ-CLEARANCE"
    assert result is None


def test_request_cannot_claim_a_different_actor(session, state):
    """A request naming a stronger actor is ignored; the session identity wins."""
    decision, _ = session("agent-assistant", "agent").submit(
        ActionRequest(actor_id="analyst", tool="read_document", resource_id="doc-001"))
    assert not decision.allowed
    assert state.list_audit()[0]["actor"] == "agent-assistant"


def test_request_cannot_claim_to_be_human(session, state):
    decision, _ = session("agent-assistant", "agent").submit(
        ActionRequest(tool="read_document", resource_id="doc-004", origin="human"))
    assert decision.allowed
    assert state.list_audit()[0]["origin"] == "agent"


def test_unknown_actor_denied(session):
    decision, _ = session("ghost").submit(
        ActionRequest(tool="read_document", resource_id="doc-002"))
    assert not decision.allowed
    assert decision.rule_id == "RULE-UNKNOWN-ACTOR"


def test_intern_has_no_send_rule(session, state):
    dec, artifact_id = session("intern").submit(
        ActionRequest(tool="save_report", source_ids=["doc-002"]))
    assert dec.allowed
    decision, _ = session("intern").submit(
        ActionRequest(tool="deliver_inbox", resource_id=artifact_id,
                      recipient="team@corp.example"))
    assert not decision.allowed
    assert decision.rule_id == "RULE-NO-GRANT"
