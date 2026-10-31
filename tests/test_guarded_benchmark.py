"""The frozen 32-row table has to survive the policy guard, not just a guardless gateway.

`benchmark/runner.py` builds its sessions without a `Guard`, so "32/32" on its own describes the
gateway as it was before Task 2. This replays every scenario with the guard attached to the
registry and to `declassify`, and requires the same verdict and the same rule id as the committed
table. It then breaks the arrangement on purpose — mutating the rulebook right after the pin — to
prove the guard is genuinely in that path and not silently absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import benchmark.runner as runner
from agentgate.policy_guard import Guard
from agentgate.sessions import SessionRegistry

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = json.loads((ROOT / "benchmark" / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
COMMITTED = json.loads((ROOT / "benchmark" / "results.json").read_text(encoding="utf-8"))
IDS = [scenario["id"] for scenario in SCENARIOS]


def _attach_guard(monkeypatch, drift_after_pin: bool = False) -> list:
    """Wrap the runner's own construction points so every session carries a Guard."""
    loaded: list[tuple[Path, Path]] = []
    real_load = runner.load_policy_set
    real_registry = runner.SessionRegistry
    real_declassify = runner.declassify

    def load(principals, policies):
        loaded.append((Path(principals), Path(policies)))
        return real_load(principals, policies)

    def registry(state, policies):
        principals, policies_file = loaded[-1]
        guard = Guard(principals, policies_file)
        if drift_after_pin:  # someone edits the rulebook after this session pinned it
            policies_file.write_text(policies_file.read_text(encoding="utf-8") + "\n",
                                      encoding="utf-8")
        return real_registry(state, policies, guard)

    def declassify(state, policies, officer, artifact, target, justification=""):
        principals, policies_file = loaded[-1]
        return real_declassify(state, policies, officer, artifact, target, justification,
                               Guard(principals, policies_file))

    monkeypatch.setattr(runner, "load_policy_set", load)
    monkeypatch.setattr(runner, "SessionRegistry", registry)
    monkeypatch.setattr(runner, "declassify", declassify)
    return loaded


@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_every_scenario_still_matches_its_frozen_row(scenario, monkeypatch):
    loaded = _attach_guard(monkeypatch)
    row = runner.run_scenario(scenario)

    assert loaded, "the replay never pinned a rulebook, so no guard was attached"
    assert row["scenario_ok"], f"{row['id']} {row['title']}: {row['actual']} vs {row['expected']}"
    assert row["audit_complete"], f"{row['id']} left an incomplete audit row"
    if not row["actual"]["allowed"]:
        assert row["executions"] == 0, f"{row['id']} blocked a step but ran a tool"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_the_guarded_verdicts_equal_the_committed_table(scenario, monkeypatch):
    _attach_guard(monkeypatch)
    committed = {row["id"]: row for row in COMMITTED["rows"]}[scenario["id"]]
    row = runner.run_scenario(scenario)
    assert row["actual"]["allowed"] == committed["actual"]["allowed"]
    assert row["actual"]["rule"] == committed["actual"]["rule"]


def test_the_guard_is_actually_in_this_path(monkeypatch):
    """Positive control: pin, then move the rulebook. Every action must now be refused for drift."""
    _attach_guard(monkeypatch, drift_after_pin=True)
    scenario = SCENARIOS[0]
    row = runner.run_scenario(scenario)

    assert row["actual"]["allowed"] is False
    assert row["actual"]["rule"] == "RULE-POLICY-DRIFT"
    assert row["executions"] == 0, "a drifted rulebook still executed a tool"
    assert not row["scenario_ok"], "the frozen row must NOT match when the rulebook drifted"


def test_the_committed_table_is_what_a_guardless_run_produces():
    """Sanity for the two tests above: the committed rows came from this code, unmodified."""
    report = runner.run_suite(results_path=None)
    assert report["metrics"] == COMMITTED["metrics"]
    assert report["metrics"]["scenario_matches"] == report["metrics"]["scenarios"] == 32
