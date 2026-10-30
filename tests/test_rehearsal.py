"""The stage rehearsal, as a test, so a demo-breaking change breaks the build.

The implementation is imported, not copied: `demo/rehearse.py` is the one runner, and this file
drives it exactly as the presenter does. A separate, weaker test implementation would pass while
the rehearsal on stage failed, which is the failure mode this file exists to rule out.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _rehearsal():
    name = "agentgate_rehearsal"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "demo" / "rehearse.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REHEARSE = _rehearsal()
LIVE_RULEBOOK = ROOT / "data" / "policies.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


RULEBOOK_AT_IMPORT = _sha(LIVE_RULEBOOK)


@pytest.fixture(scope="module")
def clean() -> object:
    """One full rehearsal for the whole module: it is the same run the presenter makes."""
    return REHEARSE.rehearse(cut="full")


@pytest.fixture()
def broken(tmp_path) -> object:
    """A full rehearsal against a scratch world with one required rule removed."""
    return REHEARSE.rehearse(cut="full", break_rule="SAVE-ANALYST", data=tmp_path / "broken")


# -- the clean run -------------------------------------------------------------


def test_the_full_cut_rehearses_green(clean):
    assert clean.error == ""
    assert clean.ok, REHEARSE.render(clean)
    scored = [beat for beat in clean.beats if beat.number]
    assert [beat.number for beat in scored] == list(range(1, 13))
    assert all(beat.found for beat in scored), REHEARSE.render(clean)
    assert clean.seconds < 90, f"rehearsal took {clean.seconds:.1f}s, the brief allows 90"


def test_every_beat_names_the_string_it_asserts(clean):
    scored = [beat for beat in clean.beats if beat.number]
    for beat in scored:
        assert beat.expected.strip(), f"beat {beat.number} asserts no promise"
        assert beat.driven_by, f"beat {beat.number} does not say what drove it"
        assert beat.seconds >= 0
    assert sum(beat.seconds for beat in scored) <= clean.seconds + 1.0


def test_the_script_claim_check_warns_instead_of_failing(clean):
    """A stale fingerprint in docs/DEMO_SCRIPT.md must be visible, not fatal and not silent."""
    claim = next(beat for beat in clean.beats if beat.number == 0)
    assert claim.found, "a documentation mismatch must not fail the rehearsal"
    if claim.warning:
        assert REHEARSE.DEFAULT_RULEBOOK in claim.warning
        assert "REPORT-3.md" in claim.detail
        assert clean.ok, "a script-claim warning must not stop the run"


def test_the_resumption_beat_reaches_the_blocked_state(clean):
    beat = next(beat for beat in clean.beats if beat.number == 9)
    assert beat.found, beat.detail
    assert clean.evidence["workflow_under_test"], "no workflow was under test"
    assert clean.evidence["delivered_after_block"] == 1, "the blocked step delivered anyway"


def test_the_audit_trail_holds_both_rulebooks_for_one_step(clean):
    """Not 'two hashes exist': one step, decided twice, by two known rulebooks."""
    assert REHEARSE.DEFAULT_RULEBOOK != REHEARSE.TIGHT_RULEBOOK
    assert clean.evidence["two_rulebooks"] == [
        (False, REHEARSE.TIGHT_RULEBOOK),
        (True, REHEARSE.DEFAULT_RULEBOOK),
    ]


def test_nothing_delivers_a_second_time_after_the_block(clean):
    assert clean.evidence["delivered_end"] == 2
    assert clean.evidence["delivered_after_noop"] == 2, "a finished workflow re-sent a message"


# -- the deliberate breakage ---------------------------------------------------


def test_a_missing_rule_fails_the_exact_beat(broken):
    assert not broken.ok, "the rehearsal passed against a rulebook missing a required rule"
    assert broken.error == "", "a misplaced rule is a beat failure, not a setup failure"
    assert broken.failed is not None
    assert broken.failed.number == 2, f"failed on beat {broken.failed.number}, expected 2"
    assert "RULE-NO-GRANT" in broken.failed.detail, broken.failed.detail
    assert "ALLOWED" in broken.failed.expected


def test_the_broken_run_leaves_the_repository_rulebook_alone(broken):
    assert broken.rulebook_before == broken.rulebook_after
    rules = json.loads(LIVE_RULEBOOK.read_text(encoding="utf-8"))
    assert "SAVE-ANALYST" in [rule["id"] for rule in rules], "the real rulebook was edited"


def test_a_rule_that_does_not_exist_is_a_setup_failure(tmp_path):
    run = REHEARSE.rehearse(break_rule="NO-SUCH-RULE", data=tmp_path / "no-such-rule")
    assert not run.ok
    assert run.error.startswith("setup failed"), run.error
    assert not [beat for beat in run.beats if beat.number], "no beat should have run"


def test_the_short_cut_runs_its_beats_in_script_order(tmp_path):
    run = REHEARSE.rehearse(cut="60", data=tmp_path / "short")
    assert run.ok, REHEARSE.render(run)
    assert [beat.number for beat in run.beats if beat.number] == [1, 2, 3, 4, 7, 8, 9, 12]


def test_the_repository_rulebook_is_untouched_by_the_whole_module():
    """Five rehearsals ran above, two of them against a deliberately broken rulebook."""
    assert _sha(LIVE_RULEBOOK) == RULEBOOK_AT_IMPORT
    rules = json.loads(LIVE_RULEBOOK.read_text(encoding="utf-8"))
    assert len(rules) == 8
