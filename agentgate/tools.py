"""The three protected tools.

They refuse to run unless called with the gateway's capability object, so a stray
import cannot reach a document, a report, or the inbox. `EXECUTIONS` grows only
inside a tool body, which makes "blocked actions never executed" checkable.
"""

from __future__ import annotations

from . import labels
from .models import Artifact, Document, SecurityLabel

_GATE = object()
EXECUTIONS: list[str] = []


def reset_executions() -> None:
    EXECUTIONS.clear()


def _require_gate(gate) -> None:
    if gate is not _GATE:
        raise PermissionError("tools are only callable through the gateway")


def _excerpt(text: str, limit: int = 120) -> str:
    """First non-empty line, or a marker. An empty document must not crash after an ALLOW."""
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:limit]
    return "(no content)"


def read_document(actor_id: str, doc_id: str, state, gate=None) -> str:
    _require_gate(gate)
    EXECUTIONS.append(f"read_document:{doc_id}")
    doc = state.get_document(doc_id)
    if doc is None:
        raise RuntimeError(f"document {doc_id} vanished")
    return doc.body


def save_report(actor_id: str, source_doc_ids: list[str], title: str | None, state,
                gate=None) -> str:
    _require_gate(gate)
    EXECUTIONS.append(f"save_report:{','.join(source_doc_ids)}")
    docs: list[Document] = []
    for doc_id in source_doc_ids:
        doc = state.get_document(doc_id)
        if doc is not None:
            docs.append(doc)
    derived = labels.combine([
        SecurityLabel(classification=d.classification, provenance=[d.id], tags=[f"owner:{d.owner}"])
        for d in docs
    ])
    # The title is derived, never free text from the proposer: a title is a content channel.
    derived_title = "Summary of " + ", ".join(d.id for d in docs)
    summary = "\n".join(f"- {d.title} ({d.classification}): {_excerpt(d.body)}" for d in docs)
    body = (
        f"{summary}\n\nProvenance: {', '.join(derived.provenance)}\n"
        f"Classification inherited from the most sensitive source: {derived.classification}"
    )
    artifact_id = state.new_artifact_id()
    state.add_artifact(Artifact(id=artifact_id, title=derived_title, label=derived, body=body))
    return artifact_id


def deliver_inbox(actor_id: str, artifact_id: str, recipient: str, state, gate=None,
                  effect_key: str = "") -> str:
    _require_gate(gate)
    EXECUTIONS.append(f"deliver_inbox:{artifact_id}->{recipient}")
    artifact = state.get_artifact(artifact_id)
    state.deliver(artifact_id, recipient,
                  artifact.label.classification if artifact else "", effect_key)
    return f"Message containing {artifact_id} placed in the mock inbox for {recipient}"
