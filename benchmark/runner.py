"""Runs the frozen scenario table and writes a defensible evidence report.

The table is written from the specification before any run. The runner never edits
expectations: a mismatch is reported, not absorbed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from agentgate import tools
from agentgate.gateway import Session, declassify
from agentgate.models import ActionRequest
from agentgate.policy import load_policy_set
from agentgate.sessions import SessionRegistry
from agentgate.store import Store

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "benchmark" / "scenarios.json"
RESULTS = ROOT / "benchmark" / "results.json"
DOCS = ROOT / "data" / "documents"
PRINCIPALS = ROOT / "data" / "principals.json"
POLICIES = ROOT / "data" / "policies.json"

REQUIRED_AUDIT_FIELDS = ("actor", "origin", "tool", "rule_id", "reason", "policy_hash")


def _apply_policy_patch(rules: list[dict], principals: list[dict], patch: dict) -> None:
    for rule in rules:
        if rule["id"] == patch.get("rule"):
            for key, value in patch.get("set", {}).items():
                rule[key] = value
    for person in principals:
        if person["id"] == patch.get("principal"):
            for key, value in patch.get("set", {}).items():
                person[key] = value
    if patch.get("remove_rule"):
        rules[:] = [r for r in rules if r["id"] != patch["remove_rule"]]


def run_scenario(scenario: dict) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="scn-"))
    docs_dir = tmp / "documents"
    shutil.copytree(DOCS, docs_dir)
    for extra in scenario.get("extra_documents", []):
        (docs_dir / f"{extra['id']}.md").write_text(
            f"---\nid: {extra['id']}\ntitle: {extra['title']}\nowner: {extra['owner']}\n"
            f"classification: {extra['classification']}\n---\n{extra['body']}\n", encoding="utf-8")

    rules = json.loads(POLICIES.read_text(encoding="utf-8"))
    principals = json.loads(PRINCIPALS.read_text(encoding="utf-8"))
    for patch in scenario.get("policy_patches", []):
        _apply_policy_patch(rules, principals, patch)
    (tmp / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    (tmp / "principals.json").write_text(json.dumps(principals), encoding="utf-8")

    store = Store(tmp / "state.sqlite")
    store.load_documents_from_dir(docs_dir)
    policies = load_policy_set(tmp / "principals.json", tmp / "rules.json")
    registry = SessionRegistry(store, policies)
    refs: dict[str, str] = {}
    setup_error = ""

    try:
        for step in scenario.get("setup", []):
            kind = step["kind"]
            if kind == "read":
                registry.get(step["actor"], step.get("origin", "human")).submit(
                    ActionRequest(tool="read_document", resource_id=step["doc"]))
            elif kind == "save":
                _, artifact_id = registry.get(step["actor"], step.get("origin", "human")).submit(
                    ActionRequest(tool="save_report", source_ids=step["sources"]))
                refs[step["as"]] = artifact_id
            elif kind == "deliver":
                registry.get(step["actor"], step.get("origin", "human")).submit(
                    ActionRequest(tool="deliver_inbox", resource_id=refs[step["artifact"]],
                                  recipient=step["recipient"]))
            elif kind == "declassify":
                child = declassify(store, policies, step["officer"], refs[step["artifact"]],
                                   step["target"],
                                   step.get("justification", "a sufficiently long justification"))
                if step.get("as"):
                    refs[step["as"]] = child.id
            elif kind == "tamper":
                target = docs_dir / step["file"]
                text = target.read_text(encoding="utf-8")
                target.write_text(text.replace(step["replace"], step["with"]), encoding="utf-8")
                store.load_documents_from_dir(docs_dir)
    except (ValueError, PermissionError) as error:
        setup_error = str(error)

    if setup_error:
        expect = scenario["expect"]
        row = {
            "id": scenario["id"], "title": scenario["title"], "category": scenario["category"],
            "spec": scenario.get("spec", ""), "expected": expect,
            "actual": {"allowed": False, "rule": "SETUP-ERROR", "reason": setup_error,
                       "raised": setup_error, "artifact_label": ""},
            "verdict_match": False,
            "rule_match": False, "artifact_ok": False, "scenario_ok": False,
            "executions": 0, "effect": 0, "outbox_delta": 0, "audit_complete": False,
        }
        store.close()
        shutil.rmtree(tmp, ignore_errors=True)
        return row

    action = scenario["action"]
    resolved = dict(action)
    if action.get("resource_ref"):
        resolved["resource_id"] = refs[action["resource_ref"]]

    ex_before = len(tools.EXECUTIONS)
    outbox_before = len(store.list_outbox())
    audit_before = len(store.list_audit(limit=100000))
    artifacts_before = len(store.list_artifacts())
    raised = ""
    if action.get("kind") == "declassify":
        try:
            declassify(store, policies, action["actor"], refs[action["artifact"]],
                       action["target"], action.get("justification", "a long enough justification"))
        except (PermissionError, ValueError) as error:
            raised = str(error)
        latest_rows = store.list_audit(limit=1)
        if latest_rows:
            latest = latest_rows[0]
            decision_allowed = bool(latest["allowed"])
            decision_rule = latest["rule_id"]
            decision_reason = latest["reason"]
        else:
            decision_allowed, decision_rule = False, "NO-AUDIT-ROW"
            decision_reason = "the gateway wrote no audit row for this release"
        result = None
    else:
        decision, result = registry.get(action["actor"], action.get("origin", "human")).submit(
            ActionRequest(actor_id=resolved.get("claimed_actor", ""), tool=action["tool"],
                          resource_id=resolved.get("resource_id"),
                          source_ids=resolved.get("sources", []),
                          recipient=resolved.get("recipient")))
        decision_allowed, decision_rule, decision_reason = (
            decision.allowed, decision.rule_id, decision.reason)

    ex_delta = len(tools.EXECUTIONS) - ex_before
    outbox_delta = len(store.list_outbox()) - outbox_before
    artifact_delta = len(store.list_artifacts()) - artifacts_before
    audit = store.list_audit(limit=100000)
    new_rows = audit[: len(audit) - audit_before]

    expect = scenario["expect"]
    verdict_match = decision_allowed == expect["allowed"]
    rule_match = decision_rule == expect["rule"]
    artifact_ok = True
    artifact_label = ""
    if scenario.get("expect_artifact_label") and isinstance(result, str):
        artifact = store.get_artifact(result)
        artifact_label = artifact.label.classification if artifact else "missing"
        artifact_ok = artifact_label == scenario["expect_artifact_label"]
    complete = bool(new_rows) and int(decision_allowed) == new_rows[0]["allowed"] and all(
        str(new_rows[0][field] or "").strip() for field in REQUIRED_AUDIT_FIELDS)
    effect = artifact_delta if action.get("kind") == "declassify" else ex_delta
    result_row = {
        "id": scenario["id"],
        "title": scenario["title"],
        "category": scenario["category"],
        "spec": scenario.get("spec", ""),
        "expected": expect,
        "actual": {"allowed": decision_allowed, "rule": decision_rule, "reason": decision_reason,
                   "raised": raised, "artifact_label": artifact_label},
        "verdict_match": verdict_match,
        "rule_match": rule_match,
        "artifact_ok": artifact_ok,
        "scenario_ok": verdict_match and rule_match and artifact_ok,
        "executions": ex_delta,
        "effect": effect,
        "outbox_delta": outbox_delta,
        "audit_complete": complete,
    }
    store.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return result_row


def run_suite(scenarios_path: Path = SCENARIOS, results_path: Path | None = RESULTS) -> dict:
    scenarios = json.loads(Path(scenarios_path).read_text(encoding="utf-8"))["scenarios"]
    tools.reset_executions()
    rows = [run_scenario(s) for s in scenarios]

    allow_rows = [r for r in rows if r["expected"]["allowed"]]
    deny_rows = [r for r in rows if not r["expected"]["allowed"]]
    metrics = {
        "scenarios": len(rows),
        "expected_allow": len(allow_rows),
        "expected_deny": len(deny_rows),
        "verdict_matches": sum(r["verdict_match"] for r in rows),
        "rule_matches": sum(r["rule_match"] for r in rows),
        "scenario_matches": sum(r["scenario_ok"] for r in rows),
        "false_denies": sum(1 for r in allow_rows if not r["actual"]["allowed"]),
        "false_allows": sum(1 for r in deny_rows if r["actual"]["allowed"]),
        "unauthorized_executions": sum(1 for r in deny_rows if r["executions"] > 0),
        "allowed_without_effect": sum(1 for r in allow_rows if r["effect"] != 1),
        "audit_complete": sum(r["audit_complete"] for r in rows),
    }
    report = {
        "scenario_file_sha256": hashlib.sha256(SCENARIOS.read_bytes()).hexdigest()[:16],
        "policy_fingerprint": load_policy_set(PRINCIPALS, POLICIES).fingerprint,
        "metrics": metrics,
        "rows": rows,
    }
    if results_path is not None:
        Path(results_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report

if __name__ == "__main__":
    report = run_suite()
    print(json.dumps(report["metrics"], indent=2))
