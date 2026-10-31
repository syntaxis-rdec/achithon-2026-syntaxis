"""Red-team runs: every named attack must be refused, or end in the safe outcome.

The arena copies `data/documents/`, the rulebook and its own SQLite file into a tmp
directory, so an attack can tamper with files without touching the repository. One test
asserts that promise: the repo's real rulebook hash is unchanged after the whole run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentgate.policy_guard import fingerprint
from redteam.attacks import (ATTACKS, LIVE_FINDINGS, PINNED_ATTACKS, POLICIES, PRINCIPALS,
                             Arena)

RUNNERS = {attack.__name__: attack for attack in ATTACKS}
RULEBOOK_AT_IMPORT = fingerprint(PRINCIPALS, POLICIES)


def _arena(tmp_path, name: str) -> Arena:
    return Arena(tmp_path / "arena", pin_documents=name in PINNED_ATTACKS)


@pytest.mark.parametrize("name", [n for n in RUNNERS if n not in LIVE_FINDINGS])
def test_attack_is_refused_or_ends_safe(tmp_path, name):
    result = RUNNERS[name](_arena(tmp_path, name))
    assert result.safe, f"{name}: {result.detail}"


@pytest.mark.parametrize("name", LIVE_FINDINGS)
@pytest.mark.xfail(strict=True,
                   reason="Live finding in team/makhdum/REPORT-2.md, kept rather than softened. "
                          "Delete the marker for an attack that starts passing, and say so in the "
                          "report.")
def test_live_finding_is_still_open(tmp_path, name):
    result = RUNNERS[name](_arena(tmp_path, name))
    assert result.safe, f"{name}: {result.detail}"


def test_the_board_is_clean_without_losing_the_mechanism():
    """An empty list must be a fact about the code, not a deleted safety net."""
    assert LIVE_FINDINGS == []
    assert PINNED_ATTACKS <= set(RUNNERS)
    root = Path(__file__).resolve().parent.parent
    audit = root / "docs" / "SECURITY_AUDIT.md"
    report = root / "team" / "makhdum" / "REPORT-2.md"
    target = audit if audit.exists() else report
    text = target.read_text(encoding="utf-8")
    for finding in ("LF-1", "LF-2"):
        assert finding in text, f"{finding} must still be written up, closed or not"


def test_the_harness_is_big_enough_and_every_attack_is_named():
    assert len(ATTACKS) >= 12
    assert len(RUNNERS) == len(ATTACKS)
    for attack in ATTACKS:
        assert attack.__doc__, f"{attack.__name__} has no stated attack"


def test_the_repository_rulebook_was_never_touched():
    assert fingerprint(PRINCIPALS, POLICIES) == RULEBOOK_AT_IMPORT
