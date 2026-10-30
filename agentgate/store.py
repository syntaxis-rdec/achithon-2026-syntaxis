"""SQLite state: documents, derived artifacts, workflows, audit trail, mock inbox."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import Artifact, Document, SecurityLabel

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, classification TEXT NOT NULL,
  owner TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, classification TEXT NOT NULL,
  provenance TEXT NOT NULL, tags TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL,
  tool TEXT NOT NULL, resource TEXT, recipient TEXT, allowed INTEGER NOT NULL,
  rule_id TEXT NOT NULL, reason TEXT NOT NULL, label TEXT);
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT, artifact_id TEXT NOT NULL,
  recipient TEXT NOT NULL, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workflows(
  id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL,
  updated_at TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- documents ---------------------------------------------------------
    def add_document(self, doc: Document) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)",
            (doc.id, doc.title, doc.classification, doc.owner, doc.body),
        )
        self.conn.commit()

    def get_document(self, doc_id: str) -> Document | None:
        row = self.conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if row is None:
            return None
        return Document(
            id=row["id"], title=row["title"], classification=row["classification"],
            owner=row["owner"], body=row["body"],
        )

    def list_documents(self) -> list[Document]:
        rows = self.conn.execute("SELECT * FROM documents ORDER BY id").fetchall()
        return [
            Document(id=r["id"], title=r["title"], classification=r["classification"],
                     owner=r["owner"], body=r["body"])
            for r in rows
        ]

    def load_documents_from_dir(self, directory: str | Path) -> int:
        """Seed participant-facing documents. Files use `---` front matter."""
        count = 0
        for file in sorted(Path(directory).glob("*.md")):
            meta, body = _parse_front_matter(file.read_text(encoding="utf-8"))
            doc_id = meta.get("id", file.stem)
            self.add_document(
                Document(
                    id=doc_id,
                    title=meta.get("title", doc_id),
                    classification=meta.get("classification", "INTERNAL"),
                    owner=meta.get("owner", "unknown"),
                    body=body.strip(),
                )
            )
            count += 1
        return count

    # -- artifacts ---------------------------------------------------------
    def add_artifact(self, artifact: Artifact) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?,?,?)",
            (artifact.id, artifact.title, artifact.label.classification,
             json.dumps(artifact.label.provenance), json.dumps(artifact.label.tags),
             artifact.body),
        )
        self.conn.commit()

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        row = self.conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        if row is None:
            return None
        return Artifact(
            id=row["id"], title=row["title"],
            label=SecurityLabel(
                classification=row["classification"],
                provenance=json.loads(row["provenance"]),
                tags=json.loads(row["tags"]),
            ),
            body=row["body"],
        )

    def new_artifact_id(self) -> str:
        return "report-" + uuid.uuid4().hex[:6]

    # -- audit -------------------------------------------------------------
    def record_audit(self, *, actor: str, tool: str, resource: str | None,
                     recipient: str | None, allowed: bool, rule_id: str,
                     reason: str, label: SecurityLabel | None) -> None:
        self.conn.execute(
            "INSERT INTO audit(ts,actor,tool,resource,recipient,allowed,rule_id,reason,label)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (now(), actor, tool, resource, recipient, int(allowed), rule_id, reason,
             json.dumps(label.model_dump()) if label else None),
        )
        self.conn.commit()

    def list_audit(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- mock inbox --------------------------------------------------------
    def deliver(self, artifact_id: str, recipient: str) -> None:
        self.conn.execute(
            "INSERT INTO outbox(artifact_id,recipient,ts) VALUES (?,?,?)",
            (artifact_id, recipient, now()),
        )
        self.conn.commit()

    def list_outbox(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM outbox ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    # -- workflows ---------------------------------------------------------
    def save_workflow(self, workflow_id: str, status: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO workflows VALUES (?,?,?,?)",
            (workflow_id, status, json.dumps(payload), now()),
        )
        self.conn.commit()

    def get_workflow(self, workflow_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "status": row["status"],
                "payload": json.loads(row["payload"]), "updated_at": row["updated_at"]}

    def close(self) -> None:
        self.conn.close()


def _parse_front_matter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    meta: dict[str, str] = {}
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return meta, "\n".join(lines[index + 1:])
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip().lower()] = value.strip()
    return meta, text
