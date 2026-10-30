"""Tests for the audit export: what a reviewer gets, and what must never be in it.

The store is the real one from `conftest.py` (four sample documents, real policy), so these tests
export the same rows the dashboard would write, not a hand-made soup of dicts.
"""

from __future__ import annotations

import csv
import json

import pytest

from agentgate import export
from agentgate.models import ActionRequest

SECRETS = {
    "openai": "sk-live-abcdefghijklmnop",
    "github": "ghp_abcdefghijklmnop1234",
    "bearer": "eyJhbGciOiJIUzI1NiJ9.payload.sig",
    "hex": "0123456789abcdef0123456789abcdef",
}
POLICY_FINGERPRINT = "12a49fe3ae7fc597"  # 16 chars: shown on purpose, never redacted


def _pack(store, directory):
    counter = [0]
    audit_rows = export.export_audit(store, directory, counter)
    outbox_rows = export.export_outbox(store, directory, counter)
    return export.export_summary(store, directory, audit_rows, outbox_rows, counter[0])


def _rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _three_actions(state, session):
    session("analyst").submit(ActionRequest(tool="read_document", resource_id="doc-001"))
    decision, artifact = session("analyst").submit(
        ActionRequest(tool="save_report", source_ids=["doc-001"]))
    assert decision.allowed
    session("analyst").submit(ActionRequest(
        tool="deliver_inbox", resource_id=artifact, recipient="manager@corp.example"))
    session("intern").submit(ActionRequest(tool="read_document", resource_id="doc-003"))


def test_exports_the_known_actions_with_the_documented_columns(tmp_path, state, session):
    _three_actions(state, session)
    rows = export.export_audit(state, tmp_path / "out")
    assert len(rows) == 4, "three allowed actions and one blocked read"

    written = _rows(tmp_path / "out" / "audit.csv")
    assert list(written[0]) == list(export.AUDIT_COLUMNS)
    assert len(written) == len(rows) == 4
    assert json.loads((tmp_path / "out" / "audit.json").read_text(encoding="utf-8")) == rows

    # list_audit orders newest first, so the CSV does too: the intern's refused read is row 0.
    tools = [row["tool"] for row in written]
    assert tools == ["read_document", "deliver_inbox", "save_report", "read_document"]
    assert written[0]["actor"] == "intern"
    assert written[0]["allowed"] == "0" and written[0]["rule_id"] == "RULE-READ-CLEARANCE"


def test_outbox_records_who_received_what(tmp_path, state, session):
    _three_actions(state, session)
    export.export_outbox(state, tmp_path / "out")
    rows = _rows(tmp_path / "out" / "outbox.csv")
    assert len(rows) == 1
    assert rows[0]["recipient"] == "manager@corp.example"
    assert rows[0]["classification"] == "CONFIDENTIAL"
    assert "artifact_id" in rows[0]


def test_a_key_in_a_justification_is_redacted_and_counted(tmp_path, state):
    state.record_audit(
        actor="security-officer", origin="human", tool="declassify", resource="report-x",
        recipient=None, allowed=False, rule_id="RULE-DECLASSIFY-ROLE",
        reason=(f"Blocked: {SECRETS['openai']} was found while checking "
                f"{SECRETS['github']} and Bearer {SECRETS['bearer']}"),
        label=None, justification=(f"copy of {SECRETS['hex']} kept at {POLICY_FINGERPRINT}"),
        policy_hash=POLICY_FINGERPRINT)

    summary = _pack(state, tmp_path / "out")
    written = (tmp_path / "out" / "audit.csv").read_text(encoding="utf-8")

    assert "[REDACTED]" in written
    for name, secret in SECRETS.items():
        assert secret not in written, f"{name} secret survived the export"
    assert "eyJhbGciOiJIUzI1NiJ9" not in written, "a bearer token's body survived"
    assert summary["redactions"] == 4, "one replacement per secret, counted"
    assert POLICY_FINGERPRINT in written, "a rulebook fingerprint is not a secret"


def test_the_summary_counts_describe_the_files_beside_it(tmp_path, state, session):
    _three_actions(state, session)
    state.record_audit(actor="operator", origin="human", tool="reload_policy", resource=None,
                       recipient=None, allowed=True, rule_id="POLICY-RELOAD",
                       reason=f"Adopted {SECRETS['openai']}", label=None,
                       policy_hash=POLICY_FINGERPRINT)
    summary = _pack(state, tmp_path / "out")

    audit = _rows(tmp_path / "out" / "audit.csv")
    outbox = _rows(tmp_path / "out" / "outbox.csv")
    assert summary["decisions"] == len(audit) == 5
    assert summary["allowed"] + summary["blocked"] == summary["decisions"]
    assert summary["allowed"] == 4 and summary["blocked"] == 1
    assert summary["messages_delivered"] == len(outbox) == 1
    assert summary["distinct_actors"] == len({row["actor"] for row in audit}) == 3
    assert summary["distinct_rules"] == len({row["rule_id"] for row in audit})
    assert summary["redactions"] == 1
    assert sum(summary["artifacts_by_classification"].values()) == summary["artifacts"] == 1
    assert summary["artifacts_by_classification"] == {"CONFIDENTIAL": 1}
    assert summary["files"] == ["audit.csv", "audit.json", "outbox.csv", "summary.json"]
    assert len(summary["fingerprint"]) == 16


def test_the_output_directory_is_created(tmp_path, state):
    target = tmp_path / "deep" / "nested" / "exports"
    assert not target.exists()
    export.export_audit(state, target)
    assert (target / "audit.csv").exists() and (target / "audit.json").exists()


def test_the_cli_writes_four_files_and_prints_one_line(tmp_path, state, session, capsys):
    _three_actions(state, session)
    target = tmp_path / "exports"
    code = export.main(["export", state.path, str(target)])
    captured = capsys.readouterr()
    assert code == 0
    assert sorted(path.name for path in target.iterdir()) == [
        "audit.csv", "audit.json", "outbox.csv", "summary.json"]
    assert len([line for line in captured.out.splitlines() if line.strip()]) == 1
    assert "4 decisions" in captured.out and "redaction(s)" in captured.out


def test_the_cli_refuses_a_missing_database(tmp_path, capsys):
    code = export.main(["export", str(tmp_path / "absent.sqlite"), str(tmp_path / "out")])
    assert code == 2
    assert "no database" in capsys.readouterr().err


def test_redaction_leaves_ordinary_text_alone():
    clean, hits = export.redact("Blocked: source 'doc-004' is above what the analyst may summarise")
    assert hits == 0 and clean.startswith("Blocked: source 'doc-004'")


@pytest.mark.parametrize("secret", list(SECRETS.values()))
def test_each_secret_shape_is_redacted_on_its_own(secret):
    cleaned, hits = export.redact(f"before {secret} after")
    assert hits == 1
    assert cleaned == "before [REDACTED] after"
