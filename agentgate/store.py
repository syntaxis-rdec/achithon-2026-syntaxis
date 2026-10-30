"""SQLite state: documents, derived artifacts, workflows, audit trail, mock inbox.

Integrity rule: a document's classification is recorded on first load. If the file
changes underneath us (different content or different classification), the document
is marked tampered, kept at its original label, and every action on it is denied.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import Artifact, Document, SecurityLabel

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, classification TEXT NOT NULL,
  owner TEXT NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL,
  integrity TEXT NOT NULL DEFAULT 'ok');
CREATE TABLE IF NOT EXISTS artifacts(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, classification TEXT NOT NULL,
  provenance TEXT NOT NULL, tags TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL,
  origin TEXT NOT NULL DEFAULT 'human', tool TEXT NOT NULL, resource TEXT,
  recipient TEXT, allowed INTEGER NOT NULL, rule_id TEXT NOT NULL,
  reason TEXT NOT NULL, label TEXT, policy_hash TEXT, workflow_id TEXT,
  step_index INTEGER);
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT, artifact_id TEXT NOT NULL,
  recipient TEXT NOT NULL, ts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workflows(
  id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL,
  updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workflow_steps(
  workflow_id TEXT NOT NULL, idx INTEGER NOT NULL, status TEXT NOT NULL,
  request TEXT NOT NULL, reason TEXT DEFAULT '', PRIMARY KEY(workflow_id, idx));
CREATE TABLE IF NOT EXISTS session_reads(
  session_id TEXT NOT NULL, doc_id TEXT NOT NULL, ts TEXT NOT NULL,
  PRIMARY KEY(session_id, doc_id));
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
        digest = hashlib.sha256((doc.classification + "\n" + doc.body).encode()).hexdigest()
        self.conn.execute(
            "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?,'ok')",
            (doc.id, doc.title, doc.classification, doc.owner, doc.body, digest),
        )
        self.conn.commit()

    def get_document(self, doc_id: str) -> Document | None:
        row = self.conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if row is None:
            return None
        return Document(id=row["id"], title=row["title"], classification=row["classification"],
                        owner=row["owner"], body=row["body"])

    def document_state(self, doc_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return dict(row) if row else None

    def list_documents(self) -> list[Document]:
        rows = self.conn.execute("SELECT * FROM documents ORDER BY id").fetchall()
        return [Document(id=r["id"], title=r["title"], classification=r["classification"],
                         owner=r["owner"], body=r["body"]) for r in rows]

    def load_documents_from_dir(self, directory: str | Path) -> int:
        """Seed documents once. Later changes to a file are treated as tampering."""
        count = 0
        for file in sorted(Path(directory).glob("*.md")):
            meta, body = _parse_front_matter(file.read_text(encoding="utf-8"))
            doc_id = meta.get("id", file.stem)
            classification = meta.get("classification", "INTERNAL")
            body = body.strip()
            digest = hashlib.sha256((classification + "\n" + body).encode()).hexdigest()
            existing = self.document_state(doc_id)
            if existing is None:
                self.conn.execute(
                    "INSERT INTO documents VALUES (?,?,?,?,?,?,'ok')",
                    (doc_id, meta.get("title", doc_id), classification,
                     meta.get("owner", "unknown"), body, digest),
                )
            elif existing["sha256"] != digest:
                self.conn.execute("UPDATE documents SET integrity='tampered' WHERE id=?", (doc_id,))
            self.conn.commit()
            count += 1
        return count

    def is_tampered(self, doc_id: str) -> bool:
        row = self.document_state(doc_id)
        return bool(row and row["integrity"] == "tampered")

    # -- read taint --------------------------------------------------------
    def record_read(self, session_id: str, doc_id: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO session_reads VALUES (?,?,?)",
                          (session_id, doc_id, now()))
        self.conn.commit()

    def reads_for(self, session_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT doc_id FROM session_reads WHERE session_id=? ORDER BY doc_id",
            (session_id,)).fetchall()
        return [r["doc_id"] for r in rows]

    # -- artifacts ---------------------------------------------------------
    def add_artifact(self, artifact: Artifact) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?,?,?)",
            (artifact.id, artifact.title, artifact.label.classification,
             json.dumps(artifact.label.provenance), json.dumps(artifact.label.tags), artifact.body))
        self.conn.commit()

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        row = self.conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        if row is None:
            return None
        return Artifact(id=row["id"], title=row["title"],
                        label=SecurityLabel(classification=row["classification"],
                                            provenance=json.loads(row["provenance"]),
                                            tags=json.loads(row["tags"])),
                        body=row["body"])

    def new_artifact_id(self) -> str:
        return "report-" + uuid.uuid4().hex[:6]

    def list_artifacts(self) -> list[Artifact]:
        rows = self.conn.execute("SELECT * FROM artifacts ORDER BY rowid DESC").fetchall()
        return [Artifact(id=r["id"], title=r["title"],
                         label=SecurityLabel(classification=r["classification"],
                                             provenance=json.loads(r["provenance"]),
                                             tags=json.loads(r["tags"])),
                         body=r["body"]) for r in rows]

    # -- audit -------------------------------------------------------------
    def record_audit(self, *, actor: str, origin: str, tool: str, resource: str | None,
                     recipient: str | None, allowed: bool, rule_id: str, reason: str,
                     label: SecurityLabel | None, policy_hash: str = "",
                     workflow_id: str | None = None, step_index: int | None = None) -> None:
        self.conn.execute(
            "INSERT INTO audit(ts,actor,origin,tool,resource,recipient,allowed,rule_id,reason,"
            "label,policy_hash,workflow_id,step_index) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now(), actor, origin, tool, resource, recipient, int(allowed), rule_id, reason,
             json.dumps(label.model_dump()) if label else None, policy_hash,
             workflow_id, step_index))
        self.conn.commit()

    def list_audit(self, limit: int = 200) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # -- mock inbox --------------------------------------------------------
    def deliver(self, artifact_id: str, recipient: str) -> None:
        self.conn.execute("INSERT INTO outbox(artifact_id,recipient,ts) VALUES (?,?,?)",
                          (artifact_id, recipient, now()))
        self.conn.commit()

    def list_outbox(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM outbox ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    # -- workflows ---------------------------------------------------------
    def save_workflow(self, workflow_id: str, status: str, payload: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO workflows VALUES (?,?,?,?)",
                          (workflow_id, status, json.dumps(payload), now()))
        self.conn.commit()

    def get_workflow(self, workflow_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "status": row["status"],
                "payload": json.loads(row["payload"]), "updated_at": row["updated_at"]}

    def list_workflows(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
        return [{"id": r["id"], "status": r["status"], "payload": json.loads(r["payload"]),
                 "updated_at": r["updated_at"]} for r in rows]

    def add_steps(self, workflow_id: str, requests: list[dict]) -> None:
        for idx, request in enumerate(requests):
            self.conn.execute(
                "INSERT OR REPLACE INTO workflow_steps VALUES (?,?,?,?,?)",
                (workflow_id, idx, "pending", json.dumps(request), ""))
        self.conn.commit()

    def steps_for(self, workflow_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM workflow_steps WHERE workflow_id=? ORDER BY idx", (workflow_id,)).fetchall()
        return [{"workflow_id": r["workflow_id"], "idx": r["idx"], "status": r["status"],
                 "request": json.loads(r["request"]), "reason": r["reason"]} for r in rows]

    def set_step(self, workflow_id: str, idx: int, status: str, reason: str = "") -> None:
        self.conn.execute("UPDATE workflow_steps SET status=?, reason=? WHERE workflow_id=? AND idx=?",
                          (status, reason, workflow_id, idx))
        self.conn.commit()

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
