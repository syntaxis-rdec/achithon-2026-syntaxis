"""Tests for Cryptographic Merkle Audit Hash Chain in AGENTGATE (PS08).

Verifies tamper-evidence, cryptographic link integrity, genesis hashing,
modification detection, deletion detection, and unhashed entry backfilling.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agentgate.audit_chain import (
    CANONICAL_FIELDS,
    GENESIS_HASH,
    compute_audit_chain,
    compute_entry_hash,
    verify_audit_chain,
)
from agentgate.gateway import Session
from agentgate.models import ActionRequest, SecurityLabel
from agentgate.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "audit_chain_test.sqlite")


def test_empty_audit_trail_is_valid(store: Store) -> None:
    """Empty audit trail must be reported as valid with 0 verified rows."""
    is_valid, error, count = verify_audit_chain(store)
    assert is_valid is True
    assert error == ""
    assert count == 0


def test_clean_chain_verification_passes(store: Store) -> None:
    """A series of recorded audit events must produce an intact, verified cryptographic hash chain."""
    store.record_audit(
        actor="analyst",
        origin="human",
        tool="read_document",
        resource="doc-001",
        recipient=None,
        allowed=True,
        rule_id="READ-ANALYST",
        reason="Analyst read clearance granted",
        label=SecurityLabel(classification="CONFIDENTIAL", provenance=["doc-001"]),
        justification="Legitimate investigation",
    )
    store.record_audit(
        actor="agent-assistant",
        origin="agent",
        tool="deliver_inbox",
        resource="art-001",
        recipient="outside@vendor.example",
        allowed=False,
        rule_id="RULE-ACTOR-CANNOT-RELEASE",
        reason="Assistant cannot release confidential documents",
        label=SecurityLabel(classification="CONFIDENTIAL", provenance=["doc-001"]),
        justification="Automated sync request",
    )
    store.record_audit(
        actor="security-officer",
        origin="human",
        tool="save_report",
        resource="doc-001,doc-002",
        recipient=None,
        allowed=True,
        rule_id="SAVE-ALLOWED",
        reason="Security officer report synthesis",
        label=SecurityLabel(classification="RESTRICTED", provenance=["doc-001", "doc-002"]),
        justification="Incident response report",
    )

    rows = store.conn.execute("SELECT * FROM audit ORDER BY id ASC").fetchall()
    assert len(rows) == 3

    # Row 1 (genesis) must reference GENESIS_HASH ("0" * 64)
    assert rows[0]["prev_hash"] == GENESIS_HASH
    assert len(rows[0]["entry_hash"]) == 64

    # Row 2 must chain to Row 1
    assert rows[1]["prev_hash"] == rows[0]["entry_hash"]
    assert len(rows[1]["entry_hash"]) == 64

    # Row 3 must chain to Row 2
    assert rows[2]["prev_hash"] == rows[1]["entry_hash"]
    assert len(rows[2]["entry_hash"]) == 64

    is_valid, error, count = verify_audit_chain(store)
    assert is_valid is True
    assert error == ""
    assert count == 3

    # Also test convenience method on Store
    st_valid, st_err, st_count = store.verify_audit_chain()
    assert st_valid is True
    assert st_err == ""
    assert st_count == 3


def test_modifying_audited_field_in_sqlite_causes_verification_failure(store: Store) -> None:
    """Tampering with any audited field in SQLite must cause cryptographic verification failure."""
    for i in range(1, 4):
        store.record_audit(
            actor=f"user-{i}",
            origin="human",
            tool="read_document",
            resource=f"doc-00{i}",
            recipient=None,
            allowed=True,
            rule_id="READ-OK",
            reason=f"Reason {i}",
            label=None,
        )

    # Initial chain is clean
    assert verify_audit_chain(store)[0] is True

    # Tamper with row 2's actor field
    store.conn.execute("UPDATE audit SET actor = 'adversary_attacker' WHERE id = 2")
    store.conn.commit()

    is_valid, error, count = verify_audit_chain(store)
    assert is_valid is False
    assert "Tampering detected at row id=2" in error
    assert count == 1  # Row 1 was verified before the tampered row failed

    # Restore actor, tamper with allowed flag
    store.conn.execute("UPDATE audit SET actor = 'user-2', allowed = 0 WHERE id = 2")
    store.conn.commit()

    is_valid, error, count = verify_audit_chain(store)
    assert is_valid is False
    assert "Tampering detected at row id=2" in error
    assert count == 1

    # Restore allowed flag, tamper with reason
    store.conn.execute("UPDATE audit SET allowed = 1, reason = 'Forged explanation' WHERE id = 2")
    store.conn.commit()

    is_valid, error, count = verify_audit_chain(store)
    assert is_valid is False
    assert "Tampering detected at row id=2" in error
    assert count == 1


def test_deleting_audit_row_breaks_the_chain(store: Store) -> None:
    """Deleting an audit row in SQLite must break the cryptographic hash link and be detected."""
    for i in range(1, 4):
        store.record_audit(
            actor=f"agent-{i}",
            origin="agent",
            tool="read_document",
            resource=f"doc-00{i}",
            recipient=None,
            allowed=True,
            rule_id="READ-OK",
            reason=f"Valid step {i}",
            label=None,
        )

    assert verify_audit_chain(store)[0] is True

    # Delete middle row (id=2)
    store.conn.execute("DELETE FROM audit WHERE id = 2")
    store.conn.commit()

    is_valid, error, count = verify_audit_chain(store)
    assert is_valid is False
    assert "Broken hash link at row id=3" in error
    assert count == 1  # Row 1 verified; Row 3 expected Row 1's hash, but had Row 2's hash


def test_deleting_genesis_row_breaks_the_chain(store: Store) -> None:
    """Deleting the genesis row leaves the next row with an invalid prev_hash link."""
    for i in range(1, 3):
        store.record_audit(
            actor=f"user-{i}",
            origin="human",
            tool="read_document",
            resource=f"doc-00{i}",
            recipient=None,
            allowed=True,
            rule_id="READ-OK",
            reason=f"Reason {i}",
            label=None,
        )

    # Delete genesis row (id=1)
    store.conn.execute("DELETE FROM audit WHERE id = 1")
    store.conn.commit()

    is_valid, error, count = verify_audit_chain(store)
    assert is_valid is False
    assert "Broken hash link at row id=2" in error
    assert count == 0


def test_compute_entry_hash_behavior() -> None:
    """compute_entry_hash produces deterministic SHA-256 hashes sensitive to all canonical fields."""
    entry = {
        "ts": "2026-10-30T17:00:00Z",
        "actor": "analyst",
        "origin": "human",
        "tool": "read_document",
        "resource": "doc-001",
        "recipient": None,
        "allowed": 1,
        "rule_id": "RULE-READ",
        "reason": "OK",
        "label": None,
        "policy_hash": "abcdef123456",
        "workflow_id": None,
        "step_index": None,
        "justification": "legit",
    }
    h1 = compute_entry_hash(GENESIS_HASH, entry)
    h2 = compute_entry_hash(GENESIS_HASH, entry)
    assert h1 == h2
    assert len(h1) == 64

    # Defaulting empty/None prev_hash to GENESIS_HASH
    h_default = compute_entry_hash("", entry)
    assert h_default == h1

    # Modifying prev_hash alters result
    h_diff_prev = compute_entry_hash("1" * 64, entry)
    assert h_diff_prev != h1

    # Modifying any canonical field alters result
    for field in CANONICAL_FIELDS:
        modified_entry = dict(entry)
        if field == "allowed":
            modified_entry[field] = 0
        elif field == "step_index":
            modified_entry[field] = 42
        else:
            modified_entry[field] = f"modified_{field}"
        h_mod = compute_entry_hash(GENESIS_HASH, modified_entry)
        assert h_mod != h1, f"Hash did not change when altering {field}"


def test_unhashed_audit_entries_compute_or_verify_cleanly(tmp_path: Path) -> None:
    """Legacy or unhashed audit rows can be backfilled and verified cleanly."""
    db_path = tmp_path / "legacy_audit.sqlite"
    # Create raw table without hash columns or populate without hashes
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL,
            origin TEXT NOT NULL DEFAULT 'human', tool TEXT NOT NULL, resource TEXT,
            recipient TEXT, allowed INTEGER NOT NULL, rule_id TEXT NOT NULL,
            reason TEXT NOT NULL, label TEXT, policy_hash TEXT, workflow_id TEXT,
            step_index INTEGER, justification TEXT DEFAULT '',
            prev_hash TEXT DEFAULT '', entry_hash TEXT DEFAULT ''
        );
    """)
    conn.execute("""
        INSERT INTO audit(ts, actor, origin, tool, resource, recipient, allowed, rule_id, reason)
        VALUES ('2026-10-30T10:00:00Z', 'legacy_user', 'human', 'read_doc', 'doc-1', NULL, 1, 'RULE-1', 'Legacy test');
    """)
    conn.execute("""
        INSERT INTO audit(ts, actor, origin, tool, resource, recipient, allowed, rule_id, reason)
        VALUES ('2026-10-30T10:01:00Z', 'legacy_user', 'human', 'read_doc', 'doc-2', NULL, 1, 'RULE-1', 'Legacy test 2');
    """)
    conn.commit()
    conn.close()

    store = Store(db_path)

    # Initial verification without auto_compute reports unsealed entries cleanly (no exception)
    is_valid, error, count = verify_audit_chain(store)
    assert is_valid is False
    assert "unsealed or missing" in error
    assert count == 0

    # Backfill / compute hashes
    updated = compute_audit_chain(store)
    assert updated == 2

    # Verification now passes
    is_valid, error, count = verify_audit_chain(store)
    assert is_valid is True
    assert error == ""
    assert count == 2


