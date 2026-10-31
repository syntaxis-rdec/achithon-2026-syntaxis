"""Tests for agentgate.export (Audit Export and Submission Packaging)."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agentgate.export import Redactor, export_all, export_audit, export_outbox, export_summary, main
from agentgate.models import Artifact, SecurityLabel
from agentgate.store import Store


@pytest.fixture
def populated_store(tmp_path: Path) -> Store:
    db_path = tmp_path / "test_store.sqlite"
    store = Store(db_path)

    # 1. Allowed audit row
    store.record_audit(
        actor="analyst",
        origin="human",
        tool="read_document",
        resource="doc-001",
        recipient=None,
        allowed=True,
        rule_id="READ-ANALYST",
        reason="Analyst may read internal or confidential",
        label=SecurityLabel(classification="CONFIDENTIAL", provenance=["doc-001"]),
        justification="Legitimate quarterly analysis sk-proj-12345secretKeyForTest",
    )

    # 2. Blocked audit row with ghp_ token
    store.record_audit(
        actor="agent",
        origin="agent",
        tool="deliver_message",
        resource="art-001",
        recipient="outside@vendor.example",
        allowed=False,
        rule_id="RULE-RECIPIENT-NOT-PERMITTED",
        reason="Recipient not allowed",
        label=SecurityLabel(classification="CONFIDENTIAL", provenance=["doc-001"]),
        justification="Agent sync attempt ghp_ABCDEF1234567890abcdef123456",
    )

    # 3. Third audit row with Bearer token
    store.record_audit(
        actor="officer",
        origin="human",
        tool="declassify_report",
        resource="art-002",
        recipient=None,
        allowed=True,
        rule_id="DECLASSIFY-OFFICER",
        reason="Security officer may declassify",
        label=SecurityLabel(classification="PUBLIC", provenance=["doc-001"]),
        justification="Public release auth Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
    )

    # 4. Outbox rows
    store.deliver(artifact_id="art-001", recipient="team@corp.example", classification="INTERNAL")
    store.deliver(artifact_id="art-002", recipient="board@corp.example", classification="CONFIDENTIAL")

    # 5. Artifacts
    store.add_artifact(Artifact(
        id="art-001",
        title="Report 1",
        label=SecurityLabel(classification="INTERNAL", provenance=["doc-001"]),
        body="Internal contents",
    ))
    store.add_artifact(Artifact(
        id="art-002",
        title="Report 2",
        label=SecurityLabel(classification="CONFIDENTIAL", provenance=["doc-002"]),
        body="Confidential contents",
    ))

    return store


def test_redactor_catches_all_four_patterns() -> None:
    redactor = Redactor()
    text = (
        "Key: sk-ant-api03-abcdef123456_XYZ, "
        "GH: ghp_1234567890abcdef1234567890abcdef, "
        "Auth: Bearer secret-auth-token-123, "
        "PrivateHex: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    )
    cleaned = redactor.redact_text(text)
    assert "sk-" not in cleaned
    assert "ghp_" not in cleaned
    assert "secret-auth-token-123" not in cleaned
    assert "0123456789abcdef0123456789abcdef" not in cleaned
    assert cleaned.count("[REDACTED]") == 4
    assert redactor.count == 4


def test_export_creates_directory_if_missing(populated_store: Store, tmp_path: Path) -> None:
    out_dir = tmp_path / "deep" / "nested" / "exports"
    assert not out_dir.exists()

    csv_path, json_path = export_audit(populated_store, out_dir)
    assert out_dir.exists()
    assert csv_path.exists()
    assert json_path.exists()


def test_export_audit_content_and_redaction(populated_store: Store, tmp_path: Path) -> None:
    out_dir = tmp_path / "audit_out"
    redactor = Redactor()
    csv_path, json_path = export_audit(populated_store, out_dir, redactor=redactor)

    # Check CSV
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == 3
    assert reader[0]["actor"] == "analyst"
    assert reader[0]["rule_id"] == "READ-ANALYST"
    assert "sk-" not in reader[0]["justification"]
    assert "[REDACTED]" in reader[0]["justification"]

    assert reader[1]["actor"] == "agent"
    assert "ghp_" not in reader[1]["justification"]
    assert "[REDACTED]" in reader[1]["justification"]

    # Check JSON
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 3
    assert data[2]["actor"] == "officer"
    assert "Bearer" not in data[2]["justification"] or "[REDACTED]" in data[2]["justification"]
    assert "eyJhbGci" not in data[2]["justification"]


def test_export_outbox(populated_store: Store, tmp_path: Path) -> None:
    out_dir = tmp_path / "outbox_out"
    csv_path = export_outbox(populated_store, out_dir)

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == 2
    assert reader[0]["recipient"] == "team@corp.example"
    assert reader[1]["recipient"] == "board@corp.example"


def test_export_summary_counts(populated_store: Store, tmp_path: Path) -> None:
    out_dir = tmp_path / "summary_out"
    redactor = Redactor()
    export_audit(populated_store, out_dir, redactor=redactor)
    export_outbox(populated_store, out_dir, redactor=redactor)
    summary_path = export_summary(populated_store, out_dir, redactor=redactor)

    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    assert summary["decisions"] == 3
    assert summary["allowed"] == 2
    assert summary["blocked"] == 1
    assert summary["distinct_actors"] == 3  # analyst, agent, officer
    assert summary["distinct_rules"] == 3   # READ-ANALYST, RULE-RECIPIENT-NOT-PERMITTED, DECLASSIFY-OFFICER
    assert summary["messages_delivered"] == 2
    assert summary["artifacts_by_classification"] == {"INTERNAL": 1, "CONFIDENTIAL": 1}
    assert summary["redactions"] >= 3


def test_export_all_convenience(populated_store: Store, tmp_path: Path) -> None:
    out_dir = tmp_path / "all_out"
    results = export_all(populated_store, out_dir)

    assert results["audit_csv"].exists()
    assert results["audit_json"].exists()
    assert results["outbox_csv"].exists()
    assert results["summary_json"].exists()
    assert results["summary"]["decisions"] == 3


def test_cli_execution(populated_store: Store, tmp_path: Path) -> None:
    out_dir = tmp_path / "cli_out"
    db_path = populated_store.path

    # Run module via subprocess
    cmd = [sys.executable, "-m", "agentgate.export", str(db_path), str(out_dir)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "Exported 3 decisions (2 allowed, 1 blocked)" in res.stdout
    assert "2 outbox messages" in res.stdout
    assert (out_dir / "audit.csv").exists()
    assert (out_dir / "summary.json").exists()


def test_redactor_catches_a_bare_jwt(tmp_path: Path) -> None:
    """A token copied without "Bearer " is still a token."""
    redactor = Redactor()
    cleaned = redactor.redact_text("pasted eyJhbGciOiJIUzI1NiJ9.cGF5bG9hZA.c2lnbmF0dXJl in a note")
    assert "[REDACTED]" in cleaned
    assert "eyJhbGciOiJIUzI1NiJ9" not in cleaned
    assert redactor.count == 1


def test_the_merkle_chain_survives_the_redactor(populated_store: Store, tmp_path: Path) -> None:
    """A 64-hex chain link is the proof, not a secret: scrubbing it voids the evidence pack."""
    # list_audit is newest-first, the export is sorted ascending: compare in one order.
    store_rows = sorted(populated_store.list_audit(), key=lambda row: row.get("id", 0))
    redactor = Redactor()
    csv_path, json_path = export_audit(populated_store, tmp_path, redactor)

    exported = json.loads(json_path.read_text(encoding="utf-8"))
    for db_row, pack_row in zip(store_rows, exported):
        if db_row.get("entry_hash"):
            assert pack_row["entry_hash"] == db_row["entry_hash"], "chain link was altered"
            assert len(pack_row["entry_hash"]) == 64
        assert pack_row.get("prev_hash", "") == db_row.get("prev_hash", "")
    # The fixture plants a token in a justification, so the redactor must still be firing --
    # just not on the three columns that carry the proof.
    assert "[REDACTED]" in json_path.read_text(encoding="utf-8")
    for column in ("entry_hash", "prev_hash", "policy_hash"):
        assert all("[REDACTED]" not in str(row.get(column, "")) for row in exported), column

    planted = Redactor()
    leaked = planted.redact_row({"reason": "key " + "sk-" + "Q" * 24, "entry_hash": "0" * 64})
    assert leaked["reason"] == "key [REDACTED]"
    assert leaked["entry_hash"] == "0" * 64, "the genesis link must stay intact"
