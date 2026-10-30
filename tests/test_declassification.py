"""Declassification: human officer only, additive, linked, audited, never a tool."""

from __future__ import annotations

import pytest

from agentgate.gateway import declassify, Session
from agentgate.models import ActionRequest


def _confidential_report(session) -> str:
    decision, artifact_id = session("analyst").submit(
        ActionRequest(tool="save_report", source_ids=["doc-001"]))
    assert decision.allowed
    return artifact_id


def test_analyst_cannot_declassify(session, state, policies):
    artifact_id = _confidential_report(session)
    with pytest.raises(PermissionError):
        declassify(state, policies, "analyst", artifact_id, "INTERNAL",
                   "the customer already published this")
    audit = state.list_audit()[0]
    assert audit["rule_id"] == "RULE-DECLASSIFY-ROLE"
    assert audit["allowed"] == 0


def test_officer_creates_a_new_linked_artifact_and_original_is_untouched(session, state, policies):
    artifact_id = _confidential_report(session)
    original = state.get_artifact(artifact_id)
    child = declassify(state, policies, "security-officer", artifact_id, "INTERNAL",
                       "approved for the internal newsletter after legal review")
    assert child.id != artifact_id
    assert child.label.classification == "INTERNAL"
    assert artifact_id in child.label.provenance
    assert state.get_artifact(artifact_id).label.classification == "CONFIDENTIAL"
    assert state.get_artifact(artifact_id).body == child.body
    audit = state.list_audit()[0]
    assert audit["tool"] == "declassify" and audit["allowed"] == 1
    assert audit["rule_id"] == "DECLASSIFY-OFFICER"


def test_short_justification_is_rejected(session, state, policies):
    artifact_id = _confidential_report(session)
    with pytest.raises(ValueError):
        declassify(state, policies, "security-officer", artifact_id, "INTERNAL", "ok")
    assert state.list_audit()[0]["rule_id"] == "RULE-DECLASSIFY-JUSTIFICATION"


def test_declassification_can_only_lower(session, state, policies):
    artifact_id = _confidential_report(session)
    with pytest.raises(ValueError):
        declassify(state, policies, "security-officer", artifact_id, "RESTRICTED",
                   "attempting to raise instead of lower")


def test_release_is_not_delivery_rights(session, state, policies):
    """The officer can lower a label, but has no send rule of their own."""
    artifact_id = _confidential_report(session)
    child = declassify(state, policies, "security-officer", artifact_id, "INTERNAL",
                       "released for internal circulation with a written reason")
    decision, result = session("security-officer").submit(
        ActionRequest(tool="deliver_inbox", resource_id=child.id,
                      recipient="team@corp.example"))
    assert not decision.allowed
    assert decision.rule_id == "RULE-NO-GRANT"
    assert result is None


def test_declassify_is_not_reachable_as_a_tool(session):
    from agentgate.models import ActionRequest as R
    with pytest.raises(Exception):
        R(tool="declassify", resource_id="x")
