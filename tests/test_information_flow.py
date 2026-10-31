"""Information flow, taint, tamper handling, and the execution barrier."""

from __future__ import annotations

from pathlib import Path

from agentgate import tools
from agentgate.gateway import Session
from agentgate.models import ActionRequest
from agentgate.store import Store


def test_report_inherits_highest_source_label(session, state):
    decision, artifact_id = session("analyst").submit(
        ActionRequest(tool="save_report", source_ids=["doc-004", "doc-001"]))
    assert decision.allowed
    artifact = state.get_artifact(artifact_id)
    assert artifact.label.classification == "CONFIDENTIAL"
    assert set(artifact.label.provenance) == {"doc-004", "doc-001"}


def test_hidden_source_is_recovered_from_read_history(session, state):
    reader = session("analyst")
    read, _ = reader.submit(ActionRequest(tool="read_document", resource_id="doc-001"))
    assert read.allowed
    decision, artifact_id = reader.submit(
        ActionRequest(tool="save_report", source_ids=["doc-002"]))
    assert decision.allowed
    artifact = state.get_artifact(artifact_id)
    assert artifact.label.classification == "CONFIDENTIAL"
    assert set(artifact.label.provenance) == {"doc-001", "doc-002"}


def test_title_cannot_carry_a_secret(session, state):
    decision, artifact_id = session("intern").submit(
        ActionRequest(tool="save_report", source_ids=["doc-002"],
                      title="Q3 revenue is 4.2 crore — confidential"))
    assert decision.allowed
    artifact = state.get_artifact(artifact_id)
    assert "4.2 crore" not in artifact.title
    assert artifact.title.startswith("Summary of doc-002")


def test_tampered_document_is_frozen_at_its_original_label(tmp_path, policies):
    root = Path(__file__).resolve().parent.parent
    docs = tmp_path / "docs"
    docs.mkdir()
    original = (root / "data" / "documents" / "doc-003-contract-injection.md").read_text(encoding="utf-8")
    (docs / "doc-003-contract-injection.md").write_text(original, encoding="utf-8")
    store = Store(tmp_path / "t.sqlite")
    store.load_documents_from_dir(docs)

    (docs / "doc-003-contract-injection.md").write_text(
        original.replace("classification: RESTRICTED", "classification: INTERNAL"), encoding="utf-8")
    store.load_documents_from_dir(docs)

    assert store.integrity_of("doc-003") == "tampered"
    assert store.get_document("doc-003").classification == "RESTRICTED"
    decision, _ = Session(store, policies, "analyst").submit(
        ActionRequest(tool="read_document", resource_id="doc-003"))
    assert not decision.allowed
    assert decision.rule_id == "RULE-DOC-INTEGRITY"


def test_delivery_blocked_when_recipient_clearance_is_too_low(session, state):
    dec, artifact_id = session("analyst").submit(
        ActionRequest(tool="save_report", source_ids=["doc-001"]))
    assert dec.allowed
    decision, result = session("analyst").submit(
        ActionRequest(tool="deliver_inbox", resource_id=artifact_id,
                      recipient="team@corp.example"))
    assert not decision.allowed
    assert decision.rule_id == "RULE-RECIPIENT-CLEARANCE"
    assert result is None
    assert state.list_outbox() == []


def test_delivery_allowed_to_matching_clearance(session, state):
    decision, artifact_id = session("analyst").submit(
        ActionRequest(tool="save_report", source_ids=["doc-004"]))
    assert decision.allowed
    decision, _ = session("analyst").submit(
        ActionRequest(tool="deliver_inbox", resource_id=artifact_id,
                      recipient="manager@corp.example"))
    assert decision.allowed
    assert len(state.list_outbox()) == 1
    assert state.list_outbox()[0]["classification"] == "INTERNAL"


def test_blocked_actions_never_reach_a_tool(session):
    dec, artifact_id = session("analyst").submit(
        ActionRequest(tool="save_report", source_ids=["doc-004"]))
    assert dec.allowed
    tools.reset_executions()
    attempts = [
        ("agent-assistant", "agent", ActionRequest(tool="read_document", resource_id="doc-001")),
        ("agent-assistant", "agent", ActionRequest(tool="deliver_inbox",
                                                   resource_id=artifact_id,
                                                   recipient="vendor@outside.example")),
        ("intern", "human", ActionRequest(tool="deliver_inbox", resource_id=artifact_id,
                                          recipient="team@corp.example")),
    ]
    for actor, origin, request in attempts:
        decision, result = session(actor, origin).submit(request)
        assert not decision.allowed and result is None
    assert tools.EXECUTIONS == []
