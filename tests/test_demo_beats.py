"""One test per beat in docs/DEMO_SCRIPT.md, driven through the real dashboard.

Each test seeds a scratch copy of `data/`, opens `app.py` with Streamlit's own AppTest, clicks
the widgets the script says to click, and asserts the exact text on screen: the verdict banner,
the rule id, the inherited classification, the delivered count and the step statuses. A beat
that does not render is a beat that does not exist, so nothing here is asserted against a
re-implementation of the page.

The beat numbers in the test names are the beat numbers in the script. Beats that come later
reproduce the clicks of the beats before them, because the order is load-bearing: read history
accumulates, the rulebook swap breaks the earlier save beat, and the delivered count is only
zero until the permitted workflow has run.

`demo/seed.py` and `demo/swap_policy.py` are exercised here too, so the seed report the run
sheet tells you to trust is the one the script actually checks.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agentgate import tools
from agentgate.policy import load_policy_set
from agentgate.store import Store

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app.py"
EM = "—"  # the dash app.py puts between a verdict and its rule id

DEFAULT_RULEBOOK = load_policy_set(ROOT / "data" / "principals.json",
                                   ROOT / "demo" / "policies_default.json").fingerprint
TIGHT_RULEBOOK = load_policy_set(ROOT / "data" / "principals.json",
                                 ROOT / "demo" / "policies_tight.json").fingerprint


def _demo_module(name: str):
    """Import demo/seed.py or demo/swap_policy.py by path."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "demo" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Dashboard:
    """Clicks the way a presenter does, then reads the page back."""

    def __init__(self, data: Path, seeded: dict):
        self.data = data
        self.seeded = seeded
        self.at = AppTest.from_file(str(APP), default_timeout=120)
        self.at.run()
        self._assert_clean()

    @property
    def db(self) -> Path:
        return self.data / "agentgate-v3.sqlite"

    def _assert_clean(self) -> None:
        """Streamlit renders a script crash as an exception element; that is a failed beat."""
        crashes = [e.value for e in self.at.exception]
        assert crashes == [], crashes

    def rerun(self) -> "Dashboard":
        """Stand-in for 'click any widget': re-renders and re-reads the rulebook."""
        self.at.run()
        self._assert_clean()
        return self

    def widget(self, label: str):
        for group in ("selectbox", "multiselect", "radio", "text_area"):
            found = [w for w in getattr(self.at, group) if w.label == label]
            if found:
                return found[0]
        raise AssertionError(f"nothing on screen labelled {label!r}")

    def choose(self, label: str, value) -> "Dashboard":
        box = self.widget(label)
        box.set_value(value)
        box.run()
        self._assert_clean()
        return self

    def click(self, label: str) -> "Dashboard":
        next(b for b in self.at.button if b.label == label).click().run()
        self._assert_clean()
        return self

    def screen(self) -> str:
        """Every string the page renders."""
        parts: list[str] = []
        for group in ("title", "header", "subheader", "caption", "markdown", "text",
                      "success", "error", "info", "warning", "json", "metric"):
            parts += [str(element.value) for element in getattr(self.at, group)]
        return "\n".join(parts)

    def verdict(self) -> str:
        """The ALLOWED / BLOCKED banner in section 2, printed exactly as the page says it."""
        banners = [str(e.value) for e in list(self.at.success) + list(self.at.error)]
        hits = [b for b in banners if b.startswith(("ALLOWED", "BLOCKED before"))]
        assert hits, f"no verdict banner on screen, banners were {banners}"
        return hits[0]

    def delivered(self) -> int:
        """The number printed under the mock inbox, read off the screen."""
        match = re.search(r"Messages actually delivered:\D*?(\d+)", self.screen())
        assert match, "the delivered count is not on screen"
        return int(match.group(1))

    def tool_counter(self) -> int:
        match = re.search(r"Tool executions recorded in this process: (\d+)", self.screen())
        assert match, "the tool counter is not on screen"
        return int(match.group(1))

    def labels(self) -> list[dict]:
        return [json.loads(str(j.value)) for j in self.at.json]

    def audit_rows(self) -> list[dict]:
        return self.at.dataframe[0].value.to_dict("records")

    def step_rows(self) -> list[dict]:
        return self.at.dataframe[1].value.to_dict("records")

    def step_statuses(self, which: str) -> list[str]:
        state = Store(self.db)
        statuses = [s["status"] for s in
                    state.steps_for(self.seeded["staged"]["workflows"][which])]
        state.close()
        return statuses

    def verdicts_for_step(self, which: str, idx: int) -> list[tuple[bool, str]]:
        state = Store(self.db)
        rows = state.conn.execute(
            "SELECT allowed, policy_hash FROM audit WHERE workflow_id=? AND step_index=?"
            " ORDER BY id", (self.seeded["staged"]["workflows"][which], idx)).fetchall()
        state.close()
        return [(bool(r["allowed"]), r["policy_hash"]) for r in rows]

    def staged_id(self, which: str) -> str:
        return self.seeded["staged"]["workflows"][which]


