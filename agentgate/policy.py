"""The only authorization authority in AGENTGATE.

Deterministic, pure, and blind to document text. Reasons carry identifiers and
labels only — never document titles, so a denial cannot leak what it protects.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import labels
from .models import ActionRequest, Decision, PolicySet, SecurityLabel


def load_policy_set(principals_path: str | Path, policies_path: str | Path) -> PolicySet:
    principals_raw = Path(principals_path).read_bytes()
    rules_raw = Path(policies_path).read_bytes()
    parsed_rules = json.loads(rules_raw.decode("utf-8"))
    seen: set[tuple[str, str]] = set()
    duplicates: list[str] = []
    for rule in parsed_rules:
        key = (rule["role"], rule["tool"])
        if key in seen:
            duplicates.append(f"{rule['role']}/{rule['tool']}")
        seen.add(key)
    if duplicates:
        raise ValueError("duplicate policy rules for role/tool: " + ", ".join(sorted(set(duplicates))))
    fingerprint = hashlib.sha256(principals_raw + b"\n" + rules_raw).hexdigest()[:16]
    return PolicySet(
        principals=json.loads(principals_raw.decode("utf-8")),
        rules=parsed_rules,
        fingerprint=fingerprint,
    )


def evaluate(request: ActionRequest, state, policies: PolicySet) -> Decision:
    actor = policies.principal(request.actor_id)
    if actor is None:
        return _deny("RULE-UNKNOWN-ACTOR", f"Actor '{request.actor_id}' is not in the directory.")
    if actor.kind == "recipient":
        return _deny("RULE-RECIPIENT-NOT-ACTOR", f"'{actor.id}' is a delivery target, not an actor.")

    matching = policies.rules_for(actor.role, request.tool)
    if not matching:
        return _deny("RULE-NO-GRANT",
                     f"Role '{actor.role}' has no rule allowing '{request.tool}'. Default deny.")
    rule = matching[0]

    if request.tool == "read_document":
        return _check_read(request, state, actor, rule)
    if request.tool == "save_report":
        return _check_save(request, state, actor, rule)
    return _check_deliver(request, state, actor, rule, policies)


# -- per-tool checks -------------------------------------------------------


def _check_read(request, state, actor, rule) -> Decision:
    doc = state.get_document(request.resource_id or "")
    if doc is None:
        return _deny("RULE-NO-SUCH-DOCUMENT", f"Document '{request.resource_id}' does not exist.")
    integrity = state.integrity_of(doc.id)
    if integrity == "tampered":
        return _deny("RULE-DOC-INTEGRITY",
                     f"Blocked: document '{doc.id}' changed on disk after registration.")
    if integrity == "invalid":
        return _deny("RULE-DOC-INVALID",
                     f"Blocked: document '{doc.id}' declares an unrecognised classification and is "
                     "treated as RESTRICTED until corrected.")
    ceiling = _ceiling(actor.clearance, rule.max_classification)
    if not labels.at_least(ceiling, doc.classification):
        return _deny(
            "RULE-READ-CLEARANCE",
            f"Blocked: document '{doc.id}' is {doc.classification}; {actor.id} holds "
            f"{actor.clearance} and rule {rule.id} caps reads at {rule.max_classification}. "
            "The text was never opened.",
        )
    return _allow(
        rule.id,
        f"Allowed: {actor.id} holds {actor.clearance}; document '{doc.id}' is "
        f"{doc.classification}, within rule {rule.id}.",
        SecurityLabel(classification=doc.classification, provenance=[doc.id],
                      tags=[f"owner:{doc.owner}"]),
    )


def _check_save(request, state, actor, rule) -> Decision:
    if not request.source_ids:
        return _deny("RULE-NO-SOURCES", "A report must cite at least one source document.")
    found = []
    for doc_id in request.source_ids:
        doc = state.get_document(doc_id)
        if doc is None:
            return _deny("RULE-NO-SUCH-DOCUMENT", f"Source '{doc_id}' does not exist.")
        integrity = state.integrity_of(doc.id)
        if integrity == "tampered":
            return _deny("RULE-DOC-INTEGRITY",
                         f"Blocked: source '{doc.id}' changed on disk after registration.")
        if integrity == "invalid":
            return _deny("RULE-DOC-INVALID",
                         f"Blocked: source '{doc.id}' has an unrecognised classification.")
        ceiling = _ceiling(actor.clearance, rule.max_classification)
        if not labels.at_least(ceiling, doc.classification):
            return _deny(
                "RULE-SOURCE-TOO-SENSITIVE",
                f"Blocked: source '{doc.id}' is {doc.classification}, above what {actor.id} may "
                f"summarise under rule {rule.id}. No report was written.",
            )
        found.append(doc)
    derived = labels.combine([
        SecurityLabel(classification=d.classification, provenance=[d.id], tags=[f"owner:{d.owner}"])
        for d in found
    ])
    return _allow(
        rule.id,
        f"Allowed: report inherits {derived.classification}, the highest of its sources, and keeps "
        f"provenance {', '.join(derived.provenance)}.",
        derived,
    )


def _check_deliver(request, state, actor, rule, policies: PolicySet) -> Decision:
    artifact = state.get_artifact(request.resource_id or "")
    if artifact is None:
        return _deny("RULE-NO-SUCH-ARTIFACT",
                     f"Artifact '{request.resource_id}' does not exist. Nothing was sent.")
    for entry in artifact.label.provenance:
        if state.get_document(entry) is not None and state.is_blocked_document(entry):
            return _deny(
                "RULE-PROVENANCE-TAMPERED",
                f"Blocked: artifact '{artifact.id}' descends from '{entry}', which is no longer "
                "trusted. The report must be rebuilt from clean sources.",
                artifact.label,
            )
    recipient_id = request.recipient or ""
    if recipient_id not in actor.allowed_recipients:
        return _deny(
            "RULE-RECIPIENT-NOT-PERMITTED",
            f"Blocked: rule {rule.id} does not permit {actor.id} to send to '{recipient_id}'. "
            "The message never reached the inbox.",
            artifact.label,
        )
    recipient = policies.principal(recipient_id)
    if recipient is None:
        return _deny("RULE-UNKNOWN-RECIPIENT",
                     f"Blocked: '{recipient_id}' is not in the directory.", artifact.label)
    if not labels.at_least(recipient.clearance, artifact.label.classification):
        return _deny(
            "RULE-RECIPIENT-CLEARANCE",
            f"Blocked: artifact '{artifact.id}' is {artifact.label.classification} but "
            f"{recipient_id} holds only {recipient.clearance}.",
            artifact.label,
        )
    if not labels.at_least(_ceiling(actor.clearance, rule.max_classification),
                           artifact.label.classification):
        return _deny(
            "RULE-ACTOR-CANNOT-RELEASE",
            f"Blocked: {actor.id} may not release {artifact.label.classification} material under "
            f"rule {rule.id}.",
            artifact.label,
        )
    return _allow(
        rule.id,
        f"Allowed: {recipient_id} holds {recipient.clearance}; artifact '{artifact.id}' is "
        f"{artifact.label.classification}; recipient is approved for {actor.id}.",
        artifact.label,
    )


# -- helpers ---------------------------------------------------------------


def _ceiling(actor_clearance: str, rule_max: str) -> str:
    """The stricter of personal clearance and the rule's cap."""
    return actor_clearance if labels.rank(actor_clearance) <= labels.rank(rule_max) else rule_max


def _allow(rule_id: str, reason: str, label: SecurityLabel | None = None) -> Decision:
    return Decision(allowed=True, rule_id=rule_id, reason=reason, label=label)


def _deny(rule_id: str, reason: str, label: SecurityLabel | None = None) -> Decision:
    return Decision(allowed=False, rule_id=rule_id, reason=reason, label=label)
