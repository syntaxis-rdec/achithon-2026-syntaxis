"""The app has to work over HTTP, not only inside AppTest.

Everything else in this repository drives `app.py` through Streamlit's in-process test client. That
missed a real crash once already — a SQLite handle kept in `st.session_state` died when a rerun landed
on another thread, and only a browser saw it (`team/tanush/REQUESTS.md`). These tests start the actual
servers, speak HTTP to them, and fail if the process writes a traceback.

Two processes are covered because the stage demo needs both: the Streamlit dashboard and the Flask
evidence server the dashboard embeds as an iframe.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture()
def world(tmp_path) -> Path:
    """A scratch data directory: the sample documents and the live rulebook, no database yet."""
    data = tmp_path / "data"
    data.mkdir()
    shutil.copytree(ROOT / "data" / "documents", data / "documents")
    shutil.copy(ROOT / "data" / "principals.json", data / "principals.json")
    shutil.copy(ROOT / "data" / "policies.json", data / "policies.json")
    return data


def _wait_and_get(base: str, path: str, attempts: int = 90) -> tuple[int, bytes, str]:
    """Poll until the server answers, then return status, body and everything it wrote so far."""
    deadline = time.time() + attempts * 0.5
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base}{path}", timeout=5) as response:
                return response.status, response.read(), last_error
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            last_error = str(exc)
            time.sleep(0.5)
    raise AssertionError(f"no answer from {base}{path}: {last_error}")


def _terminate(proc: subprocess.Popen) -> str:
    proc.terminate()
    try:
        _, err = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:  # a wedged server must not wedge the suite
        proc.kill()
        _, err = proc.communicate(timeout=30)
    return (err or b"").decode("utf-8", errors="replace")


def test_the_streamlit_dashboard_serves_a_real_page(world):
    """The presenter's actual path: streamlit over HTTP, not an in-process render."""
    port = _free_port()
    env = {**os.environ, "AGENTGATE_DATA_DIR": str(world), "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
         "--server.headless", "true", "--server.port", str(port),
         "--browser.gatherUsageStats", "false"],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        health, body, _ = _wait_and_get(f"http://127.0.0.1:{port}", "/_stcore/health")
        assert health == 200 and body.strip() == b"ok", body
        status, page, _ = _wait_and_get(f"http://127.0.0.1:{port}", "/", attempts=40)
        assert status == 200 and page, "the dashboard returned an empty page"
        # Streamlit runs the script only when a browser session connects, so the HTTP layer can
        # prove the server is up and serving; tests/test_demo_beats.py prove the script renders.
    finally:
        log = _terminate(proc)

    assert "Traceback (most recent call last)" not in log, log[-2000:]
    assert "sqlite3.ProgrammingError" not in log, log[-2000:]


def test_the_flask_evidence_server_serves_live_data(world):
    """The iframe in the dashboard points at this process; if it is down, the demo has a hole."""
    port = _free_port()
    env = {**os.environ, "AGENTGATE_DATA_DIR": str(world), "AGENTGATE_WEB_PORT": str(port),
           "AGENTGATE_WEB_HOST": "127.0.0.1", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([sys.executable, str(ROOT / "web" / "app.py")], cwd=str(ROOT),
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    try:
        status, body, _ = _wait_and_get(base, "/")
        html = body.decode("utf-8", errors="replace")
        assert status == 200
        assert "READ-ONLY" in html, "the evidence page must say what it is"
        assert "{{" not in html, "an unrendered template reached the browser"

        status, payload, _ = _wait_and_get(base, "/api/snapshot")
        snapshot = json.loads(payload)
        assert snapshot["meta"]["read_only"] is True
        assert snapshot["counts"]["decisions"] == 0, "a fresh world has no decisions to show"
        assert snapshot["policy"]["fingerprint"], "the rulebook fingerprint must be live"
    finally:
        log = _terminate(proc)

    assert "Traceback (most recent call last)" not in log, log[-2000:]


def test_the_two_ports_do_not_have_to_collide(world):
    """The port is configurable so a busy 5000 does not stop the demo."""
    port = _free_port()
    assert port != 5000
    env = {**os.environ, "AGENTGATE_DATA_DIR": str(world), "AGENTGATE_WEB_PORT": str(port),
           "AGENTGATE_WEB_HOST": "127.0.0.1"}
    proc = subprocess.Popen([sys.executable, str(ROOT / "web" / "app.py")], cwd=str(ROOT),
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        status, _, _ = _wait_and_get(f"http://127.0.0.1:{port}", "/api/snapshot")
        assert status == 200
    finally:
        _terminate(proc)