@pytest.fixture()
def stage(tmp_path, monkeypatch) -> Dashboard:
    data = tmp_path / "data"
    shutil.copytree(ROOT / "data", data, ignore=shutil.ignore_patterns("*.sqlite"))
    monkeypatch.setenv("AGENTGATE_DATA_DIR", str(data))
    seeded = _demo_module("seed").seed(data)
    tools.reset_executions()
    return Dashboard(data, seeded)


# -- the click sequences the script tells the presenter to perform ----------


def beat_authorized_read(dash: Dashboard) -> Dashboard:
    return (dash.choose("Actor", "analyst")
            .choose("Tool", "read_document")
            .choose("Proposal came from", "human")
            .choose("Document", "doc-001")
            .click("Submit to gateway"))


def beat_inherit_label(dash: Dashboard) -> Dashboard:
    return (dash.choose("Tool", "save_report")
            .choose("Source documents", ["doc-001", "doc-002"])
            .click("Submit to gateway"))


def beat_block_outside(dash: Dashboard) -> Dashboard:
    return (dash.choose("Tool", "deliver_inbox")
            .choose("Recipient", "vendor@outside.example")
            .click("Submit to gateway"))


def beat_obey_injection(dash: Dashboard) -> Dashboard:
    return (dash.choose("Actor", "agent-assistant")
            .choose("Tool", "read_document")
            .choose("Proposal came from", "agent (AI)")
            .choose("Document", "doc-003")
            .click("Submit to gateway"))


def beat_resume(dash: Dashboard, which: str) -> Dashboard:
    return dash.choose("Saved workflow", dash.staged_id(which)).click("Resume")


def swap(dash: Dashboard, mode: str) -> None:
    """The pre-staged file swap, then the click that lets it land."""
    before, after = _demo_module("swap_policy").swap(mode)
    expected = TIGHT_RULEBOOK if mode == "tighten" else DEFAULT_RULEBOOK
    assert before != after, "the swap left the rulebook fingerprint unchanged"
    assert after == expected
    dash.rerun()


# -- beat 0: what demo/seed.py owes the script ------------------------------


def test_beat_0_seed_leaves_the_page_one_click_from_beat_one(stage: Dashboard):
    assert [(s.label, s.value) for s in stage.at.selectbox][:3] == [
        ("Actor", "analyst"), ("Tool", "read_document"), ("Document", "doc-001")]
    assert [r.value for r in stage.at.radio] == ["human"]
    assert "Submit an action to see the decision." in stage.screen()
    assert stage.delivered() == 0
    assert stage.tool_counter() == 0
    assert f"policy fingerprint `{DEFAULT_RULEBOOK}`" in stage.screen()
    assert "Staged for this demo" in stage.screen(), "the prefilled justification must be labelled"
    assert "no longer needs CONFIDENTIAL handling" in stage.widget("Written justification").value


# -- beats 1 to 4: allow, inherit, block, ignore the text -------------------


def test_beat_1_authorized_read_is_allowed_by_its_rule(stage: Dashboard):
    beat_authorized_read(stage)
    assert stage.verdict() == f"ALLOWED {EM} rule READ-ANALYST"
    assert stage.tool_counter() == 1
    assert stage.delivered() == 0


def test_beat_2_report_inherits_the_highest_label_and_keeps_provenance(stage: Dashboard):
    beat_authorized_read(stage)
    beat_inherit_label(stage)
    assert stage.verdict() == f"ALLOWED {EM} rule SAVE-ANALYST"
    assert stage.labels()[-1] == {"classification": "CONFIDENTIAL",
                                  "provenance": ["doc-001", "doc-002"],
                                  "tags": ["owner:finance", "owner:facilities"]}
    assert "Effective sources after read history: doc-001, doc-002" in stage.screen()
    assert stage.tool_counter() == 2