def test_verify_with_auto_compute_flag(tmp_path: Path) -> None:
    """verify_audit_chain with auto_compute=True seals unhashed entries and verifies in one step."""
    store = Store(tmp_path / "auto_compute.sqlite")
    # Insert unhashed row directly
    store.conn.execute("""
        INSERT INTO audit(ts, actor, origin, tool, resource, recipient, allowed, rule_id, reason, prev_hash, entry_hash)
        VALUES ('2026-10-30T10:00:00Z', 'batch_actor', 'agent', 'tool_call', 'res-1', NULL, 1, 'RULE-A', 'Unsealed', '', '');
    """)
    store.conn.commit()

    is_valid, error, count = verify_audit_chain(store, auto_compute=True)
    assert is_valid is True
    assert error == ""
    assert count == 1


def test_tampering_with_prev_hash_or_entry_hash_fails_verification(store: Store) -> None:
    """Direct tampering with the stored hash columns in SQLite is caught."""
    store.record_audit(
        actor="user-1", origin="human", tool="read_document", resource="doc-1",
        recipient=None, allowed=True, rule_id="OK", reason="Pass", label=None,
    )
    store.record_audit(
        actor="user-2", origin="human", tool="read_document", resource="doc-2",
        recipient=None, allowed=True, rule_id="OK", reason="Pass", label=None,
    )

    # Tamper with row 2's prev_hash
    store.conn.execute("UPDATE audit SET prev_hash = ? WHERE id = 2", ("f" * 64,))
    store.conn.commit()

    is_valid, error, count = verify_audit_chain(store)
    assert is_valid is False
    assert "Broken hash link at row id=2" in error

    # Re-seal properly, then tamper with row 1's entry_hash
    compute_audit_chain(store, force=True)
    assert verify_audit_chain(store)[0] is True

    store.conn.execute("UPDATE audit SET entry_hash = ? WHERE id = 1", ("e" * 64,))
    store.conn.commit()

    is_valid, error, count = verify_audit_chain(store)
    assert is_valid is False
    assert "Tampering detected at row id=1" in error


def test_gateway_session_produces_valid_chain(store: Store, policies) -> None:
    """Gateway Session interactions automatically generate a valid cryptographic audit chain."""
    session = Session(store, policies, "analyst")
    session.submit(ActionRequest(tool="read_document", resource_id="doc-002"))
    session.submit(ActionRequest(tool="save_report", source_ids=["doc-002"]))

    agent_session = Session(store, policies, "agent-assistant", "agent")
    agent_session.submit(ActionRequest(tool="deliver_inbox", resource_id="report-xxx", recipient="ext@leak.example"))

    is_valid, error, count = verify_audit_chain(store)
    assert is_valid is True
    assert error == ""
    assert count == 3
