"""Unit tests for the policy integrity guard.

The red-team harness attacks the guard through the gateway. These cover the API itself:
the pin is comparable with a loaded rulebook, drift refuses everything, and the only way
out is the operator token.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentgate.gateway import Session
from agentgate.models import ActionRequest
from agentgate.policy import load_policy_set
from agentgate.policy_guard import Guard, PolicyDrift, fingerprint
from agentgate.sessions import SessionRegistry

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
    from agentgate.store import Store

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
    from agentgate.store import Store

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