def test_beat_3_sending_outside_is_blocked_before_any_tool_runs(stage: Dashboard):
    beat_authorized_read(stage)
    beat_inherit_label(stage)
    before = len(tools.EXECUTIONS)
    beat_block_outside(stage)

    assert stage.verdict() == f"BLOCKED before execution {EM} rule RULE-RECIPIENT-NOT-PERMITTED"
    assert "No tool was invoked." in stage.screen()
    assert stage.delivered() == 0
    assert stage.tool_counter() == 2
    assert len(tools.EXECUTIONS) == before, "a blocked action executed a tool"

    newest = stage.audit_rows()[0]
    assert (newest["allowed"], newest["rule_id"]) == ("BLOCKED", "RULE-RECIPIENT-NOT-PERMITTED")
    reason = next(str(m.value) for m in stage.at.markdown if str(m.value).startswith("Blocked"))
    for leak in ("Q3 Revenue Summary", "Cafeteria Menu", "Vendor Contract"):
        assert leak not in reason, "the denial named the thing it protects"


def test_beat_4_document_text_cannot_change_the_outcome(stage: Dashboard):
    """doc-003 orders the agent to forward to the vendor; policy never reads that text."""
    beat_obey_injection(stage)
    assert stage.verdict() == f"BLOCKED before execution {EM} rule RULE-READ-CLEARANCE"
    reason = next(str(m.value) for m in stage.at.markdown if str(m.value).startswith("Blocked"))
    assert "The text was never opened." in reason
    for leak in ("ignore all previous policy", "vendor@outside.example", "SYSTEM DIRECTIVE"):
        assert leak not in reason, "the decision echoed document text"
    assert tools.EXECUTIONS == [], "the injected instruction must not reach a tool"


# -- beats 5 and 6: release is an officer action, not a tool ----------------


def test_beat_5_a_non_officer_release_is_refused_and_audited(stage: Dashboard):
    beat_inherit_label(stage)
    stage.click("Release")
    assert "Refused: not a security officer." in stage.screen()
    assert stage.audit_rows()[0]["rule_id"] == "RULE-DECLASSIFY-ROLE"
    state = Store(stage.db)
    count = len(state.list_artifacts())
    state.close()
    assert count == 2, "a refused release must not create a report"


def test_beat_6_officer_release_creates_a_linked_copy(stage: Dashboard):
    beat_inherit_label(stage)
    state = Store(stage.db)
    newest = state.list_artifacts()[0].id
    state.close()
    assert stage.widget("Report to release").value == newest

    stage.choose("Actor", "security-officer").click("Release")
    created = re.search(r"Created (report-\w+) at PUBLIC\. Original untouched\.", stage.screen())
    assert created, "the released copy is not on screen"

    state = Store(stage.db)
    child, parent = state.get_artifact(created.group(1)), state.get_artifact(newest)
    state.close()
    assert child.label.classification == "PUBLIC"
    assert parent.id in child.label.provenance
    assert "declassified-by:security-officer" in child.label.tags
    assert parent.label.classification == "CONFIDENTIAL", "the original was edited"


# -- beats 7 to 11: a saved workflow is a list of proposals -----------------


def test_beat_7_permitted_workflow_runs_to_completion(stage: Dashboard):
    beat_resume(stage, "run")
    assert f"Ran to completion under `{DEFAULT_RULEBOOK}`" in stage.screen()
    assert stage.step_statuses("run") == ["done", "done", "done"]
    assert [r["Status"] for r in stage.step_rows()] == ["done", "done", "done"]
    assert stage.delivered() == 1
    assert stage.tool_counter() == 3


def test_beat_8_swap_lands_on_the_next_click_without_re_deciding_anything(
        stage: Dashboard):
    beat_resume(stage, "run")
    pending_before = stage.step_statuses("tight")
    executed = len(tools.EXECUTIONS)
    swap(stage, "tighten")

    assert f"policy fingerprint `{TIGHT_RULEBOOK}`" in stage.screen()
    assert f"Rulebook on disk right now: `{TIGHT_RULEBOOK}`" in stage.screen()
    assert stage.step_statuses("tight") == pending_before == ["pending", "pending", "pending"]
    assert stage.delivered() == 1, "swapping the rulebook must not run or block anything itself"
    assert len(tools.EXECUTIONS) == executed, "the swap itself executed a tool"


