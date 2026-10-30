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
                   reason="Live finding in team/makhdum/REPORT-2.md, kept rather than softened. "
                          "Delete the marker for an attack that starts passing, and say so in the "
                          "report.")
def test_live_finding_is_still_open(arena, name):
    result = RUNNERS[name](arena)
    assert result.safe, f"{name}: {result.detail}"


def test_the_harness_is_big_enough_and_every_attack_is_named():
    assert len(ATTACKS) >= 12
    assert len(RUNNERS) == len(ATTACKS)
    for attack in ATTACKS:
        assert attack.__doc__, f"{attack.__name__} has no stated attack"


def test_the_repository_rulebook_was_never_touched():
    assert fingerprint(PRINCIPALS, POLICIES) == RULEBOOK_AT_IMPORT
