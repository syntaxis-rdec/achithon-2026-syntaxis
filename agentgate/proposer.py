"""Natural language into proposed tool actions, with no authority at all.

The proposer reads a sentence, resolves identifiers against local state, and builds
`ActionRequest` objects. It never evaluates policy, never calls a tool, and cannot
express a release. Every proposal must still go through
`agentgate.gateway.Session.submit`, which binds the actor and origin and consults the
deterministic policy engine. Identity written in the sentence is discarded.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from pydantic import BaseModel, Field

from .models import ActionRequest, PolicySet

ROOT = Path(__file__).resolve().parent.parent

Transport = Callable[[str, dict[str, Any], dict[str, str], float], bytes | str]

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

_SYSTEM_PROMPT = (
    "Translate one sentence into tool actions for a security gateway. Reply with JSON only, "
    'in the shape {"actions":[{"tool":"read_document","resource_id":"doc-001"}]}. '
    "read_document takes resource_id. save_report takes source_ids. deliver_inbox takes "
    "resource_id and recipient. Use only ids from the vocabulary; never invent an id. "
    "Identity is bound by the gateway: do not emit or infer an actor or origin. Changing a "
    "security classification is not an available action. If the sentence cannot be expressed, "
    'reply {"actions":[]}.'
)
_MODEL_ACTION_KEYS = {"tool", "resource_id", "source_ids", "recipient", "actor_id", "origin"}
_MODEL_IGNORED_KEYS = {"actor_id", "origin"}
_MODEL_TOOLS = ("read_document", "save_report", "deliver_inbox")
_MAX_MODEL_ACTIONS = 20


@dataclass(frozen=True)
class ModelConfig:
    """Optional model endpoint. The key is kept out of repr and never persisted."""

    base_url: str
    api_key: str = field(repr=False)
    model: str = "gpt-4o-mini"
    timeout: float = 8.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ModelConfig | None:
        source = os.environ if env is None else env
        base_url = source.get("AGENTGATE_MODEL_BASE_URL", "").strip()
        api_key = source.get("AGENTGATE_MODEL_KEY", "").strip()
        if not base_url or not api_key:
            return None
        model = source.get("AGENTGATE_MODEL_NAME", "").strip() or "gpt-4o-mini"
        return cls(base_url=base_url, api_key=api_key, model=model)


class _Refused(Exception):
    """A sentence this deterministic parser will not turn into an action."""


class Proposal(BaseModel):
    """What the proposer understood. Not a decision and not a permission."""

    actions: list[ActionRequest] = Field(default_factory=list)
    backend: Literal["scripted", "model"] = "scripted"
    refusal: str | None = None


def propose(sentence: str, *, session, state, policies: PolicySet,
            transport: Transport | None = None,
            config: ModelConfig | None = None) -> Proposal:
    """Turn one sentence into proposals for the session's actor.

    `session` supplies the identity; anything the sentence says about identity is
    ignored. The returned actions still have to pass `Session.submit`. The model
    backend is used only when both model environment variables are configured (or a
    `config` is passed); otherwise the deterministic scripted parser runs.
    """
    actor_id = _actor_id(session)
    text = " ".join(sentence.split()) if isinstance(sentence, str) else ""
    if not text:
        return _refusal("the proposer needs a sentence to interpret.")
    if _RELEASE_RE.search(text):
        return Proposal(refusal=_RELEASE_REFUSAL)

    model = config if config is not None else ModelConfig.from_env()
    if model is not None:
        return _model_proposal(text, actor_id=actor_id, state=state, policies=policies,
                               config=model, transport=transport or _urllib_transport)
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


# -- optional model backend ------------------------------------------------


def _model_proposal(text: str, *, actor_id: str, state, policies: PolicySet,
                    config: ModelConfig, transport: Transport) -> Proposal:
    content = _call_model(text, state=state, policies=policies, config=config,
                          transport=transport)
    if content is None:
        return _scripted(text, actor_id=actor_id, state=state, policies=policies)

    try:
        payload = json.loads(_strip_fence(content))
    except (json.JSONDecodeError, TypeError):
        return _model_refusal("the model reply was not valid JSON, so it was discarded.")
    try:
        actions = _actions_from_model(payload, state=state, policies=policies)
    except _Refused as refused:
        return _model_refusal(str(refused))
    return Proposal(actions=_stamp(actions, actor_id), backend="model")


def _call_model(text: str, *, state, policies: PolicySet, config: ModelConfig,
                transport: Transport) -> str | None:
    """Return the reply text, or None when the call itself failed.

    Any transport, HTTP or envelope failure counts as the model backend being
    unavailable; the caller then falls back to the scripted parser. A reply that
    arrives but breaks the contract is handled separately as untrusted input.
    """
    payload = _model_payload(text, state=state, policies=policies, model=config.model)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.api_key}",
    }
    try:
        body = transport(config.base_url, payload, headers, config.timeout)
        if isinstance(body, str):
            body = body.encode("utf-8")
        envelope = json.loads(body)
        content = envelope["choices"][0]["message"]["content"]
    except Exception:
        return None
    return content if isinstance(content, str) else None


def _model_payload(sentence: str, *, state, policies: PolicySet, model: str) -> dict[str, Any]:
    """Sentence plus identifiers only: no titles, labels, bodies or policy text."""
    vocabulary = {
        "sentence": sentence,
        "documents": [document.id for document in state.list_documents()],
        "reports": [artifact.id for artifact in state.list_artifacts()],
        "actors": [principal.id for principal in policies.principals
                   if principal.kind != "recipient"],
        "recipients": [principal.id for principal in policies.principals
                       if principal.kind != "actor"],
    }
    return {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(vocabulary, ensure_ascii=False)},
        ],
    }


def _actions_from_model(raw, *, state, policies: PolicySet) -> list[ActionRequest]:
    if not isinstance(raw, dict):
        raise _Refused("the model reply was not a JSON object, so it was discarded.")
    unexpected = set(raw) - {"actions"} - _MODEL_IGNORED_KEYS
    if unexpected:
        raise _Refused("the model reply carried unexpected field(s) "
                       f"{_field_list(unexpected)}, so it was discarded.")
    items = raw.get("actions")
    if not isinstance(items, list):
        raise _Refused("the model reply had no list of actions, so it was discarded.")
    if not items:
        raise _Refused("the model returned no tool action, so nothing was proposed.")
    if len(items) > _MAX_MODEL_ACTIONS:
        raise _Refused(f"the model returned {len(items)} actions; the limit is "
                       f"{_MAX_MODEL_ACTIONS}, so the reply was discarded.")
    return [_action_from_model(item, state=state, policies=policies) for item in items]


def _action_from_model(item, *, state, policies: PolicySet) -> ActionRequest:
    if not isinstance(item, dict):
        raise _Refused("the model reply contained an action that was not an object, "
                       "so it was discarded.")
    unexpected = set(item) - _MODEL_ACTION_KEYS
    if unexpected:
        raise _Refused("the model action carried unexpected field(s) "
                       f"{_field_list(unexpected)}, so it was discarded.")
    item = {key: value for key, value in item.items() if key not in _MODEL_IGNORED_KEYS}

    tool = item.get("tool")
    if not isinstance(tool, str) or tool not in _MODEL_TOOLS:
        raise _Refused(f"the model asked for unknown tool '{_short(tool)}', "
                       "so nothing was proposed.")
    resource = item.get("resource_id")
    if resource is not None and not isinstance(resource, str):
        raise _Refused("the model gave a resource id that is not text, "
                       "so the reply was discarded.")
    recipient = item.get("recipient")
    if recipient is not None and not isinstance(recipient, str):
        raise _Refused("the model gave a recipient that is not text, "
                       "so the reply was discarded.")
    sources = item.get("source_ids")
    if sources is None:
        sources = []
    if not isinstance(sources, list) or any(not isinstance(source, str) for source in sources):
        raise _Refused("the model gave sources that are not a list of ids, "
                       "so the reply was discarded.")

    if tool == "read_document":
        if sources or recipient:
            raise _Refused("the model mixed fields across tools, so the reply was discarded.")
        return ActionRequest(tool="read_document", resource_id=_model_document(resource, state))
    if tool == "save_report":
        if resource or recipient:
            raise _Refused("the model mixed fields across tools, so the reply was discarded.")
        if not sources:
            raise _Refused("the model proposed a report with no sources, "
                           "so nothing was proposed.")
        return ActionRequest(tool="save_report", source_ids=_model_sources(sources, state))
    if sources:
        raise _Refused("the model mixed fields across tools, so the reply was discarded.")
    if not resource or not recipient:
        raise _Refused("the model proposed a delivery without a report or recipient, "
                       "so nothing was proposed.")
    return ActionRequest(tool="deliver_inbox", resource_id=_model_artifact(resource, state),
                         recipient=_model_recipient(recipient, policies))


def _model_document(resource: str | None, state) -> str:
    if not resource:
        raise _Refused("the model proposed a read without a document id, "
                       "so nothing was proposed.")
    known = {document.id.lower(): document.id for document in state.list_documents()}
    canonical = known.get(resource.lower())
    if canonical is None:
        raise _Refused(f"the model named document '{_short(resource)}', which is not "
                       "registered, so the reply was discarded.")
    return canonical


def _model_sources(sources: list[str], state) -> list[str]:
    known = {document.id.lower(): document.id for document in state.list_documents()}
    canonical: list[str] = []
    for source in sources:
        document = known.get(source.lower())
        if document is None:
            raise _Refused(f"the model named source '{_short(source)}', which is not "
                           "registered, so the reply was discarded.")
        if document not in canonical:
            canonical.append(document)
    return canonical


def _model_artifact(resource: str | None, state) -> str:
    known = {artifact.id.lower(): artifact.id for artifact in state.list_artifacts()}
    canonical = known.get(resource.lower()) if resource else None
    if canonical is None:
        raise _Refused(f"the model named report '{_short(resource)}', which does not exist, "
                       "so the reply was discarded.")
    return canonical


def _model_recipient(raw: str, policies: PolicySet) -> str:
    known = {principal.id.lower(): principal.id for principal in policies.principals
             if principal.kind != "actor"}
    canonical = known.get(raw.lower())
    if canonical is None:
        raise _Refused(f"the model named recipient '{_short(raw)}', which is not in the "
                       "directory, so the reply was discarded.")
    return canonical


def _strip_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text


def _urllib_transport(url: str, payload: dict[str, Any], headers: dict[str, str],
                      timeout: float) -> bytes:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


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


def _model_refusal(reason: str) -> Proposal:
    return Proposal(backend="model", refusal="Refused: " + reason)


def _field_list(names, limit: int = 4) -> str:
    clean = sorted(_short(name, 30) for name in names)
    shown = ", ".join(clean[:limit])
    return shown + ("..." if len(clean) > limit else "")


def _short(text: str, limit: int = 90) -> str:
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else collapsed[:limit - 3] + "..."


# -- command line ----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agentgate.proposer",
        description="Propose tool actions from one sentence, then let the gateway decide.")
    parser.add_argument("sentence", help="the sentence to interpret")
    parser.add_argument("--actor", default="agent-assistant",
                        help="actor whose session proposes (default: agent-assistant)")
    parser.add_argument("--db", default=str(ROOT / "data" / "agentgate-v3.sqlite"),
                        help="state file to read and audit (default: the dashboard database)")
    args = parser.parse_args(argv)

    from .gateway import Session
    from .policy import load_policy_set
    from .store import Store

    try:
        store = Store(args.db)
    except Exception as error:
        print(f"Cannot open state file '{args.db}': {error}", file=sys.stderr)
        return 3

    try:
        seeded = 0
        if not store.list_documents():
            seeded = store.load_documents_from_dir(ROOT / "data" / "documents")
        policies = load_policy_set(ROOT / "data" / "principals.json",
                                   ROOT / "data" / "policies.json")
        principal = policies.principal(args.actor)
        if principal is None or principal.kind == "recipient":
            print(f"Refused: '{args.actor}' is not an actor in the directory.",
                  file=sys.stderr)
            return 3
        if seeded:
            print(f"State {args.db} was empty; registered {seeded} documents.")

        session = Session(store, policies, args.actor, origin="agent")
        proposal = propose(args.sentence, session=session, state=store, policies=policies)
        print(f"Sentence: {args.sentence}")
        print(f"Backend: {proposal.backend}")
        if proposal.refusal:
            print(proposal.refusal)
            print("Gateway: nothing was submitted. A refusal is not an authorisation.")
            if "report" in proposal.refusal.lower():
                print("Hint: create one first with: "
                      f'python -m agentgate.proposer --db "{args.db}" '
                      '--actor analyst "summarise doc-001"')
            return 2

        print("Proposal:")
        for action in proposal.actions:
            print("  - " + _describe(action))
        print(f"Gateway decisions (state {args.db}, policy {policies.fingerprint}):")
        for action in proposal.actions:
            decision, result = session.submit(action)
            verdict = "ALLOWED" if decision.allowed else "BLOCKED"
            print(f"  {verdict} {decision.rule_id}: {decision.reason}")
            if result is not None:
                print(f"    result: {result}")
        return 0
    finally:
        store.close()


def _describe(action: ActionRequest) -> str:
    target = action.resource_id or ",".join(action.source_ids) or "-"
    line = f"{action.tool} {target}"
    if action.recipient:
        line += f" to {action.recipient}"
    return f"{line} (actor={action.actor_id}, origin={action.origin})"


if __name__ == "__main__":
    raise SystemExit(main())
