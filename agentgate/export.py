"""Audit export and submission packaging for AGENTGATE (PS08).

Exports the SQLite audit trail, outbox deliveries, and summary statistics to
CSV and JSON with mandatory secret redaction (sk-, ghp-, Bearer, 32+ hex).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

from .store import Store

# Secrets patterns to redact:
# 1. sk-[A-Za-z0-9_-]+ (OpenAI / third party API keys)
# 2. ghp_[A-Za-z0-9]+ (GitHub Personal Access Tokens)
# 3. Bearer [A-Za-z0-9._~+/-]+=* (HTTP Authorization bearer tokens)
# 4. \b[0-9a-fA-F]{32,}\b (32+ character hex strings like private keys/tokens)
REDACTION_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]+"),
    re.compile(r"ghp_[A-Za-z0-9]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=\-]+", re.IGNORECASE),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
    # A JWT pasted without its "Bearer " prefix, which is what lands in a justification field.
    re.compile(r"\beyJ[A-Za-z0-9._\-]{20,}"),
]

REPLACEMENT = "[REDACTED]"


class Redactor:
    def __init__(self) -> None:
        self.count = 0

    def redact_text(self, text: str) -> str:
        if not isinstance(text, str) or not text:
            return text
        result = text
        for pattern in REDACTION_PATTERNS:
            matches = list(pattern.finditer(result))
            if matches:
                self.count += len(matches)
                result = pattern.sub(REPLACEMENT, result)
        return result

    def redact_row(self, row: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, str):
                cleaned[k] = self.redact_text(v)
            else:
                cleaned[k] = v
        return cleaned


def export_audit(store: Store, directory: str | Path, redactor: Redactor | None = None) -> tuple[Path, Path]:
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    if redactor is None:
        redactor = Redactor()

    rows = store.list_audit(limit=10_000_000)
    rows = sorted(rows, key=lambda r: r.get("id", 0))
    cleaned_rows = [redactor.redact_row(r) for r in rows]

    csv_path = out_dir / "audit.csv"
    json_path = out_dir / "audit.json"

    if cleaned_rows:
        fieldnames = list(cleaned_rows[0].keys())
    else:
        fieldnames = [
            "id", "ts", "actor", "origin", "tool", "resource", "recipient",
            "allowed", "rule_id", "reason", "label", "policy_hash",
            "workflow_id", "step_index", "justification"
        ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cleaned_rows)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(cleaned_rows, f, indent=2)

    return csv_path, json_path


def export_outbox(store: Store, directory: str | Path, redactor: Redactor | None = None) -> Path:
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    if redactor is None:
        redactor = Redactor()

    rows = store.list_outbox()
    rows = sorted(rows, key=lambda r: r.get("id", 0))
    cleaned_rows = [redactor.redact_row(r) for r in rows]

    csv_path = out_dir / "outbox.csv"
    if cleaned_rows:
        fieldnames = list(cleaned_rows[0].keys())
    else:
        fieldnames = ["id", "artifact_id", "recipient", "classification", "ts", "effect_key"]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cleaned_rows)

    return csv_path


def export_summary(store: Store, directory: str | Path, redactor: Redactor | None = None) -> Path:
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)

    audit_rows = store.list_audit(limit=10_000_000)
    outbox_rows = store.list_outbox()
    artifacts = store.list_artifacts()

    decisions = len(audit_rows)
    allowed = sum(1 for r in audit_rows if r.get("allowed"))
    blocked = decisions - allowed
    distinct_actors = len({r.get("actor") for r in audit_rows if r.get("actor")})
    distinct_rules = len({r.get("rule_id") for r in audit_rows if r.get("rule_id")})
    messages_delivered = len(outbox_rows)

    artifacts_by_classification: dict[str, int] = {}
    for art in artifacts:
        cls_name = art.label.classification if hasattr(art, "label") else "UNKNOWN"
        artifacts_by_classification[cls_name] = artifacts_by_classification.get(cls_name, 0) + 1

    summary = {
        "decisions": decisions,
        "allowed": allowed,
        "blocked": blocked,
        "distinct_actors": distinct_actors,
        "distinct_rules": distinct_rules,
        "messages_delivered": messages_delivered,
        "artifacts_by_classification": artifacts_by_classification,
        "redactions": redactor.count if redactor else 0,
    }

    json_path = out_dir / "summary.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return json_path


def export_all(store: Store, directory: str | Path) -> dict[str, Any]:
    redactor = Redactor()
    audit_csv, audit_json = export_audit(store, directory, redactor=redactor)
    outbox_csv = export_outbox(store, directory, redactor=redactor)
    summary_json = export_summary(store, directory, redactor=redactor)
    with open(summary_json, "r", encoding="utf-8") as f:
        summary_data = json.load(f)
    return {
        "audit_csv": audit_csv,
        "audit_json": audit_json,
        "outbox_csv": outbox_csv,
        "summary_json": summary_json,
        "summary": summary_data,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export AGENTGATE audit trail and summary.")
    parser.add_argument("db_path", help="Path to SQLite database file")
    parser.add_argument("out_dir", help="Output directory for exported files")
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Error: Database file not found: {db_path}", file=sys.stderr)
        return 1

    store = Store(db_path)
    try:
        results = export_all(store, args.out_dir)
        s = results["summary"]
        print(
            f"Exported {s['decisions']} decisions ({s['allowed']} allowed, {s['blocked']} blocked), "
            f"{s['messages_delivered']} outbox messages, {s['redactions']} redactions to {args.out_dir}"
        )
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())

