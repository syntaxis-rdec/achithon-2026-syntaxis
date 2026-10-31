"""Unit tests for the policy integrity guard.

The red-team harness attacks the guard through the gateway. These cover the API itself:
the pin is comparable with a loaded rulebook, drift refuses everything, and the only way
out is the operator token.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agentgate.gateway import Session
from agentgate.models import ActionRequest
from agentgate.policy import load_policy_set
from agentgate.policy_guard import Guard, PolicyDrift, fingerprint, unadopted_rows
from agentgate.sessions import SessionRegistry
from agentgate.store import Store

ROOT = Path(__file__).resolve().parent.parent
PRINCIPALS = ROOT / "data" / "principals.json"
POLICIES = ROOT / "data" / "policies.json"
TOKEN = "unit-test-token"


@pytest.fixture()
def rulebook(tmp_path):
    """Copies of the real files, so no test ever edits data/."""
    principals = tmp_path / "principals.json"
    policies = tmp_path / "policies.json"
    principals.write_text(PRINCIPALS.read_text(encoding="utf-8"), encoding="utf-8")
    policies.write_text(POLICIES.read_text(encoding="utf-8"), encoding="utf-8")
    return principals, policies


def test_the_pin_equals_a_loaded_rulebook_fingerprint(rulebook):
    principals, policies = rulebook
    loaded = load_policy_set(principals, policies)
    assert Guard(principals, policies).recorded == loaded.fingerprint == fingerprint(
        principals, policies)


def test_a_byte_change_in_either_file_is_drift(rulebook):
    principals, policies = rulebook
    guard = Guard(principals, policies)
    policies.write_text(policies.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(PolicyDrift) as caught:
        guard.check()
    assert caught.value.expected == guard.recorded
    assert caught.value.found != guard.recorded


def test_drift_status_reports_instead_of_raising(rulebook):
    principals, policies = rulebook
    guard = Guard(principals, policies)
    assert guard.drift_status() is None
    rules = json.loads(policies.read_text(encoding="utf-8"))
    rules[0]["max_classification"] = "PUBLIC"
    policies.write_text(json.dumps(rules), encoding="utf-8")
    assert guard.drift_status().found != guard.recorded


def test_reload_needs_the_operator_token(rulebook):
    principals, policies = rulebook
    guard = Guard(principals, policies, token=TOKEN)
    for rejected in (None, "", "wrong"):
        with pytest.raises(PermissionError):
            guard.reload(rejected)


def test_a_guard_without_a_token_can_never_reload(rulebook):
    principals, policies = rulebook
    guard = Guard(principals, policies)
    with pytest.raises(PermissionError):
        guard.reload(None)


def test_reload_swaps_the_pin_and_records_both(rulebook):
    principals, policies = rulebook
    guard = Guard(principals, policies, token=TOKEN)
    before = guard.recorded
    rules = json.loads(policies.read_text(encoding="utf-8"))
    rules[0]["max_classification"] = "RESTRICTED"
    policies.write_text(json.dumps(rules), encoding="utf-8")

    adopted = guard.reload(TOKEN)
    assert guard.recorded == guard.current() != before
    assert guard.reloads == [(before, guard.recorded)]
    assert adopted.fingerprint == guard.recorded


def test_a_drifting_rulebook_denies_before_any_tool_runs(tmp_path, rulebook):
    principals, policies_file = rulebook
    store = Store(tmp_path / "guard.sqlite")
    store.load_documents_from_dir(ROOT / "data" / "documents")
    policies = load_policy_set(principals, policies_file)
    guard = Guard(principals, policies_file, token=TOKEN)

    session = Session(store, policies, "intern", "human", guard)
    decision, result = session.submit(ActionRequest(tool="read_document", resource_id="doc-002"))
    assert decision.allowed and result is not None

    rules = json.loads(policies_file.read_text(encoding="utf-8"))
    rules[0]["max_classification"] = "RESTRICTED"
    policies_file.write_text(json.dumps(rules), encoding="utf-8")

    decision, result = session.submit(ActionRequest(tool="read_document", resource_id="doc-002"))
    assert not decision.allowed and result is None
    assert decision.rule_id == "RULE-POLICY-DRIFT"
    row = store.list_audit()[0]
    assert row["allowed"] == 0 and row["rule_id"] == "RULE-POLICY-DRIFT"
    assert row["policy_hash"] == policies.fingerprint
    assert "doc-002" not in str(result)


def test_a_guarded_registry_adopts_only_through_reload(rulebook):
    principals, policies_file = rulebook
    policies = load_policy_set(principals, policies_file)
    registry = SessionRegistry(None, policies, Guard(principals, policies_file, token=TOKEN))
    other = load_policy_set(principals, policies_file)
    other = other.model_copy(update={"fingerprint": "deadbeefdeadbeef"})

    with pytest.raises(PermissionError):
        registry.refresh(other)
    with pytest.raises(PermissionError):
        SessionRegistry(None, policies).reload_rulebook(TOKEN)


def test_adopting_and_refusing_a_rulebook_both_leave_a_trace(tmp_path, rulebook):
    principals, policies_file = rulebook
    store = Store(tmp_path / "reload.sqlite")
    policies = load_policy_set(principals, policies_file)
    registry = SessionRegistry(store, policies, Guard(principals, policies_file, token=TOKEN))
    rules = json.loads(policies_file.read_text(encoding="utf-8"))
    rules[0]["max_classification"] = "RESTRICTED"
    policies_file.write_text(json.dumps(rules), encoding="utf-8")

    with pytest.raises(PermissionError):
        registry.reload_rulebook("wrong")
    refused = store.list_audit()[0]
    assert refused["rule_id"] == "RULE-POLICY-RELOAD-REFUSED" and refused["allowed"] == 0

    adopted = registry.reload_rulebook(TOKEN)
    row = store.list_audit()[0]
    assert row["rule_id"] == "POLICY-RELOAD" and row["allowed"] == 1
    assert row["policy_hash"] == adopted.fingerprint
    assert adopted.fingerprint != refused["policy_hash"]
    assert store.list_audit()[1]["rule_id"] == "RULE-POLICY-RELOAD-REFUSED"


def _scratch_data(tmp_path):
    """A copy of `data/` the dashboard can own, the way demo/seed.py hands one over."""
    data = tmp_path / "data"
    data.mkdir()
    shutil.copytree(ROOT / "data" / "documents", data / "documents")
    shutil.copy(PRINCIPALS, data / "principals.json")
    shutil.copy(POLICIES, data / "policies.json")
    return data


def test_the_dashboard_refuses_a_rulebook_swapped_between_clicks(tmp_path, monkeypatch):
    """Pinned mode, real app.py, one swap and two clicks. The guard is not only an API."""
    from streamlit.testing.v1 import AppTest

    data = _scratch_data(tmp_path)
    monkeypatch.setenv("AGENTGATE_DATA_DIR", str(data))
    monkeypatch.setenv("AGENTGATE_PIN_RULEBOOK", "1")
    monkeypatch.setenv("AGENTGATE_RELOAD_TOKEN", TOKEN)

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.run()
    assert [e.value for e in at.exception] == []
    assert at.error == []

    rules = json.loads((data / "policies.json").read_text(encoding="utf-8"))
    rules[0]["max_classification"] = "RESTRICTED"
    (data / "policies.json").write_text(json.dumps(rules), encoding="utf-8")
    at.run()
    assert any("RULE-POLICY-DRIFT" in error.value for error in at.error)

    def submit_form(with_token: str):
        at.text_input[0].set_value(with_token)
        accept = [button for button in at.button
                  if button.label == "Accept the rulebook now on disk"]
        assert accept, "the reload form never rendered"
        accept[0].click()
        at.run()

    submit_form("wrong")
    assert any("RULE-POLICY-DRIFT" in error.value for error in at.error)
    refused = Store(data / "agentgate-v3.sqlite").list_audit()[0]
    assert refused["rule_id"] == "RULE-POLICY-RELOAD-REFUSED" and refused["allowed"] == 0

    submit_form(TOKEN)
    assert at.error == []
    adopted = Store(data / "agentgate-v3.sqlite").list_audit()[0]
    assert adopted["rule_id"] == "POLICY-RELOAD" and adopted["allowed"] == 1


def test_a_vanished_rulebook_is_refused_not_crashed(tmp_path, rulebook):
    """A deleted file is a denial, not a traceback in the middle of a decision."""
    principals, policies_file = rulebook
    store = Store(tmp_path / "gone.sqlite")
    store.load_documents_from_dir(ROOT / "data" / "documents")
    policies = load_policy_set(principals, policies_file)
    session = Session(store, policies, "intern", "human", Guard(principals, policies_file))

    allowed, _ = session.submit(ActionRequest(tool="read_document", resource_id="doc-002"))
    assert allowed.allowed

    policies_file.unlink()
    decision, result = session.submit(ActionRequest(tool="read_document", resource_id="doc-002"))
    assert not decision.allowed and result is None
    assert decision.rule_id == "RULE-POLICY-DRIFT" and "unreadable" in decision.reason
    assert store.list_audit()[0]["rule_id"] == "RULE-POLICY-DRIFT"


def test_a_malformed_rulebook_cannot_be_adopted(tmp_path, rulebook):
    """The token is not enough: the file the operator points at has to parse."""
    principals, policies_file = rulebook
    guard = Guard(principals, policies_file, token=TOKEN)
    before = guard.recorded
    policies_file.write_text("{ not json", encoding="utf-8")

    with pytest.raises(PermissionError):
        guard.reload(TOKEN)
    assert guard.recorded == before and guard.reloads == []


def test_the_detector_names_a_decision_made_off_the_pin(tmp_path, rulebook):
    """Anything that forgets the guard still leaves its hash on the row, so it is findable."""
    principals, policies_file = rulebook
    store = Store(tmp_path / "ghosts.sqlite")
    store.load_documents_from_dir(ROOT / "data" / "documents")
    guard = Guard(principals, policies_file, token=TOKEN)
    pinned = load_policy_set(principals, policies_file)

    Session(store, pinned, "intern", "human", guard).submit(
        ActionRequest(tool="read_document", resource_id="doc-002"))
    assert unadopted_rows(store, guard) == []

    rules = json.loads(policies_file.read_text(encoding="utf-8"))
    rules[0]["max_classification"] = "RESTRICTED"
    policies_file.write_text(json.dumps(rules), encoding="utf-8")
    drifted = load_policy_set(principals, policies_file)
    Session(store, drifted, "intern", "human").submit(
        ActionRequest(tool="read_document", resource_id="doc-002"))

    ghosts = unadopted_rows(store, guard)
    assert len(ghosts) == 1 and ghosts[0]["policy_hash"] == drifted.fingerprint


def _pinned(tmp_path, rulebook):
    """A guard over a copy of the rulebook plus the document set, in a scratch world."""
    from agentgate.policy_guard import Guard
    from agentgate.store import Store

    principals, policies_file = rulebook
    docs = tmp_path / "docs"
    shutil.copytree(ROOT / "data" / "documents", docs)
    store = Store(tmp_path / "pin.sqlite")
    store.load_documents_from_dir(docs)
    return store, Guard(principals, policies_file, token=TOKEN, documents_path=docs), docs


def test_a_pinned_document_set_refuses_a_document_minted_after_the_pin(tmp_path, rulebook):
    """The one thing per-document fingerprints cannot see: a file that was never registered."""
    store, guard, docs = _pinned(tmp_path, rulebook)
    policies = load_policy_set(*[guard.principals_path, guard.policies_path])

    allowed, _ = Session(store, policies, "intern", "human", guard).submit(
        ActionRequest(tool="read_document", resource_id="doc-002"))
    assert allowed.allowed

    (docs / "doc-999-forged.md").write_text(
        "---\nid: doc-999\ntitle: Public Trivia\nclassification: PUBLIC\nowner: attacker\n---\n"
        "Nothing sensitive here.\n", encoding="utf-8")
    store.load_documents_from_dir(docs)
    assert store.get_document("doc-999").classification == "PUBLIC", "the store trusts it on sight"

    decision, result = Session(store, policies, "intern", "human", guard).submit(
        ActionRequest(tool="read_document", resource_id="doc-999"))
    assert not decision.allowed and result is None
    assert decision.rule_id == "RULE-DOCUMENT-DRIFT"
    assert "document set" in decision.reason
    assert store.list_audit()[0]["rule_id"] == "RULE-DOCUMENT-DRIFT"


def test_an_edit_to_a_registered_document_also_breaks_the_document_pin(tmp_path, rulebook):
    store, guard, docs = _pinned(tmp_path, rulebook)
    target = docs / "doc-004-support.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nappended\n", encoding="utf-8")
    with pytest.raises(PolicyDrift) as caught:
        guard.check()
    assert caught.value.kind == "documents"


def test_without_a_document_pin_a_minted_document_is_still_trusted(tmp_path, rulebook):
    """Statement of the default, so nobody mistakes an opt-in control for unconditional safety."""
    from agentgate.store import Store

    principals, policies_file = rulebook
    docs = tmp_path / "unpinned"
    shutil.copytree(ROOT / "data" / "documents", docs)
    store = Store(tmp_path / "unpinned.sqlite")
    store.load_documents_from_dir(docs)
    guard = Guard(principals, policies_file, token=TOKEN)  # documents_path not given
    (docs / "doc-888.md").write_text(
        "---\nid: doc-888\ntitle: Forged\nclassification: PUBLIC\nowner: attacker\n---\nx\n",
        encoding="utf-8")
    store.load_documents_from_dir(docs)

    decision, result = Session(store, load_policy_set(principals, policies_file),
                               "intern", "human", guard).submit(
        ActionRequest(tool="read_document", resource_id="doc-888"))
    assert decision.allowed, "the rulebook pin alone cannot see a new file — that is the limitation"
    assert result is not None


def test_adopting_a_rulebook_re_pins_the_document_set_too(tmp_path, rulebook):
    """One token, both pins: an operator who reloads has accepted the new state of both."""
    store, guard, docs = _pinned(tmp_path, rulebook)
    before = guard.pinned_documents
    (docs / "doc-777.md").write_text(
        "---\nid: doc-777\ntitle: Added legitimately\nclassification: PUBLIC\nowner: ops\n---\nx\n",
        encoding="utf-8")
    with pytest.raises(PolicyDrift):
        guard.check()

    guard.reload(TOKEN)
    assert guard.pinned_documents != before
    guard.check()
    store.load_documents_from_dir(docs)
    decision, _ = Session(store, load_policy_set(guard.principals_path, guard.policies_path),
                          "intern", "human", guard).submit(
        ActionRequest(tool="read_document", resource_id="doc-777"))
    assert decision.allowed
