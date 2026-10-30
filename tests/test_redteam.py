"""Red-team runs: every named attack must be refused, or end in the safe outcome.

The arena copies `data/documents/`, the rulebook and its own SQLite file into a tmp
directory, so an attack can tamper with files without touching the repository. One test
asserts that promise: the repo's real rulebook hash is unchanged after the whole run.
"""

from __future__ import annotations

import pytest

from agentgate.policy_guard import fingerprint
from redteam.attacks import ATTACKS, LIVE_FINDINGS, POLICIES, PRINCIPALS, Arena

RUNNERS = {attack.__name__: attack for attack in ATTACKS}
RULEBOOK_AT_IMPORT = fingerprint(PRINCIPALS, POLICIES)


@pytest.fixture()
def arena(tmp_path):
    return Arena(tmp_path / "arena")


@pytest.mark.parametrize("name", [n for n in RUNNERS if n not in LIVE_FINDINGS])
def test_attack_is_refused_or_ends_safe(arena, name):
    result = RUNNERS[name](arena)
    assert result.safe, f"{name}: {result.detail}"


@pytest.mark.parametrize("name", LIVE_FINDINGS)
@pytest.mark.xfail(strict=True,
                   reason="Live finding LF-1 in team/makhdum/REPORT-2.md: workflow.resume builds a "
                          "guardless Session and re-reads disk, so a drifted rulebook is honoured "
                          "there with no RULE-POLICY-DRIFT denial. Delete this marker when the "
                          "resume path takes a guard.")
def test_live_finding_is_still_open(arena, name):
    result = RUNNERS[name](arena)
    assert result.safe, f"{name}: {result.detail}"


def test_the_harness_is_big_enough_and_every_attack_is_named():
    assert len(ATTACKS) >= 12
    assert len(RUNNERS) == len(ATTACKS)
    for attack in ATTACKS:
        assert attack.__doc__, f"{attack.__name__} has no stated attack"
        assert attack.__name__.startswith(("claim", "hide", "smuggle", "lower", "deliver", "read",
                                           "resume", "crash", "swap", "reload", "ask", "release",
                                           "act", "forge"))


def test_the_repository_rulebook_was_never_touched():
    assert fingerprint(PRINCIPALS, POLICIES) == RULEBOOK_AT_IMPORT
