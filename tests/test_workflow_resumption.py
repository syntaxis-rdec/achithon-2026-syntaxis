"""Workflow resumption: a stored workflow is a list of proposals, re-decided on every run.

Every test here reads or writes the policy JSON on disk, because that is the whole point
of resumption — the rulebook that applies is the one that exists when the app wakes up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentgate import tools, workflow
from agentgate.models import ActionRequest
from agentgate.policy import load_policy_set
from agentgate.store import Store

ROOT = Path(__file__).resolve().parent.parent
PRINCIPALS = ROOT / "data" / "principals.json"
POLICIES = ROOT / "data" / "policies.json"
DOCS = ROOT / "data" / "documents"


# -- helpers ---------------------------------------------------------------


def _rulebook(tmp_path: Path) -> Path:
    """A scratch copy of the rulebook that a test can change on disk."""
    dest = tmp_path / "policies.json"
    dest.write_text(POLICIES.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def _edit_rule(path: Path, rule_id: str, **changes) -> str:
    """Change one rule the way a human editing data/policies.json would, return the
    fingerprint the new file now carries."""
    rules = json.loads(Path(path).read_text(encoding="utf-8"))
    for rule in rules:
        if rule["id"] == rule_id:
            rule.update(changes)
    Path(path).write_text(json.dumps(rules), encoding="utf-8")
    return load_policy_set(PRINCIPALS, path).fingerprint


def _read_save_send(actor: str = "analyst", doc: str = "doc-004",
                    recipient: str = "team@corp.example") -> list[ActionRequest]:
    """Read a document, summarise it, deliver the summary to the report it just made."""
    return [
        ActionRequest(actor_id=actor, tool="read_document", resource_id=doc),
        ActionRequest(actor_id=actor, tool="save_report", source_ids=[doc]),
        ActionRequest(actor_id=actor, tool="deliver_inbox", resource_id="$1",
                      recipient=recipient),
    ]


def _audit(state: Store, workflow_id: str, step_index: int | None = None) -> list[dict]:
    """Read the trail with plain SQL: the database alone must tell the story."""
    sql = "SELECT * FROM audit WHERE workflow_id=?"
    args: list[object] = [workflow_id]
    if step_index is not None:
        sql += " AND step_index=?"
        args.append(step_index)
    return [dict(row) for row in state.conn.execute(sql + " ORDER BY id", args)]


def _crash_at_step(monkeypatch, step_index: int, before_write: bool) -> dict:
    """Kill the process while the runner is working on one step.

    `before_write=True` loses the status write but keeps the effect the tool already
    made; `False` is the ordinary case of closing the app between two steps. Set the
    returned switch's "armed" to False to stand the process back up.
    """
    real = Store.set_step
    switch = {"armed": True}

    def crashing(self, workflow_id, idx, status, reason="", output=None):
        if idx == step_index and switch["armed"]:
            if before_write:
                raise RuntimeError("simulated exit: effect done, status not written")
            real(self, workflow_id, idx, status, reason, output)
            raise RuntimeError("simulated exit: stopped between steps")
        real(self, workflow_id, idx, status, reason, output)

    monkeypatch.setattr(Store, "set_step", crashing)
    return switch


# -- a whole run -----------------------------------------------------------


def test_a_permitted_workflow_runs_to_completion_with_one_effect_per_step(state):
    wf = workflow.create(state, _read_save_send(), title="read, summarise, deliver")
    report = workflow.resume(state, wf, PRINCIPALS, POLICIES)

    assert report["status"] == "completed"
    assert [s["status"] for s in report["steps"]] == ["done", "done", "done"]
    assert [s["tool"] for s in report["steps"]] == [
        "read_document", "save_report", "deliver_inbox"]

    assert len(tools.EXECUTIONS) == 3
    assert len(state.list_artifacts()) == 1
    assert len(state.list_outbox()) == 1
    assert state.list_outbox()[0]["classification"] == "INTERNAL"

    rows = _audit(state, wf)
    assert [r["step_index"] for r in rows] == [0, 1, 2]
    assert all(r["workflow_id"] == wf and r["allowed"] == 1 for r in rows)
    assert all(r["policy_hash"] == report["policy_fingerprint"] for r in rows)

    again = workflow.resume(state, wf, PRINCIPALS, POLICIES)
    assert again["status"] == "completed" and again["steps"] == []
    assert len(state.list_outbox()) == 1


def test_a_step_only_ever_holds_one_of_the_four_statuses(state):
    wf = workflow.create(state, _read_save_send(), title="statuses")
    assert [s["status"] for s in state.steps_for(wf)] == ["pending", "pending", "pending"]
    workflow.resume(state, wf, PRINCIPALS, POLICIES)
    assert [s["status"] for s in state.steps_for(wf)] == ["done", "done", "done"]
    with pytest.raises(ValueError):
        state.set_step(wf, 0, "skipped")


def test_blocked_steps_never_call_a_tool(state, tmp_path):
    rules = _rulebook(tmp_path)
    _edit_rule(rules, "SEND-ANALYST", max_classification="PUBLIC")
    steps = _read_save_send()
    steps.append(ActionRequest(actor_id="analyst", tool="deliver_inbox", resource_id="$1",
                               recipient="manager@corp.example"))
    wf = workflow.create(state, steps, title="summarise, then try to send")

    report = workflow.resume(state, wf, PRINCIPALS, rules)

    assert [s["status"] for s in state.steps_for(wf)] == ["done", "done", "blocked", "halted"]
    assert report["status"] == "halted"
    assert report["steps"][2]["rule_id"] == "RULE-ACTOR-CANNOT-RELEASE"
    assert [e.split(":")[0] for e in tools.EXECUTIONS] == ["read_document", "save_report"]
    assert state.list_outbox() == []
    assert len(state.list_artifacts()) == 1


# -- the rulebook changed while the app was closed --------------------------


def test_a_rule_tightened_on_disk_blocks_the_pending_step(state, tmp_path, monkeypatch):
    rules = _rulebook(tmp_path)
    old_fingerprint = load_policy_set(PRINCIPALS, rules).fingerprint
    wf = workflow.create(state, _read_save_send(), title="read, summarise, deliver")

    switch = _crash_at_step(monkeypatch, 0, before_write=False)
    with pytest.raises(RuntimeError):
        workflow.resume(state, wf, PRINCIPALS, rules)
    switch["armed"] = False
    assert [s["status"] for s in state.steps_for(wf)] == ["done", "pending", "pending"]

    new_fingerprint = _edit_rule(rules, "SAVE-ANALYST", max_classification="PUBLIC")

    report = workflow.resume(state, wf, PRINCIPALS, rules)
    assert report["status"] == "halted"
    assert [s["status"] for s in state.steps_for(wf)] == ["done", "blocked", "halted"]
    assert report["steps"][0]["rule_id"] == "RULE-SOURCE-TOO-SENSITIVE"
    assert report["policy_fingerprint"] == new_fingerprint != old_fingerprint

    assert [(r["step_index"], bool(r["allowed"]), r["policy_hash"]) for r in _audit(state, wf)] == [
        (0, True, old_fingerprint), (1, False, new_fingerprint)]
    assert state.list_outbox() == []
    assert not any(e.startswith("deliver_inbox") for e in tools.EXECUTIONS)


def test_the_same_step_is_blocked_then_allowed_under_two_fingerprints(state, tmp_path):
    rules = _rulebook(tmp_path)
    tight = _edit_rule(rules, "READ-ANALYST", max_classification="PUBLIC")
    wf = workflow.create(state, _read_save_send(), title="read, summarise, deliver")

    first = workflow.resume(state, wf, PRINCIPALS, rules)
    assert first["status"] == "halted"
    assert [s["status"] for s in state.steps_for(wf)] == ["blocked", "halted", "halted"]
    assert first["steps"][0]["rule_id"] == "RULE-READ-CLEARANCE"
    assert state.list_artifacts() == [] and state.list_outbox() == []

    loose = _edit_rule(rules, "READ-ANALYST", max_classification="CONFIDENTIAL")

    second = workflow.resume(state, wf, PRINCIPALS, rules)
    assert second["status"] == "completed"
    assert [s["status"] for s in state.steps_for(wf)] == ["done", "done", "done"]

    rows = _audit(state, wf, 0)
    assert [(bool(r["allowed"]), r["policy_hash"]) for r in rows] == [
        (False, tight), (True, loose)]
    assert len(state.list_outbox()) == 1


# -- a real restart, and a crash mid-step ----------------------------------


def test_resuming_after_reopening_the_database_still_enforces_labels_and_policy(tmp_path):
    db = tmp_path / "resume.sqlite"
    first_process = Store(db)
    first_process.load_documents_from_dir(DOCS)
    wf = workflow.create(first_process,
                         _read_save_send("agent-assistant", "doc-002", "team@corp.example"),
                         title="agent tries to send outside its list")

    report = workflow.resume(first_process, wf, PRINCIPALS, POLICIES)
    assert [s["status"] for s in report["steps"]] == ["done", "done", "blocked"]
    assert report["steps"][2]["rule_id"] == "RULE-RECIPIENT-NOT-PERMITTED"
    artifact_id = first_process.steps_for(wf)[1]["output"]
    assert first_process.get_artifact(artifact_id).label.classification == "PUBLIC"
    assert first_process.list_outbox() == []
    first_process.close()

    tools.reset_executions()
    second_process = Store(db)
    assert second_process.get_artifact(artifact_id).label.provenance == ["doc-002"]

    resumed = workflow.resume(second_process, wf, PRINCIPALS, POLICIES)
    assert resumed["status"] == "halted"
    assert tools.EXECUTIONS == []
    assert second_process.list_outbox() == []
    assert [bool(r["allowed"]) for r in _audit(second_process, wf, 2)] == [False, False]

    follow_up = workflow.create(second_process, [
        ActionRequest(actor_id="agent-assistant", tool="deliver_inbox",
                      resource_id=artifact_id, recipient="team@corp.example")])
    fresh = workflow.resume(second_process, follow_up, PRINCIPALS, POLICIES)
    assert fresh["steps"][0]["rule_id"] == "RULE-RECIPIENT-NOT-PERMITTED"
    assert second_process.list_outbox() == []
    second_process.close()


def test_read_history_survives_the_restart_and_still_taints_a_report(tmp_path):
    db = tmp_path / "taint.sqlite"
    first = Store(db)
    first.load_documents_from_dir(DOCS)
    read = workflow.create(first, [
        ActionRequest(actor_id="analyst", tool="read_document", resource_id="doc-001")])
    assert workflow.resume(first, read, PRINCIPALS, POLICIES)["status"] == "completed"
    first.close()

    second = Store(db)
    hidden = workflow.create(second, [
        ActionRequest(actor_id="analyst", tool="save_report", source_ids=["doc-002"])])
    assert workflow.resume(second, hidden, PRINCIPALS, POLICIES)["status"] == "completed"
    artifact_id = second.steps_for(hidden)[0]["output"]
    label = second.get_artifact(artifact_id).label
    assert label.classification == "CONFIDENTIAL"
    assert set(label.provenance) == {"doc-001", "doc-002"}
    second.close()


def test_a_crash_between_execute_and_status_write_does_not_deliver_twice(state, monkeypatch):
    wf = workflow.create(state, _read_save_send(), title="read, summarise, deliver")

    switch = _crash_at_step(monkeypatch, 2, before_write=True)
    with pytest.raises(RuntimeError):
        workflow.resume(state, wf, PRINCIPALS, POLICIES)

    assert [s["status"] for s in state.steps_for(wf)] == ["done", "done", "pending"]
    assert len(state.list_outbox()) == 1
    switch["armed"] = False

    report = workflow.resume(state, wf, PRINCIPALS, POLICIES)
    assert report["status"] == "completed"
    assert len(state.list_outbox()) == 1
    assert state.list_outbox()[0]["effect_key"] == f"{wf}:2"
    assert [r["step_index"] for r in _audit(state, wf)] == [0, 1, 2, 2]
