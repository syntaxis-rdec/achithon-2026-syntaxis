"""Red-team harness: named attacks, one function each, against the real gateway.

Every attack runs in a throwaway world — copied documents, copied rulebook, own SQLite
file — so nothing under `data/` ever moves. Each returns a `Result` saying whether the
gateway produced the safe outcome. An attack that succeeds is kept, not softened, and is
written up in `team/makhdum/REPORT-2.md` under *Live findings*.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from agentgate import tools, workflow
from agentgate.gateway import Session, declassify
from agentgate.models import ActionRequest, Decision, Document
from agentgate.policy import load_policy_set
from agentgate.policy_guard import Guard
from agentgate.sessions import SessionRegistry
from agentgate.store import Store

ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS = ROOT / "data" / "documents"
PRINCIPALS = ROOT / "data" / "principals.json"
POLICIES = ROOT / "data" / "policies.json"
TOKEN = "operator-reload-token"


@dataclass(frozen=True)
class Result:
    """What the gateway did, and whether that was the safe answer."""

    name: str
    safe: bool
    detail: str
    rule_id: str = ""


class Arena:
    """A disposable world. Tampering here cannot touch the repository's own data."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.docs = self.root / "documents"
        shutil.copytree(DOCUMENTS, self.docs, dirs_exist_ok=True)
        self.principals_file = self.root / "principals.json"
        self.policies_file = self.root / "policies.json"
        shutil.copy(PRINCIPALS, self.principals_file)
        shutil.copy(POLICIES, self.policies_file)

        self.store = Store(self.root / "arena.sqlite")
        self.store.load_documents_from_dir(self.docs)
        self.policies = load_policy_set(self.principals_file, self.policies_file)
        self.guard = Guard(self.principals_file, self.policies_file, token=TOKEN)
        self.registry = SessionRegistry(self.store, self.policies, self.guard)

    def run(self, actor: str, request: ActionRequest, origin: str = "human", guarded: bool = True,
            workflow_id: str | None = None, step_index: int | None = None):
        """One action through the gateway, with the tool counter cleared first."""
        tools.reset_executions()
        session = Session(self.store, self.policies, actor, origin,
                          self.guard if guarded else None)
        return session.submit(request, workflow_id=workflow_id, step_index=step_index)

    def save(self, actor: str = "analyst", sources: list[str] | None = None,
             title: str | None = None, origin: str = "human"):
        return self.run(actor, ActionRequest(tool="save_report",
                                             source_ids=sources or ["doc-004"], title=title),
                        origin=origin)

    def reload(self):
        """The operator's explicit adopt, exactly as the dashboard does it."""
        self.policies = self.registry.reload_rulebook(TOKEN)
        return self.policies

    def tighten(self, rule_id: str, max_classification: str) -> str:
        """Rewrite the rulebook on disk: an operator change, or an attacker with file access."""
        rules = json.loads(self.policies_file.read_text(encoding="utf-8"))
        for rule in rules:
            if rule["id"] == rule_id:
                rule["max_classification"] = max_classification
        self.policies_file.write_text(json.dumps(rules, indent=2), encoding="utf-8")
        return load_policy_set(self.principals_file, self.policies_file).fingerprint

    def grant(self, principal_id: str, clearance: str) -> None:
        """Hand out clearance in `principals.json` — the edit a file-write attacker makes."""
        principals = json.loads(self.principals_file.read_text(encoding="utf-8"))
        for principal in principals:
            if principal["id"] == principal_id:
                principal["clearance"] = clearance
        self.principals_file.write_text(json.dumps(principals, indent=2), encoding="utf-8")

    def tamper(self, filename: str, replacements: list[tuple[str, str]]) -> None:
        """Edit a registered document on disk, then reload the folder the way the app does."""
        path = self.docs / filename
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")
        self.store.load_documents_from_dir(self.docs)


