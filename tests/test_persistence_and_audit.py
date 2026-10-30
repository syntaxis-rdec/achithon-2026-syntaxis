"""Persistence: restrictions survive saving, reloading, and a fresh process."""

from __future__ import annotations

from agentgate.gateway import run_action
from agentgate.models import ActionRequest
from agentgate.policy import load_policy_set
from agentgate.store import Store


def test_labels_survive_a_full_process_restart(tmp_path, policies):
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    first = Store(tmp_path / "persist.sqlite")
    first.load_documents_from_dir(root / "data" / "documents")

    decision, artifact_id = run_action(
        ActionRequest(actor_id="analyst", tool="save_report", source_ids=["doc-001"],
                      title="Revenue brief"), first, policies)
    assert decision.allowed
    first.save_workflow("wf-1", "awaiting_delivery", {"artifact_id": artifact_id})
    first.close()

    # A brand new process reading the same database.
    second = Store(tmp_path / "persist.sqlite")
    workflow = second.get_workflow("wf-1")
    restored = second.get_artifact(workflow["payload"]["artifact_id"])
    assert restored.label.classification == "CONFIDENTIAL"
    assert restored.label.provenance == ["doc-001"]

    blocked, result = run_action(
        ActionRequest(actor_id="agent-assistant", tool="deliver_inbox",
                      resource_id=restored.id, recipient="manager@corp.example",
                      origin="agent"),
        second, policies)
    assert not blocked.allowed
    assert blocked.rule_id == "RULE-ACTOR-CANNOT-RELEASE"
    assert result is None
    assert second.list_outbox() == []
    second.close()


def test_audit_records_every_decision_including_blocks(state, policies):
    attempts = [
        ActionRequest(actor_id="analyst", tool="read_document", resource_id="doc-002"),
        ActionRequest(actor_id="agent-assistant", tool="read_document", resource_id="doc-001"),
    ]
    for request in attempts:
        run_action(request, state, policies)
    audit = state.list_audit()
    assert len(audit) == 2
    assert {row["allowed"] for row in audit} == {0, 1}
    assert all(row["reason"].strip() for row in audit)
    assert all(row["rule_id"].strip() for row in audit)
