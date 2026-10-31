"""The web page has to be computed, not painted.

Aryans's first cut was a static mockup: hardcoded demo rows, and counters that added constants
(`+ 7`, `128 + events.length - 4`) to look busy. These tests drive the real gateway and then require
the page to say exactly what the database says — including zeros when there is no database at all.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agentgate.gateway import Session
from agentgate.models import ActionRequest
from agentgate.policy import load_policy_set
from agentgate.store import Store
from web.app import app, snapshot

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def empty_world(tmp_path, monkeypatch):
    """A data directory with the real rulebook and no database yet."""
    data = tmp_path / "empty"
    data.mkdir()
    shutil.copy(ROOT / "data" / "principals.json", data / "principals.json")
    shutil.copy(ROOT / "data" / "policies.json", data / "policies.json")
    monkeypatch.setenv("AGENTGATE_DATA_DIR", str(data))
    app.config["TESTING"] = True
    return app.test_client(), data


@pytest.fixture()
def live_world(tmp_path, monkeypatch):
    """A seeded demo world, the same one `demo/seed.py` builds."""
    import importlib.util

    data = tmp_path / "live"
    data.mkdir()
    shutil.copytree(ROOT / "data" / "documents", data / "documents")
    shutil.copy(ROOT / "data" / "principals.json", data / "principals.json")
    shutil.copy(ROOT / "data" / "policies.json", data / "policies.json")

    spec = importlib.util.spec_from_file_location("seed_for_web", ROOT / "demo" / "seed.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    seeded = seed.seed(data)

    monkeypatch.setenv("AGENTGATE_DATA_DIR", str(data))
    app.config["TESTING"] = True
    return app.test_client(), data, seeded


def _drive(data: Path) -> None:
    """Two real decisions: one allowed read, one delivery the policy refuses."""
    policies = load_policy_set(data / "principals.json", data / "policies.json")
    store = Store(data / "agentgate-v3.sqlite")
    try:
        Session(store, policies, "analyst", "human").submit(
            ActionRequest(tool="read_document", resource_id="doc-001"))
        decision, artifact = Session(store, policies, "analyst", "human").submit(
            ActionRequest(tool="save_report", source_ids=["doc-001"]))
        assert decision.allowed
        Session(store, policies, "analyst", "human").submit(
            ActionRequest(tool="deliver_inbox", resource_id=artifact,
                          recipient="vendor@outside.example"))
    finally:
        store.close()


def test_an_empty_world_renders_zeros_not_demo_data(empty_world):
    client, _ = empty_world
    html = client.get("/").get_data(as_text=True)
    assert "no database yet" in html
    assert "0 decisions" in html

    payload = client.get("/api/snapshot").json
    assert payload["meta"]["live"] is False
    assert payload["counts"]["decisions"] == 0
    assert payload["counts"]["delivered"] == 0
    assert payload["counts"]["pending_steps"] == 0
    assert payload["events"] == [] and payload["workflows"] == []


def test_the_demo_arithmetic_is_gone(empty_world):
    client, _ = empty_world
    template = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "+ 7" not in template and "128 + events.length" not in template
    assert "EVT-0091" not in client.get("/").get_data(as_text=True)


def test_the_page_says_exactly_what_the_database_says(live_world):
    client, data, _ = live_world

    before = client.get("/api/snapshot").json
    assert before["meta"]["live"] is True
    assert before["counts"]["decisions"] == 1, "the seeder leaves exactly one audit row"
    assert before["counts"]["pending_steps"] == 6, "two workflows, three pending steps each"

    _drive(data)

    payload = client.get("/api/snapshot").json
    store = Store(data / "agentgate-v3.sqlite")
    try:
        audit = store.list_audit()
        outbox = store.list_outbox()
    finally:
        store.close()

    assert payload["counts"]["decisions"] == len(audit) == 4
    assert payload["counts"]["allowed"] == sum(1 for row in audit if row["allowed"]) == 3
    assert payload["counts"]["blocked"] == 1
    assert payload["counts"]["delivered"] == len(outbox) == 0
    assert payload["counts"]["pending_steps"] == 6

    html = client.get("/").get_data(as_text=True)
    fingerprint = load_policy_set(data / "principals.json", data / "policies.json").fingerprint
    assert fingerprint in html, "the page must show the rulebook it is reading"
    assert "4 decisions" in html and "1 blocked" in html
    assert "RULE-RECIPIENT-NOT-PERMITTED" in html or "never reached the inbox" in html


def test_events_carry_the_real_rule_and_reason(live_world):
    client, data, _ = live_world
    _drive(data)
    events = client.get("/api/snapshot").json["events"]
    assert len(events) == 4
    blocked = [event for event in events if event["decision"] == "Blocked"]
    assert len(blocked) == 1
    assert "vendor@outside.example" in blocked[0]["reason"]
    assert all(event["id"].startswith("EVT-") and event["time"] for event in events)


def test_workflows_and_pending_steps_come_from_the_store(live_world):
    client, _, seeded = live_world
    payload = client.get("/api/snapshot").json
    ids = {item["id"] for item in payload["workflows"]}
    assert ids == set(seeded["staged"]["workflows"].values())
    assert all(item["status"] == "In progress" for item in payload["workflows"])
    assert all(item["checkpoint"].startswith("Step 0 of 3") for item in payload["workflows"])
    assert len(payload["approvals"]) == 6


def test_the_evidence_numbers_come_from_the_published_artifacts(live_world):
    client, _, _ = live_world
    payload = client.get("/api/snapshot").json
    committed = json.loads((ROOT / "benchmark" / "results.json").read_text(encoding="utf-8"))
    assert payload["evidence"]["benchmark"] == committed["metrics"]
    assert payload["evidence"]["redteam"]["attacks"] >= 12


def test_the_page_cannot_act(live_world):
    """Read-only by construction: no POST route exists to approve, resume or execute."""
    client, _, _ = live_world
    for route in ("/", "/api/snapshot"):
        assert client.post(route).status_code == 405
    template = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "READ-ONLY" in template
    assert "readOnly(" in template


def test_snapshot_is_pure_read(live_world):
    """Rendering the page twice must not write a single row."""
    client, data, _ = live_world
    store = Store(data / "agentgate-v3.sqlite")
    try:
        before = (len(store.list_audit()), len(store.list_outbox()), len(store.list_artifacts()))
    finally:
        store.close()
    client.get("/")
    client.get("/api/snapshot")
    snapshot(data)
    store = Store(data / "agentgate-v3.sqlite")
    try:
        after = (len(store.list_audit()), len(store.list_outbox()), len(store.list_artifacts()))
    finally:
        store.close()
    assert before == after