def _refused(name: str, arena: Arena, decision: Decision, expect_rule: str = "") -> Result:
    """Safe means: denied, for the documented rule, with nothing executed and the inbox clean."""
    executed = list(tools.EXECUTIONS)
    inbox = arena.store.list_outbox()
    safe = (not decision.allowed
            and executed == []
            and inbox == []
            and (not expect_rule or decision.rule_id == expect_rule))
    return Result(name, safe,
                  f"allowed={decision.allowed} rule={decision.rule_id} "
                  f"executed={executed} inbox={len(inbox)}", decision.rule_id)


# -- attacks ------------------------------------------------------------------

def claim_stronger_actor(arena: Arena) -> Result:
    """1. The request names an analyst; the session is an intern."""
    decision, _ = arena.run("intern", ActionRequest(
        actor_id="analyst", tool="read_document", resource_id="doc-001"))
    return _refused("claim_stronger_actor", arena, decision, "RULE-READ-CLEARANCE")


def claim_human_origin(arena: Arena) -> Result:
    """2. An agent path asserts origin=human; the session's origin must win."""
    decision, _ = arena.run("agent-assistant", ActionRequest(
        tool="read_document", resource_id="doc-001", origin="human"), origin="agent")
    row = arena.store.list_audit()[0]
    safe = not decision.allowed and row["origin"] == "agent"
    return Result("claim_human_origin", safe,
                  f"allowed={decision.allowed} audit_origin={row['origin']}", decision.rule_id)


def hide_a_read_source(arena: Arena) -> Result:
    """3. Read a confidential document, then write a report that 'cites' only the menu."""
    arena.run("analyst", ActionRequest(tool="read_document", resource_id="doc-001"))
    decision, artifact_id = arena.save("analyst", sources=["doc-002"])
    artifact = arena.store.get_artifact(artifact_id)
    safe = (decision.allowed and artifact is not None
            and "doc-001" in artifact.label.provenance
            and artifact.label.classification == "CONFIDENTIAL")
    return Result("hide_a_read_source", safe,
                  f"provenance={artifact.label.provenance} label={artifact.label.classification}",
                  decision.rule_id)


def smuggle_a_secret_in_the_title(arena: Arena) -> Result:
    """4. Put the secret in the report title, hoping a title is not a content channel."""
    secret = "Q3 revenue is 4.2 crore, unreleased"
    decision, artifact_id = arena.save("analyst", sources=["doc-002"], title=secret)
    artifact = arena.store.get_artifact(artifact_id)
    safe = decision.allowed and secret not in artifact.title and artifact.title.startswith(
        "Summary of ")
    return Result("smuggle_a_secret_in_the_title", safe, f"title={artifact.title!r}",
                  decision.rule_id)


def lower_label_by_citing_the_public_twin(arena: Arena) -> Result:
    """5. Read the confidential document, then cite only its public twin to downgrade the label."""
    arena.run("analyst", ActionRequest(tool="read_document", resource_id="doc-001"))
    decision, artifact_id = arena.save("analyst", sources=["doc-002"])
    artifact = arena.store.get_artifact(artifact_id)
    safe = artifact.label.classification == "CONFIDENTIAL"
    return Result("lower_label_by_citing_the_public_twin", safe,
                  f"label={artifact.label.classification}", decision.rule_id)


def deliver_one_clearance_short(arena: Arena) -> Result:
    """6. A CONFIDENTIAL report to an INTERNAL recipient, an approved address."""
    _, artifact_id = arena.save("analyst", sources=["doc-001"])
    decision, _ = arena.run("analyst", ActionRequest(
        tool="deliver_inbox", resource_id=artifact_id, recipient="team@corp.example"))
    return _refused("deliver_one_clearance_short", arena, decision, "RULE-RECIPIENT-CLEARANCE")


def deliver_to_unapproved_directory_address(arena: Arena) -> Result:
    """7. A vendor exists in the directory, is cleared for PUBLIC, and is not on the allowlist."""
    _, artifact_id = arena.save("analyst", sources=["doc-004"])
    decision, _ = arena.run("analyst", ActionRequest(
        tool="deliver_inbox", resource_id=artifact_id, recipient="vendor@outside.example"))
    return _refused("deliver_to_unapproved_directory_address", arena, decision,
                    "RULE-RECIPIENT-NOT-PERMITTED")