def test_beat_9_resumption_blocks_the_step_the_old_rulebook_passed(stage: Dashboard):
    beat_resume(stage, "run")
    swap(stage, "tighten")
    before = len(tools.EXECUTIONS)
    beat_resume(stage, "tight")

    assert f"Stopped at the first block under `{TIGHT_RULEBOOK}`" in stage.screen()
    assert stage.step_statuses("tight") == ["done", "blocked", "halted"]
    assert [r["Status"] for r in stage.step_rows()] == ["done", "blocked", "halted"]
    assert stage.delivered() == 1, "a blocked delivery must not reach the inbox"
    assert not [e for e in tools.EXECUTIONS[before:] if e.startswith("deliver_inbox")]

    rows = stage.audit_rows()
    assert rows[0]["rule_id"] == "RULE-SOURCE-TOO-SENSITIVE"
    assert rows[0]["allowed"] == "BLOCKED"
    assert rows[0]["policy_hash"] == TIGHT_RULEBOOK
    assert rows[1]["rule_id"] == "READ-ANALYST"
    assert rows[1]["policy_hash"] == TIGHT_RULEBOOK


def test_beat_10_restore_lets_the_same_step_pass_and_the_audit_keeps_both(
        stage: Dashboard):
    """The step blocked under the tightened rulebook passes again once it is undone."""
    beat_resume(stage, "run")
    swap(stage, "tighten")
    beat_resume(stage, "tight")
    assert stage.verdicts_for_step("tight", 1) == [(False, TIGHT_RULEBOOK)]

    swap(stage, "restore")
    beat_resume(stage, "tight")
    assert f"Ran to completion under `{DEFAULT_RULEBOOK}`" in stage.screen()
    assert stage.step_statuses("tight") == ["done", "done", "done"]
    assert stage.verdicts_for_step("tight", 1) == [(False, TIGHT_RULEBOOK),
                                                   (True, DEFAULT_RULEBOOK)]
    assert stage.delivered() == 2

    on_screen = {(r["allowed"], r["rule_id"], r["policy_hash"]) for r in stage.audit_rows()}
    assert ("BLOCKED", "RULE-SOURCE-TOO-SENSITIVE", TIGHT_RULEBOOK) in on_screen
    assert ("ALLOWED", "SAVE-ANALYST", DEFAULT_RULEBOOK) in on_screen


def test_beat_11_resuming_a_finished_workflow_re_runs_nothing(stage: Dashboard):
    beat_resume(stage, "run")
    assert stage.delivered() == 1
    beat_resume(stage, "run")
    assert "Nothing was re-run" in stage.screen()
    assert stage.step_statuses("run") == ["done", "done", "done"]
    assert stage.delivered() == 1, "a retried step must not deliver twice"


# -- beat 12: the evidence panel --------------------------------------------


def test_beat_12_evidence_panel_shows_the_frozen_suite(stage: Dashboard):
    """Panel text vs the committed table, and a live re-run with the write suppressed.

    The button itself is not clicked here on purpose: `run_suite()` on its default path
    rewrites `benchmark/results.json`, and that table is frozen. The beat asserts the numbers
    printed from the committed file, that the button is on screen, and that the same function
    the button calls reproduces those numbers exactly.
    """
    from benchmark.runner import run_suite

    committed = json.loads((ROOT / "benchmark" / "results.json").read_text(encoding="utf-8"))
    expected = committed["metrics"]
    assert {m.label: str(m.value) for m in stage.at.metric} == {
        "Scenarios matched": f"{expected['scenario_matches']}/{expected['scenarios']}",
        "Unauthorized executions": str(expected["unauthorized_executions"]),
        "False allows / false denies": f"{expected['false_allows']} / {expected['false_denies']}",
        "Decisions with a complete audit row":
            f"{expected['audit_complete']}/{expected['scenarios']}",
    }
    assert "All 32 scenarios matched their frozen expectations." in stage.screen()
    assert "Run the suite" in [b.label for b in stage.at.button]

    live = run_suite(results_path=None)
    assert live["metrics"] == expected, "a live run must reproduce the panel"
    assert expected["unauthorized_executions"] == 0 and expected["false_allows"] == 0


# -- the honesty of the staged swap -----------------------------------------


