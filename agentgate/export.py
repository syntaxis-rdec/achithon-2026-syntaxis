"""Turn a live `Store` into an evidence pack a reviewer can read without the app.

    python -m agentgate.export data/agentgate-v3.sqlite exports/

Writes `audit.csv`, `audit.json`, `outbox.csv` and `summary.json` into the directory, creating it
if needed, and prints one line. Standard library plus pandas only.

Two rules govern everything here:

* **Redaction before writing.** Every string in every exported row is scanned for a key-shaped
  secret — `sk-…`, `ghp_…`, `Bearer …`, or a run of 32+ hex characters — and the match is replaced
  with `[REDACTED]`. The number of replacements lands in `summary.json`, so a reviewer can see that
  the guard ran rather than assume it did.
* **Counts come from the rows.** `summary.json` is derived from the same rows written to the two
  audit files and the outbox file, so it cannot drift away from the files beside it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .store import Store

REDACTED = "[REDACTED]"

# Each pattern matches a whole secret, not a prefix, so a redacted value leaves nothing behind.
# The 32+ hex rule deliberately sits above the 16-character rulebook fingerprint, which is not a
# secret and is one of the things this pack exists to show.
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9._\-]{20,}"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
)

AUDIT_COLUMNS = ("ts", "actor", "origin", "tool", "resource", "recipient", "allowed", "rule_id",
                 "reason", "label", "policy_hash", "workflow_id", "step_index", "justification")
OUTBOX_COLUMNS = ("artifact_id", "recipient", "classification", "ts", "effect_key")


def redact(value):
    """Return the value with any secret-shaped run replaced, and how many runs were replaced."""
    if not isinstance(value, str):
        return value, 0
    total = 0
    for pattern in SECRET_PATTERNS:
        value, replacements = pattern.subn(REDACTED, value)
        total += replacements
    return value, total


def _redact_row(row: dict, columns: tuple[str, ...], counter: list[int]) -> dict:
    clean = {}
    for column in columns:
        clean[column], hits = redact(row.get(column))
        counter[0] += hits
    return clean


def _write_csv(path: Path, rows: list[dict], columns: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def export_audit(store: Store, directory: str | Path,
                 counter: list[int] | None = None) -> list[dict]:
    """Write `audit.csv` and `audit.json`; return the redacted rows that were written."""
    counter = counter if counter is not None else [0]
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    rows = [_redact_row(row, AUDIT_COLUMNS, counter)
            for row in store.list_audit(limit=100_000)]
    _write_csv(folder / "audit.csv", rows, AUDIT_COLUMNS)
    _write_json(folder / "audit.json", rows)
    return rows


def export_outbox(store: Store, directory: str | Path,
                  counter: list[int] | None = None) -> list[dict]:
    """Write `outbox.csv`: what actually left the gateway, and to whom."""
    counter = counter if counter is not None else [0]
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    rows = [_redact_row(row, OUTBOX_COLUMNS, counter) for row in store.list_outbox()]
    _write_csv(folder / "outbox.csv", rows, OUTBOX_COLUMNS)
    return rows


def summarise(store: Store, audit_rows: list[dict], outbox_rows: list[dict],
              redactions: int, source: str | Path | None = None) -> dict:
    """The counts a reviewer asks for first, taken from the exported rows themselves."""
    artifacts = store.list_artifacts()
    by_classification = Counter(artifact.label.classification for artifact in artifacts)
    allowed = sum(1 for row in audit_rows if row["allowed"] in (1, True, "1"))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(source) if source is not None else str(getattr(store, "path", "")),
        "decisions": len(audit_rows),
        "allowed": allowed,
        "blocked": len(audit_rows) - allowed,
        "distinct_actors": len({row["actor"] for row in audit_rows}),
        "distinct_rules": len({row["rule_id"] for row in audit_rows}),
        "messages_delivered": len(outbox_rows),
        "artifacts": len(artifacts),
        "artifacts_by_classification": dict(sorted(by_classification.items())),
        "redactions": redactions,
    }


def export_summary(store: Store, directory: str | Path, audit_rows: list[dict],
                   outbox_rows: list[dict], redactions: int,
                   source: str | Path | None = None) -> dict:
    """Write `summary.json`, including a hash over the three data files, and return it."""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    summary = summarise(store, audit_rows, outbox_rows, redactions, source)
    summary["files"] = ["audit.csv", "audit.json", "outbox.csv", "summary.json"]
    summary["fingerprint"] = _file_fingerprint(folder)
    _write_json(folder / "summary.json", summary)
    return summary


def export_pack(db_path: str | Path, directory: str | Path) -> dict:
    """The one call the CLI makes: all four files, one redaction counter, one summary."""
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"no database at {db}")
    store = Store(db)
    counter = [0]
    try:
        audit_rows = export_audit(store, directory, counter)
        outbox_rows = export_outbox(store, directory, counter)
        return export_summary(store, directory, audit_rows, outbox_rows, counter[0], source=db)
    finally:
        store.close()


def _file_fingerprint(folder: Path) -> str:
    """A hash over the exported bytes, so a reviewer can tell two packs apart."""
    digest = hashlib.sha256()
    for name in ("audit.csv", "audit.json", "outbox.csv"):
        digest.update((folder / name).read_bytes())
    return digest.hexdigest()[:16]


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: python -m agentgate.export <db_path> <out_dir>", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        summary = export_pack(argv[1], argv[2])
    except FileNotFoundError as exc:
        print(f"export failed: {exc}", file=sys.stderr)
        return 2
    print(f"export: {summary['decisions']} decisions "
          f"({summary['allowed']} allowed, {summary['blocked']} blocked), "
          f"{summary['messages_delivered']} messages, {summary['artifacts']} artifacts, "
          f"{summary['redactions']} redaction(s) -> {Path(argv[2])} "
          f"[audit.csv, audit.json, outbox.csv, summary.json]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