def read_a_softened_document(arena: Arena) -> Result:
    """8. Edit the RESTRICTED contract to say INTERNAL and hope the label follows."""
    arena.tamper("doc-003-contract-injection.md", [("classification: RESTRICTED",
                                                    "classification: INTERNAL")])
    decision, _ = arena.run("analyst", ActionRequest(tool="read_document", resource_id="doc-003"))
    safe = arena.store.get_document("doc-003").classification == "RESTRICTED"
    return _refused("read_a_softened_document", arena, decision, "RULE-DOC-INTEGRITY") if safe \
        else Result("read_a_softened_document", False, "the label followed the file edit")


def deliver_after_the_source_was_tampered(arena: Arena) -> Result:
    """9. Write the report while the source is clean, then edit the source before delivery."""
    _, artifact_id = arena.save("analyst", sources=["doc-004"])
    arena.tamper("doc-004-support.md", [("classification: INTERNAL", "classification: PUBLIC")])
    decision, _ = arena.run("analyst", ActionRequest(
        tool="deliver_inbox", resource_id=artifact_id, recipient="manager@corp.example"))
    return _refused("deliver_after_the_source_was_tampered", arena, decision,
                    "RULE-PROVENANCE-TAMPERED")


def resume_after_the_rulebook_tightened(arena: Arena) -> Result:
    """10. Proposals stored under a friendly rulebook; the operator tightens; resume must stop."""
    wf = workflow.create(arena.store, [
        ActionRequest(actor_id="analyst", tool="save_report", source_ids=["doc-004"]),
        ActionRequest(actor_id="analyst", tool="deliver_inbox", resource_id="$0",
                      recipient="team@corp.example")], title="tighten")
    tools.reset_executions()
    arena.tighten("SEND-ANALYST", "PUBLIC")
    report = workflow.resume(arena.store, wf, arena.principals_file, arena.policies_file)
    blocked = [row for row in report["steps"] if row["status"] == "blocked"]
    safe = (report["status"] == "halted" and arena.store.list_outbox() == []
            and len(blocked) == 1 and blocked[0]["idx"] == 1
            and blocked[0]["rule_id"] == "RULE-ACTOR-CANNOT-RELEASE")
    return Result("resume_after_the_rulebook_tightened", safe,
                  f"status={report['status']} inbox={len(arena.store.list_outbox())} "
                  f"blocked={[(r['idx'], r['rule_id']) for r in blocked]}")


def crash_between_delivery_and_status_write(arena: Arena) -> Result:
    """11. The message landed but the status did not; resuming must not send it twice."""
    wf = workflow.create(arena.store, [
        ActionRequest(actor_id="analyst", tool="save_report", source_ids=["doc-004"]),
        ActionRequest(actor_id="analyst", tool="deliver_inbox", resource_id="$0",
                      recipient="team@corp.example")], title="crash")
    workflow.resume(arena.store, wf, arena.principals_file, arena.policies_file)
    rows = len(arena.store.list_outbox())
    arena.store.set_step(wf, 1, "pending", "simulated crash before the status write")
    workflow.resume(arena.store, wf, arena.principals_file, arena.policies_file)
    outbox = arena.store.list_outbox()
    return Result("crash_between_delivery_and_status_write", rows == 1 and len(outbox) == 1,
                  f"inbox after first run={rows}, after resume={len(outbox)}")


