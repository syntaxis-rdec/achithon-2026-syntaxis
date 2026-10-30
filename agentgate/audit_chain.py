"""Cryptographic Merkle Audit Hash Chain for AGENTGATE (PS08).

Implements tamper-evident cryptographic hash chaining for audit logs:
- Each audit entry cryptographically seals the previous entry's hash (SHA-256).
- Genesis row (first audit event) links to a 64-char zero hash ("0" * 64).
- Canonical fields ensure deterministic serialization across SQLite data types.
- Verification detects any retroactive record tampering, modification, or row deletion.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .store import Store

GENESIS_HASH: str = "0" * 64

# Canonical fields in deterministic evaluation order
CANONICAL_FIELDS: tuple[str, ...] = (
    "ts",
    "actor",
    "origin",
    "tool",
    "resource",
    "recipient",
    "allowed",
    "rule_id",
    "reason",
    "label",
    "policy_hash",
    "workflow_id",
    "step_index",
    "justification",
)


def _normalize_canonical_field(key: str, val: Any) -> Any:
    """Normalize a canonical audit field for deterministic hashing."""
    if key == "allowed":
        return int(bool(val)) if val is not None else 0
    if key == "step_index":
        return int(val) if val is not None and val != "" else None
    if key == "label":
        if hasattr(val, "model_dump"):
            return json.dumps(val.model_dump(), sort_keys=True)
        if isinstance(val, dict):
            return json.dumps(val, sort_keys=True)
        if val is not None:
            return str(val)
        return None
    if val is None:
        return None
    if isinstance(val, (int, float, bool)):
        return val
    return str(val)


def compute_entry_hash(prev_hash: str, audit_entry: dict[str, Any]) -> str:
    """Generate SHA-256 of canonical fields + prev_hash.

    The genesis row uses "0" * 64 as prev_hash.
    """
    if not prev_hash:
        prev_hash = GENESIS_HASH

    canonical_data: dict[str, Any] = {}
    for field in CANONICAL_FIELDS:
        raw_val = audit_entry.get(field)
        canonical_data[field] = _normalize_canonical_field(field, raw_val)

    payload = json.dumps(
        {"prev_hash": prev_hash, "entry": canonical_data},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ensure_hash_columns(store: Store) -> None:
    """Ensure audit table has prev_hash and entry_hash columns."""
    cols = [r["name"] for r in store.conn.execute("PRAGMA table_info(audit)")]
    changed = False
    if "prev_hash" not in cols:
        store.conn.execute("ALTER TABLE audit ADD COLUMN prev_hash TEXT DEFAULT ''")
        changed = True
    if "entry_hash" not in cols:
        store.conn.execute("ALTER TABLE audit ADD COLUMN entry_hash TEXT DEFAULT ''")
        changed = True
    if changed:
        store.conn.commit()


def compute_audit_chain(store: Store, force: bool = False) -> int:
    """Compute and store cryptographic hashes for audit entries in chronological order.

    If force is False, only entries missing prev_hash or entry_hash are computed.
    If force is True, the entire chain is recomputed from genesis.
    Returns the count of entries updated.
    """
    _ensure_hash_columns(store)
    rows = store.conn.execute("SELECT * FROM audit ORDER BY id ASC").fetchall()
    if not rows:
        return 0

    updated_count = 0
    prev_hash = GENESIS_HASH

    for row in rows:
        row_dict = dict(row)
        stored_prev = row_dict.get("prev_hash") or ""
        stored_entry = row_dict.get("entry_hash") or ""

        needs_update = force or not stored_entry or not stored_prev
        if needs_update:
            entry_hash = compute_entry_hash(prev_hash, row_dict)
            store.conn.execute(
                "UPDATE audit SET prev_hash = ?, entry_hash = ? WHERE id = ?",
                (prev_hash, entry_hash, row_dict["id"]),
            )
            prev_hash = entry_hash
            updated_count += 1
        else:
            prev_hash = stored_entry

    if updated_count > 0:
        store.conn.commit()
    return updated_count


def verify_audit_chain(store: Store, auto_compute: bool = False) -> tuple[bool, str, int]:
    """Verify that all audit rows in chronological order (id ASC) have an intact cryptographic hash link.

    Args:
        store: SQLite Store instance to verify.
        auto_compute: If True, computes hashes for unhashed entries before verification.

    Returns:
        (is_valid, error_description, verified_count)
    """
    _ensure_hash_columns(store)
    if auto_compute:
        compute_audit_chain(store, force=False)

    rows = store.conn.execute("SELECT * FROM audit ORDER BY id ASC").fetchall()
    if not rows:
        return True, "", 0

    verified_count = 0
    expected_prev = GENESIS_HASH

    for row in rows:
        row_dict = dict(row)
        row_id = row_dict["id"]
        stored_prev = row_dict.get("prev_hash") or ""
        stored_entry = row_dict.get("entry_hash") or ""

        if not stored_entry or not stored_prev:
            return (
                False,
                f"Audit row id={row_id} has unsealed or missing cryptographic hash",
                verified_count,
            )

        if stored_prev != expected_prev:
            return (
                False,
                f"Broken hash link at row id={row_id}: prev_hash '{stored_prev}' does not match expected '{expected_prev}'",
                verified_count,
            )

        computed = compute_entry_hash(stored_prev, row_dict)
        if computed != stored_entry:
            return (
                False,
                f"Tampering detected at row id={row_id}: stored entry_hash '{stored_entry}' does not match computed '{computed}'",
                verified_count,
            )

        expected_prev = stored_entry
        verified_count += 1

    return True, "", verified_count
