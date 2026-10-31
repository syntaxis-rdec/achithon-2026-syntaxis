"""The front door has to work for someone who reads only what it prints.

`start.py` is the first thing a non-technical user runs. These tests hold it to two promises: it
explains the purpose before it does anything, and `--dry-run` really is a dry run.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("agentgate_start", ROOT / "start.py")
start = importlib.util.module_from_spec(spec)
sys.modules["agentgate_start"] = start
spec.loader.exec_module(start)


def test_dry_run_states_the_purpose_and_the_plan(capsys, tmp_path):
    assert start.main(["start.py", "--dry-run"]) == 0
    out = capsys.readouterr().out

    assert "decides whether an AI assistant may act" in out
    assert "Allowed -> the action runs" in out and "Blocked -> nothing" in out
    for step in ("1.", "2.", "3.", "4.", "Ctrl-C"):
        assert step in out
    assert "http://localhost:" in out


def test_the_plan_names_the_ports_it_will_use(tmp_path):
    steps = start.plan(tmp_path, reseed=False, port=8600, web_port=5066)
    joined = " ".join(steps)
    assert "port 5066" in joined and "port 8600" in joined
    assert "http://localhost:8600" in joined


def test_seeding_is_skipped_unless_asked_or_missing(tmp_path):
    staged = tmp_path / "data"
    staged.mkdir()
    (staged / "agentgate-v3.sqlite").write_bytes(b"")
    assert start.seed_needed(staged, reseed=False) is False
    assert start.seed_needed(staged, reseed=True) is True
    assert start.seed_needed(tmp_path / "empty", reseed=False) is True


def test_a_busy_port_is_reported_not_used():
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        busy = held.getsockname()[1]
        assert start.port_is_free(busy) is False
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    assert start.port_is_free(free) is True


def test_a_busy_dashboard_port_exits_with_a_way_out(monkeypatch, capsys):
    monkeypatch.setattr(start, "port_is_free", lambda port: False)
    monkeypatch.setattr(start, "seed_needed", lambda data, reseed: False)
    code = start.main(["start.py", "--port", "8570", "--no-browser"])
    message = capsys.readouterr().out
    assert code == 2
    assert "--port 8571" in message, "the message must say how to fix it"


def test_a_non_default_evidence_port_is_called_out(tmp_path):
    """The dashboard embeds :5000; starting evidence elsewhere would silently blank that panel."""
    custom = " ".join(start.plan(tmp_path, reseed=False, port=8570, web_port=5066))
    assert "leaves that panel empty" in custom
    default = " ".join(start.plan(tmp_path, reseed=False, port=8570, web_port=5000))
    assert "leaves that panel empty" not in default
