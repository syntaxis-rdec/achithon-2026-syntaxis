"""Natural language into proposed tool actions, with no authority at all.

The proposer reads a sentence, resolves identifiers against local state, and builds
`ActionRequest` objects. It never evaluates policy, never calls a tool, and cannot
express a release. Every proposal must still go through
`agentgate.gateway.Session.submit`, which binds the actor and origin and consults the
deterministic policy engine. Identity written in the sentence is discarded.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from .models import ActionRequest, PolicySet

ROOT = Path(__file__).resolve().parent.parent

_EXAMPLE = ("'read doc-004', 'summarise doc-002 and doc-004', or "
            "'send report-abc123 to manager@corp.example'")

_RELEASE_REFUSAL = (
    "Refused: the proposer cannot change a security label. Release is a separate "
    "human security-officer action, not a tool, and there is no route to it from here."
)

_RELEASE_RE = re.compile(
    "|".join(
        f"(?:{pattern})" for pattern in (
            r"\bdeclassif\w*",
            r"\breclassif\w*",
            r"\bdowngrad\w*",
            r"\blower(?:ing)?\s+(?:the\s+)?(?:classification|label|sensitivity)",
            r"\breduce\s+(?:the\s+)?(?:classification|label|sensitivity)",
            r"\brelease\s+(?:the\s+)?(?:label|classification)",
            r"\b(?:make|mark|set|treat|change)\s+"
            r"(?:this|it|that|the|report|artifact|artefact|document|doc-\S+|report-\S+)"
            r"\b[^.]{0,30}\b(?:public|internal|confidential|restricted)\b",
            r"\b(?:set|change)\s+(?:the\s+)?(?:classification|label)\b",
        )
    ),
    re.IGNORECASE,
)

_NOISE = (
    r"please",
    r"kindly",
    r"(?:can|could|would|will)\s+you",
    r"(?:i\s+want|i'd\s+like|i\s+need)\s+you\s+to",
    r"ignore\s+(?:all\s+)?(?:the\s+)?(?:previous\s+|prior\s+)?(?:policy|policies|instructions)",
    r"disregard\s+(?:all\s+)?(?:the\s+)?(?:policy|policies|instructions)",
    r"forget\s+(?:all\s+)?(?:the\s+)?(?:policy|policies|instructions)",
    r"system\s+directive",
    r"new\s+instructions",
    r"system",
)

_READ = re.compile(r"^(?:read|open|view|fetch)\s+(?:the\s+)?(?:documents?\s+)?(?P<ids>.+)$",
                   re.IGNORECASE)
_SUMMARY = re.compile(
    r"^(?:summari[sz]e|summary\s+of|"
    r"(?:write|make|prepare|create)\s+(?:a\s+)?(?:report|summary)\s+(?:from|on|of|about)|"
    r"report\s+on)\s+(?P<rest>.+)$",
    re.IGNORECASE,
)
_SUMMARY_TAIL = re.compile(r"\s+(?:into|as)\s+(?:a\s+)?(?:report|summary)$", re.IGNORECASE)
_SEND = re.compile(r"^(?:send|deliver|email|forward)\s+(?P<what>.+?)\s+to\s+(?P<who>.+)$",
                   re.IGNORECASE)

_ALL_DOCUMENTS = {"everything", "all", "all documents", "all the documents", "the documents",
                  "every document", "every documents", "each document"}
_ALL_REPORTS = {"everything", "all", "all reports", "all the reports", "all saved reports",
                "all of them"}
_LATEST_REPORTS = {"report", "the report", "the saved report", "the latest report",
                   "the latest one", "the last report", "the most recent report",
                   "latest report"}
_DESCRIPTOR_STOPWORDS = {
    "report", "reports", "summary", "summaries", "file", "files", "artifact", "artefact",
    "document", "documents", "brief", "briefing", "one", "saved", "latest", "last", "most",
    "recent", "my", "our", "that", "this", "the", "a", "an", "about", "on", "of", "to",
    "for", "from",
}


class _Refused(Exception):
    """A sentence this deterministic parser will not turn into an action."""


class Proposal(BaseModel):
    """What the proposer understood. Not a decision and not a permission."""

    actions: list[ActionRequest] = Field(default_factory=list)
    backend: str = "scripted"
    refusal: str | None = None


def propose(sentence: str, *, session, state, policies: PolicySet) -> Proposal:
    """Turn one sentence into proposals for the session's actor.

    `session` supplies the identity; anything the sentence says about identity is
    ignored. The returned actions still have to pass `Session.submit`.
    """
    actor_id = _actor_id(session)
    text = " ".join(sentence.split()) if isinstance(sentence, str) else ""
    if not text:
        return _refusal("the proposer needs a sentence to interpret.")
    if _RELEASE_RE.search(text):
        return Proposal(refusal=_RELEASE_REFUSAL)
    return _scripted(text, actor_id=actor_id, state=state, policies=policies)


# -- scripted backend ------------------------------------------------------


def _scripted(text: str, *, actor_id: str, state, policies: PolicySet) -> Proposal:
    cleaned = _strip_identity(text, _actor_ids(policies))
    if not cleaned:
        return _refusal(f"nothing was left to act on after removing identity wording. Try {_EXAMPLE}.")
    try:
        actions = _parse(cleaned, state=state, policies=policies)
    except _Refused as refused:
        return _refusal(str(refused))
    return Proposal(actions=_stamp(actions, actor_id), backend="scripted")


def _parse(clause: str, *, state, policies: PolicySet) -> list[ActionRequest]:
    match = _READ.match(clause)
    if match:
        return [ActionRequest(tool="read_document", resource_id=doc_id)
                for doc_id in _document_ids(match.group("ids"), state)]

    match = _SUMMARY.match(clause)
    if match:
        sources = _SUMMARY_TAIL.sub("", match.group("rest"))
        return [ActionRequest(tool="save_report", source_ids=_document_ids(sources, state))]

    match = _SEND.match(clause)
    if match:
        recipient = _recipient(match.group("who"), policies)
        return [ActionRequest(tool="deliver_inbox", resource_id=report_id, recipient=recipient)
                for report_id in _reports(match.group("what"), state)]

    raise _Refused(f"I cannot turn '{_short(clause)}' into a tool action. Try {_EXAMPLE}.")


def _document_ids(raw: str, state) -> list[str]:
    documents = state.list_documents()
    known = {document.id.lower(): document.id for document in documents}
    if raw.strip().lower() in _ALL_DOCUMENTS:
        if not documents:
            raise _Refused("no documents are registered, so there is nothing to read or summarise.")
        return [document.id for document in documents]

    ids: list[str] = []
    for piece in re.split(r"\s*(?:,|;|\+|&|\band\b)\s*", raw, flags=re.IGNORECASE):
        token = re.sub(r"^(?:the\s+)?(?:documents?\s+)?", "", piece.strip(),
                       flags=re.IGNORECASE).strip()
        if not token:
            continue
        canonical = known.get(token.lower())
        if canonical is None:
            raise _Refused(f"'{_short(token)}' is not a registered document. "
                           f"Known documents: {', '.join(sorted(known.values()))}.")
        if canonical not in ids:
            ids.append(canonical)
    if not ids:
        raise _Refused("no document was named.")
    return ids


def _reports(raw: str, state) -> list[str]:
    """Resolve a delivery target. Ambiguity is refused, never guessed away."""
    artifacts = state.list_artifacts()
    known = {artifact.id.lower(): artifact.id for artifact in artifacts}
    phrase = raw.strip().strip("\"'").lower()
    phrase = re.sub(r"^(?:the|my|our|that|this)\s+", "", phrase)
    phrase = re.sub(r"^saved\s+", "", phrase)

    if phrase in _ALL_REPORTS:
        if not artifacts:
            raise _Refused("there is no saved report to send. Summarise a document first.")
        return [artifact.id for artifact in artifacts]

    if phrase in known:
        return [known[phrase]]
    if phrase.startswith("report ") and phrase[7:].strip() in known:
        return [known[phrase[7:].strip()]]
    if phrase in _LATEST_REPORTS:
        if not artifacts:
            raise _Refused("there is no saved report yet. Summarise a document first.")
        return [artifacts[0].id]
    if phrase.startswith("doc-"):
        raise _Refused("documents cannot be delivered directly; summarise the document into a "
                       "report first.")

    words = [word for word in re.findall(r"[a-z0-9]+", phrase)
             if len(word) >= 3 and word not in _DESCRIPTOR_STOPWORDS]
    if not words:
        raise _Refused(f"I could not tell which report '{_short(raw)}' means. "
                       f"Saved reports: {_report_ids(artifacts)}.")

    matches = [artifact for artifact in artifacts if _mentions(artifact, words, state)]
    if len(matches) == 1:
        return [matches[0].id]
    if not matches:
        raise _Refused(f"no saved report matches '{_short(raw)}'. "
                       f"Saved reports: {_report_ids(artifacts)}.")
    raise _Refused(f"'{_short(raw)}' matches more than one saved report "
                   f"({', '.join(artifact.id for artifact in matches)}). Name one by id or say "
                   "'the latest report'.")


def _mentions(artifact, words: list[str], state) -> bool:
    haystack = artifact.title.lower()
    for doc_id in artifact.label.provenance:
        document = state.get_document(doc_id)
        if document is not None:
            haystack += " " + document.title.lower()
    return any(re.search(rf"\b{re.escape(word)}\b", haystack) for word in words)


def _recipient(raw: str, policies: PolicySet) -> str:
    known = {principal.id.lower(): principal.id for principal in policies.principals
             if principal.kind != "actor"}
    token = raw.strip().strip("\"'").lower()
    token = re.sub(r"^(?:the|our)\s+", "", token)
    canonical = known.get(token)
    if canonical is None:
        raise _Refused(f"'{_short(raw)}' is not a recipient in the directory. Known recipients: "
                       f"{', '.join(sorted(known.values()))}.")
    return canonical


def _report_ids(artifacts) -> str:
    return ", ".join(artifact.id for artifact in artifacts) or "none"


# -- identity and stamping -------------------------------------------------


def _actor_id(session) -> str:
    actor_id = getattr(session, "actor_id", "")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise ValueError("propose() needs a session with a bound actor_id")
    return actor_id


def _stamp(actions: list[ActionRequest], actor_id: str) -> list[ActionRequest]:
    return [action.model_copy(update={"actor_id": actor_id, "origin": "agent"})
            for action in actions]


def _actor_ids(policies: PolicySet) -> list[str]:
    return [principal.id for principal in policies.principals if principal.kind != "recipient"]


def _strip_identity(text: str, actor_ids: list[str]) -> str:
    cleaned = " ".join(text.strip().split()).rstrip(" .!?")
    cleaned = re.sub(r"\b(?:actor|origin)\s*[=:]\s*[\w@.\-]+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\borigin\s+(?:is|was)\s+[\w@.\-]+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bas an? (?:human|agent|ai|assistant)\b", " ", cleaned, flags=re.IGNORECASE)
    for actor_id in sorted(actor_ids, key=len, reverse=True):
        ident = re.escape(actor_id)
        cleaned = re.sub(rf"\b(?:as|for|by)\s+(?:the\s+)?{ident}\b", " ", cleaned,
                         flags=re.IGNORECASE)
        cleaned = re.sub(rf"\bon behalf of\s+(?:the\s+)?{ident}\b", " ", cleaned,
                         flags=re.IGNORECASE)
        cleaned = re.sub(rf"^(?:i am|i'm|this is|acting as)\s+(?:the\s+)?{ident}\b", " ",
                         cleaned, flags=re.IGNORECASE)

    while True:
        before = cleaned
        for noise in _NOISE:
            cleaned = re.sub(rf"^(?:{noise})\b[\s,;:\-]*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:and|then)\b[\s,;:\-]*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"[\s,;:\-]*\b(?:and|then)$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"[\s,;:\-]*\bplease$", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" ,;:-")
        if cleaned == before:
            return cleaned


# -- helpers ---------------------------------------------------------------


def _refusal(reason: str) -> Proposal:
    if not reason.startswith("Refused:"):
        reason = "Refused: " + reason
    return Proposal(refusal=reason)


def _short(text: str, limit: int = 90) -> str:
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else collapsed[:limit - 3] + "..."