def test_staged_rulebook_swap_changes_exactly_one_value():
    default = json.loads((ROOT / "demo" / "policies_default.json").read_text(encoding="utf-8"))
    live = json.loads((ROOT / "data" / "policies.json").read_text(encoding="utf-8"))
    tight = json.loads((ROOT / "demo" / "policies_tight.json").read_text(encoding="utf-8"))

    assert default == live, "the restore source must match the committed rulebook"
    assert [r["id"] for r in tight] == [r["id"] for r in default]
    changed = [a["id"] for a, b in zip(tight, default) if a != b]
    assert changed == ["SAVE-ANALYST"], f"expected one rule to differ, got {changed}"
    assert tight[1]["max_classification"] == "PUBLIC"
    assert "DEMO CHANGE" in tight[1]["description"], "the swap must say what it changed"


# -- full rehearsals: the order the script tells you to click in -------------
#
# These two are the real proof. The per-beat tests above each start from the seeded state and
# re-do only the clicks their own beat needs; these follow docs/DEMO_SCRIPT.md from the first
# click to the last with nothing skipped and nothing reordered, so a beat that quietly spoils a
# later one fails here. It already earned that: the analyst's read history from beat 1 pushes
# every later report to CONFIDENTIAL, which is what forced the workflow recipient to
# manager@corp.example.


def test_rehearsal_sixty_second_cut_clicks_through_in_order(stage: Dashboard):
    """Script beats 1, 2, 3, 4, 7, 8, 9, 12 in that order."""
    beat_authorized_read(stage)
    assert stage.verdict() == f"ALLOWED {EM} rule READ-ANALYST"
    assert stage.tool_counter() == 1

    beat_inherit_label(stage)
    assert stage.verdict() == f"ALLOWED {EM} rule SAVE-ANALYST"
    assert stage.labels()[-1]["classification"] == "CONFIDENTIAL"

    beat_block_outside(stage)
    assert stage.verdict() == (f"BLOCKED before execution {EM} "
                               "rule RULE-RECIPIENT-NOT-PERMITTED")
    assert stage.delivered() == 0

    beat_obey_injection(stage)
    assert stage.verdict() == f"BLOCKED before execution {EM} rule RULE-READ-CLEARANCE"

    beat_resume(stage, "run")
    assert f"Ran to completion under `{DEFAULT_RULEBOOK}`" in stage.screen()
    assert stage.delivered() == 1

    swap(stage, "tighten")
    assert stage.step_statuses("tight") == ["pending", "pending", "pending"]

    beat_resume(stage, "tight")
    assert f"Stopped at the first block under `{TIGHT_RULEBOOK}`" in stage.screen()
    assert stage.step_statuses("tight") == ["done", "blocked", "halted"]
    assert stage.delivered() == 1, "the block must have kept the message out of the inbox"
    assert stage.tool_counter() == 6, "read, save, three on the permitted run, one more read"


def test_rehearsal_extended_cut_clicks_through_in_order(stage: Dashboard):
    """Script beats 1 to 12 in that order, including the release pair and the restore."""
    beat_authorized_read(stage)
    beat_inherit_label(stage)
    beat_block_outside(stage)
    beat_obey_injection(stage)

    stage.choose("Actor", "analyst").click("Release")
    assert "Refused: not a security officer." in stage.screen()
    assert stage.audit_rows()[0]["rule_id"] == "RULE-DECLASSIFY-ROLE"

    stage.choose("Actor", "security-officer").click("Release")
    assert re.search(r"Created report-\w+ at PUBLIC\. Original untouched\.", stage.screen())

    beat_resume(stage, "run")
    assert stage.delivered() == 1

    swap(stage, "tighten")
    beat_resume(stage, "tight")
    assert stage.step_statuses("tight") == ["done", "blocked", "halted"]

    swap(stage, "restore")
    beat_resume(stage, "tight")
    assert f"Ran to completion under `{DEFAULT_RULEBOOK}`" in stage.screen()
    assert stage.verdicts_for_step("tight", 1) == [(False, TIGHT_RULEBOOK),
                                                   (True, DEFAULT_RULEBOOK)]
    assert stage.delivered() == 2

    beat_resume(stage, "run")
    assert "Nothing was re-run" in stage.screen()
    assert stage.delivered() == 2, "a finished workflow must not send a second message"

    assert str([m.value for m in stage.at.metric][0]) == "32/32"
