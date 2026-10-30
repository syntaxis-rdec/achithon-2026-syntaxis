"""Persistence across a restart, audit completeness, and audit-before-execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentgate import tools
from agentgate.gateway import Session
from agentgate.models import ActionRequest
from agentgate.store import Store


def _docs_root() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "documents"


def test_labels_survive_a_full_process_restart(tmp_path, policies):
    first = Store(tmp_path / "persist.sqlite")
    first.load_documents_from_dir(_docs_root())
    decision, artifact_id = Session(first, policies, "analyst").submit(
        ActionRequest(tool="save_report", source_ids=["doc-001"]))
    assert decision.allowed
    first.close()

    second = Store(tmp_path / "persist.sqlite")
    restored = second.get_artifact(artifact_id)
    assert restored.label.classification == "CONFIDENTIAL"
    assert restored.label.provenance == ["doc-001"]

    blocked, result = Session(second, policies, "agent-assistant", "agent").submit(
        ActionRequest(tool="deliver_inbox", resource_id=artifact_id,
                      recipient="manager@corp.example"))
    assert not blocked.allowed
    assert blocked.rule_id == "RULE-ACTOR-CANNOT-RELEASE"
    assert result is None
    assert second.list_outbox() == []
    second.close()


def test_audit_records_origin_rule_and_policy_fingerprint(session, state, policies):
    session("analyst").submit(ActionRequest(tool="read_document", resource_id="doc-002"))
    session("agent-assistant", "agent").submit(
        ActionRequest(tool="read_document", resource_id="doc-001"))
    audit = state.list_audit()
    assert len(audit) == 2
    assert {row["allowed"] for row in audit} == {0, 1}
    assert {row["origin"] for row in audit} == {"human", "agent"}
    assert all(row["policy_hash"] == policies.fingerprint for row in audit)
    assert all(row["reason"].strip() and row["rule_id"].strip() for row in audit)


def test_audit_row_exists_even_when_the_tool_crashes(session, state, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(tools, "read_document", boom)
    with pytest.raises(RuntimeError):
        session("analyst").submit(ActionRequest(tool="read_document", resource_id="doc-002"))
    audit = state.list_audit()
    assert audit and audit[0]["allowed"] == 1
    assert audit[0]["tool"] == "read_document"
