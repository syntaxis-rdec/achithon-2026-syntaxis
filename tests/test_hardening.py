"""Hardening: capability gate, malformed input, justification, officer limits, resumption taint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentgate import tools
from agentgate.gateway import Session, declassify
from agentgate.models import ActionRequest
from agentgate.policy import load_policy_set
from agentgate.store import Store

ROOT = Path(__file__).resolve().parent.parent


def test_tools_refuse_direct_calls(state):
    with pytest.raises(PermissionError):
        tools.read_document("intern", "doc-001", state)
    with pytest.raises(PermissionError):
        tools.deliver_inbox("intern", "x", "vendor@outside.example", state)


def test_duplicate_role_tool_rules_are_rejected(tmp_path):
    principals = json.loads((ROOT / "data" / "principals.json").read_text())
    rules = json.loads((ROOT / "data" / "policies.json").read_text())
    rules.append({"id": "READ-INTERN-WIDE", "role": "intern", "tool": "read_document",
                  "max_classification": "CONFIDENTIAL"})
    (tmp_path / "p.json").write_text(json.dumps(principals))
    (tmp_path / "r.json").write_text(json.dumps(rules))
    with pytest.raises(ValueError, match="duplicate policy rules"):
        load_policy_set(tmp_path / "p.json", tmp_path / "r.json")


def test_unknown_classification_fails_closed(tmp_path, policies):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "doc-bad.md").write_text(
        "---\nid: doc-bad\ntitle: Bad Label\nclassification: SECRET\nowner: ops\n---\nbody\n",
        encoding="utf-8")
    store = Store(tmp_path / "b.sqlite")
    store.load_documents_from_dir(docs)
    assert store.integrity_of("doc-bad") == "invalid"
    assert store.get_document("doc-bad").classification == "RESTRICTED"
    decision, _ = Session(store, policies, "analyst").submit(
        ActionRequest(tool="read_document", resource_id="doc-bad"))
    assert not decision.allowed
    assert decision.rule_id == "RULE-DOC-INVALID"


def test_title_only_edit_is_detected_as_tampering(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    text = "---\nid: doc-t\ntitle: Original\nowner: ops\nclassification: INTERNAL\n---\nbody\n"
    (docs / "doc-t.md").write_text(text, encoding="utf-8")
    store = Store(tmp_path / "t.sqlite")
    store.load_documents_from_dir(docs)
    (docs / "doc-t.md").write_text(text.replace("title: Original", "title: Rewritten"),
                                   encoding="utf-8")
    store.load_documents_from_dir(docs)
    assert store.integrity_of("doc-t") == "tampered"


def test_justification_is_stored_with_the_release(session, state, policies):
    dec, artifact_id = session("analyst").submit(
        ActionRequest(tool="save_report", source_ids=["doc-001"]))
    assert dec.allowed
    marker = "approved by legal after the press release"
    declassify(state, policies, "security-officer", artifact_id, "INTERNAL", marker)
    row = state.list_audit()[0]
    assert row["justification"] == marker


def test_officer_clearance_must_cover_the_artifact(tmp_path, state):
    principals = json.loads((ROOT / "data" / "principals.json").read_text())
    for person in principals:
        if person["id"] == "security-officer":
            person["clearance"] = "INTERNAL"
    (tmp_path / "p.json").write_text(json.dumps(principals))
    (tmp_path / "r.json").write_text((ROOT / "data" / "policies.json").read_text())
    weak = load_policy_set(tmp_path / "p.json", tmp_path / "r.json")
    dec, artifact_id = Session(state, weak, "analyst").submit(
        ActionRequest(tool="save_report", source_ids=["doc-001"]))
    assert dec.allowed
    with pytest.raises(PermissionError):
        declassify(state, weak, "security-officer", artifact_id, "PUBLIC",
                   "a long enough justification string")
    assert state.list_audit()[0]["rule_id"] == "RULE-DECLASSIFY-CLEARANCE"


def test_report_from_a_later_tampered_source_cannot_be_delivered(tmp_path, policies):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "doc-s.md").write_text(
        "---\nid: doc-s\ntitle: Source\nowner: ops\nclassification: INTERNAL\n---\nbody line\n",
        encoding="utf-8")
    store = Store(tmp_path / "s.sqlite")
    store.load_documents_from_dir(docs)
    analyst = Session(store, policies, "analyst")
    dec, artifact_id = analyst.submit(ActionRequest(tool="save_report", source_ids=["doc-s"]))
    assert dec.allowed

    (docs / "doc-s.md").write_text(
        "---\nid: doc-s\ntitle: Source\nowner: ops\nclassification: INTERNAL\n---\nchanged body\n",
        encoding="utf-8")
    store.load_documents_from_dir(docs)

    decision, result = analyst.submit(
        ActionRequest(tool="deliver_inbox", resource_id=artifact_id,
                      recipient="manager@corp.example"))
    assert not decision.allowed
    assert decision.rule_id == "RULE-PROVENANCE-TAMPERED"
    assert result is None
    assert store.list_outbox() == []


def test_registry_keeps_read_history_across_clicks(registry, state):
    first = registry.get("analyst")
    first.submit(ActionRequest(tool="read_document", resource_id="doc-001"))
    second = registry.get("analyst")
    assert first is second
    decision, artifact_id = second.submit(
        ActionRequest(tool="save_report", source_ids=["doc-002"]))
    assert decision.allowed
    assert state.get_artifact(artifact_id).label.classification == "CONFIDENTIAL"


def test_registry_refresh_applies_new_rules_without_restart(registry, tmp_path):
    session = registry.get("analyst")
    allowed, _ = session.submit(ActionRequest(tool="read_document", resource_id="doc-001"))
    assert allowed.allowed

    rules = json.loads((ROOT / "data" / "policies.json").read_text())
    for rule in rules:
        if rule["id"] == "READ-ANALYST":
            rule["max_classification"] = "PUBLIC"
    (tmp_path / "r.json").write_text(json.dumps(rules))
    tightened = load_policy_set(ROOT / "data" / "principals.json", tmp_path / "r.json")
    registry.refresh(tightened)

    denied, _ = session.submit(ActionRequest(tool="read_document", resource_id="doc-001"))
    assert not denied.allowed
    assert denied.rule_id == "RULE-READ-CLEARANCE"
