"""The submission archive is the thing that gets scored, so it cannot be an untested script.

`package_submission.py` had no test and no run record: it printed "SUCCESS" and asked people to
believe it. These tests build a real archive into a temporary directory and assert what is in it,
what is kept out, and that a planted secret stops the build instead of riding along.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("package_submission", ROOT / "package_submission.py")
packager = importlib.util.module_from_spec(spec)
sys.modules["package_submission"] = packager
spec.loader.exec_module(packager)


def test_collect_files_takes_the_real_source_and_no_junk():
    files = packager.collect_files()
    assert files, "the packager found nothing to include"
    top = {path.relative_to(ROOT).parts[0] for path in files}
    assert {"agentgate", "tests", "docs", "web", "benchmark"} <= top

    for path in files:
        name = path.name
        assert not name.endswith((".sqlite", ".db", ".pyc", ".pyo")), name
        assert ".venv" not in path.parts and "__pycache__" not in path.parts
        assert name != ".env", "a dot-env file must never be packaged"


def test_a_planted_secret_is_refused_not_packaged(capsys):
    # Built at runtime on purpose: the packager scans every file it collects, including tests,
    # so a literal token in this source would block the build. That behaviour is correct.
    planted = "sk-" + "K7x9" * 5
    assert packager.check_secrets_in_text("clean audit row", "audit.txt") is True
    capsys.readouterr()
    assert packager.check_secrets_in_text(f"key {planted}", "note.txt") is False
    assert "Secret pattern detected" in capsys.readouterr().err


def test_the_archive_builds_and_carries_the_evidence_files(tmp_path, monkeypatch):
    target = tmp_path / "submission.zip"
    monkeypatch.setattr(packager, "OUTPUT_ZIP", target)
    assert packager.main() == 0

    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        for required in ("start.py", "agentgate/policy.py", "agentgate/export.py", "app.py",
                         "docs/RUN.md",
                         "docs/SUBMISSION.md", "web/app.py", "demo/rehearse.py",
                         "redteam/attacks.py", "benchmark/scenarios.json",
                         "benchmark/results.json", "requirements.txt"):
            assert required in names, f"{required} is missing from the archive"
        assert not [name for name in names
                    if name.endswith((".sqlite", ".pyc")) or ".venv" in name.split("/")]
        assert not any(name.startswith("agentgate-PS08-submission") for name in names)


def test_the_generated_archive_cannot_be_committed():
    """A 0.3 MB zip in the repository root would otherwise land in git next to the source."""
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*.zip" in ignore or "agentgate-PS08-submission.zip" in ignore

    check = subprocess.run(["git", "check-ignore", "-q", str(ROOT / "agentgate-PS08-submission.zip")],
                           cwd=str(ROOT), capture_output=True)
    assert check.returncode == 0, "the built archive must be git-ignored"


def test_the_one_command_launcher_is_shipped(tmp_path, monkeypatch):
    """The archive is what a non-technical reader receives; without start.py the front door is gone."""
    target = tmp_path / "submission.zip"
    monkeypatch.setattr(packager, "OUTPUT_ZIP", target)
    assert packager.main() == 0
    with zipfile.ZipFile(target) as archive:
        assert "start.py" in archive.namelist()
        readme = archive.read("README.md").decode("utf-8", errors="replace")
    assert "python start.py" in readme, "the shipped README must lead with the one command"