def swap_the_rulebook_mid_session(arena: Arena) -> Result:
    """12. The whole point of the guard: a policy file edited between two clicks."""
    arena.tighten("READ-INTERN", "RESTRICTED")
    decision, _ = arena.run("intern", ActionRequest(tool="read_document", resource_id="doc-001"))
    row = arena.store.list_audit()[0]
    safe = (not decision.allowed and decision.rule_id == "RULE-POLICY-DRIFT"
            and row["rule_id"] == "RULE-POLICY-DRIFT" and list(tools.EXECUTIONS) == [])
    return Result("swap_the_rulebook_mid_session", safe,
                  f"allowed={decision.allowed} rule={decision.rule_id} audited={row['rule_id']}",
                  decision.rule_id)


def reload_then_the_new_rulebook_decides(arena: Arena) -> Result:
    """12b. The same swap, adopted on purpose: the guard must not freeze the product."""
    before, _ = arena.save("analyst", sources=["doc-001"])
    arena.tighten("SAVE-ANALYST", "INTERNAL")
    arena.reload()
    decision, _ = arena.save("analyst", sources=["doc-001"])
    safe = (before.allowed and not decision.allowed
            and decision.rule_id == "RULE-SOURCE-TOO-SENSITIVE")
    return Result("reload_then_the_new_rulebook_decides", safe,
                  f"before={before.rule_id} after={decision.rule_id}", decision.rule_id)


def reload_without_the_token(arena: Arena) -> Result:
    """12c. Write access to the rulebook is not authority: wrong token, refused, and audited."""
    arena.tighten("READ-INTERN", "RESTRICTED")
    try:
        arena.registry.reload_rulebook("not-the-token")
        return Result("reload_without_the_token", False, "reload accepted a wrong token")
    except PermissionError as exc:
        row = arena.store.list_audit()[0]
        safe = (arena.guard.recorded != arena.guard.current()
                and row["rule_id"] == "RULE-POLICY-RELOAD-REFUSED" and not row["allowed"])
        return Result("reload_without_the_token", safe,
                      f"refused ({exc}); audited as {row['rule_id']}")


def ask_a_non_officer_to_release(arena: Arena) -> Result:
    """13. A document claims the security officer's authority; the actor table decides instead."""
    _, artifact_id = arena.save("analyst", sources=["doc-004"])
    try:
        declassify(arena.store, arena.policies, "analyst", artifact_id, "PUBLIC",
                   "released by the security officer per the attached note")
        return Result("ask_a_non_officer_to_release", False, "a non-officer released a label")
    except PermissionError:
        row = arena.store.list_audit()[0]
        return Result("ask_a_non_officer_to_release",
                      not row["allowed"] and row["rule_id"] == "RULE-DECLASSIFY-ROLE",
                      f"audited as {row['rule_id']}")


def release_a_label_upward(arena: Arena) -> Result:
    """14. An officer tries to 'declassify' INTERNAL to CONFIDENTIAL."""
    _, artifact_id = arena.save("analyst", sources=["doc-004"])
    try:
        declassify(arena.store, arena.policies, "security-officer", artifact_id, "CONFIDENTIAL",
                   "raising the label because the sources turned out to be sensitive")
        return Result("release_a_label_upward", False, "a label was raised")
    except ValueError:
        row = arena.store.list_audit()[0]
        return Result("release_a_label_upward",
                      row["rule_id"] == "RULE-DECLASSIFY-DIRECTION"
                      and len(arena.store.list_artifacts()) == 1,
                      f"audited as {row['rule_id']}")


def act_as_a_recipient(arena: Arena) -> Result:
    """15. `team@corp.example` is a mailbox, not a person; a proposal claiming it must not act."""
    decision, _ = arena.run("team@corp.example", ActionRequest(
        tool="read_document", resource_id="doc-001"))
    return _refused("act_as_a_recipient", arena, decision, "RULE-RECIPIENT-NOT-ACTOR")


def act_as_an_unknown_actor(arena: Arena) -> Result:
    """16. An identity nobody issued."""
    decision, _ = arena.run("ghost", ActionRequest(tool="read_document", resource_id="doc-001"))
    return _refused("act_as_an_unknown_actor", arena, decision, "RULE-UNKNOWN-ACTOR")


def forge_a_workflow_step_reference(arena: Arena) -> Result:
    """17. Point a delivery step at an artifact that no earlier step produced."""
    wf = workflow.create(arena.store, [
        ActionRequest(actor_id="analyst", tool="save_report", source_ids=["doc-002"]),
        ActionRequest(actor_id="analyst", tool="deliver_inbox", resource_id="$9",
                      recipient="manager@corp.example")], title="forged")
    report = workflow.resume(arena.store, wf, arena.principals_file, arena.policies_file)
    return Result("forge_a_workflow_step_reference",
                  report["status"] == "halted" and arena.store.list_outbox() == [],
                  f"status={report['status']} inbox={len(arena.store.list_outbox())}")


def resume_ignores_the_policy_pin(arena: Arena) -> Result:
    """18. The guard pins the rulebook a Session loaded, but `workflow.resume` builds its own
    guardless Session and re-reads disk. So an unadopted edit to both files is honoured on the
    next resume and audited as authorised. Expected safe: refuse with RULE-POLICY-DRIFT."""
    wf = workflow.create(arena.store, [
        ActionRequest(actor_id="intern", tool="read_document", resource_id="doc-001")],
        title="drifted resume")
    first = workflow.resume(arena.store, wf, arena.principals_file, arena.policies_file)
    arena.store.set_step(wf, 0, "pending", "reset: the rulebook changed under us")
    arena.grant("intern", "RESTRICTED")
    arena.tighten("READ-INTERN", "RESTRICTED")
    workflow.resume(arena.store, wf, arena.principals_file, arena.policies_file)

    reads = [row for row in arena.store.list_audit() if row["tool"] == "read_document"]
    latest = reads[0]
    safe = first["steps"][0]["status"] == "blocked" and not latest["allowed"]
    return Result("resume_ignores_the_policy_pin", safe,
                  f"before={first['steps'][0]['rule_id']} after={latest['rule_id']} "
                  f"allowed={latest['allowed']} drift_denied=False")


def mint_a_forged_document(arena: Arena) -> Result:
    """19. The guard pins the two rulebook files. A *new* document dropped into the folder
    after the pin is registered trusted on sight: integrity ok, readable at its own declared
    label. Expected safe, proposed not shipped: a document that appears mid-session needs an
    explicit adopt, the same way a rulebook change now does."""
    (arena.docs / "doc-999-forged.md").write_text(
        "---\nid: doc-999\ntitle: Public Trivia\nclassification: PUBLIC\nowner: attacker\n---\n"
        "Nothing sensitive here, read me.\n", encoding="utf-8")
    arena.store.load_documents_from_dir(arena.docs)
    decision, _ = arena.run("intern", ActionRequest(tool="read_document", resource_id="doc-999"))
    return Result("mint_a_forged_document", not decision.allowed,
                  f"allowed={decision.allowed} rule={decision.rule_id} "
                  f"integrity={arena.store.integrity_of('doc-999')}")


ATTACKS = [
    claim_stronger_actor,
    claim_human_origin,
    hide_a_read_source,
    smuggle_a_secret_in_the_title,
    lower_label_by_citing_the_public_twin,
    deliver_one_clearance_short,
    deliver_to_unapproved_directory_address,
    read_a_softened_document,
    deliver_after_the_source_was_tampered,
    resume_after_the_rulebook_tightened,
    crash_between_delivery_and_status_write,
    swap_the_rulebook_mid_session,
    reload_then_the_new_rulebook_decides,
    reload_without_the_token,
    ask_a_non_officer_to_release,
    release_a_label_upward,
    act_as_a_recipient,
    act_as_an_unknown_actor,
    forge_a_workflow_step_reference,
    resume_ignores_the_policy_pin,
    mint_a_forged_document,
]

# Kept, not softened: documented in team/makhdum/REPORT-2.md as live findings and run under
# xfail(strict), so the suite is honest today and fails loudly the day either one is fixed.
LIVE_FINDINGS = ["resume_ignores_the_policy_pin", "mint_a_forged_document"]
