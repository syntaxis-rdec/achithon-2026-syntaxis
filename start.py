"""One command to run AGENTGATE.

    python start.py

It stages the demo state, starts the two local servers, opens the browser at the dashboard, and
prints what you are looking at. Press Ctrl-C to stop everything.

Why this exists: the app used to need a venv, two terminals, a seeder, a port, and a URL. Nobody
non-technical should have to hold that in their head. The manual path still works and is documented
in `docs/RUN.md`; this is just the front door.

    python start.py --dry-run          show the plan without starting anything
    python start.py --reseed           rebuild the demo state first
    python start.py --port 8600        dashboard port (default 8570)
    python start.py --no-browser       do not open a browser
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable

INTRO = """\
AGENTGATE decides whether an AI assistant may act, before it acts.

  An assistant asks to read a file, save a summary, or send a message.
  A separate policy engine checks who is asking and how sensitive the material is.
  Allowed -> the action runs.  Blocked -> nothing is opened, saved or sent.

This window starts the app. Press Ctrl-C when you are done.
"""


def data_dir() -> Path:
    return Path(os.environ.get("AGENTGATE_DATA_DIR") or ROOT / "data")


def port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def responds(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_for(url: str, seconds: int = 60) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if responds(url):
            return True
        time.sleep(0.5)
    return False


def seed_needed(data: Path, reseed: bool) -> bool:
    return reseed or not (data / "agentgate-v3.sqlite").exists()


def plan(data: Path, reseed: bool, port: int, web_port: int) -> list[str]:
    """What the launcher will do, as sentences a person can read before it happens."""
    steps = []
    if seed_needed(data, reseed):
        steps.append("1. Stage the demo: one confidential report and two queued workflows.")
    else:
        steps.append("1. Reuse the staged demo state already in "
                     f"{data.name}/ (use --reseed to rebuild it).")
    steps.append(f"2. Start the evidence server on port {web_port} (the page's right-hand panel).")
    steps.append(f"3. Start the dashboard on port {port} and open http://localhost:{port} .")
    if web_port != 5000:
        steps.append(f"   note: the dashboard embeds http://localhost:5000, so evidence on "
                     f"{web_port} leaves that panel empty. Use the default for the full page.")
    steps.append("4. Press Ctrl-C here to stop both.")
    return steps


def _spawn(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(args, cwd=str(ROOT), env=os.environ.copy())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run AGENTGATE with one command.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("AGENTGATE_UI_PORT", 8570)))
    parser.add_argument("--web-port", type=int,
                        default=int(os.environ.get("AGENTGATE_WEB_PORT", 5000)))
    parser.add_argument("--reseed", action="store_true", help="rebuild the demo state first")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    args = parser.parse_args(argv[1:])

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    data = data_dir()
    steps = plan(data, args.reseed, args.port, args.web_port)

    print(INTRO)
    for line in steps:
        print("  " + line)
    print()

    if args.dry_run:
        return 0

    if not port_is_free(args.port):
        print(f"The dashboard port {args.port} is already in use.\n"
              f"Close the other Streamlit window, or run: python start.py --port {args.port + 1}")
        return 2

    children: list[subprocess.Popen] = []
    try:
        if seed_needed(data, args.reseed):
            print("Staging the demo ...", flush=True)
            seeded = subprocess.run([PYTHON, str(ROOT / "demo" / "seed.py")],
                                    cwd=str(ROOT), env=os.environ.copy())
            if seeded.returncode != 0:
                print("Could not stage the demo. If a dashboard is already running, close it first,\n"
                      "or stop it with Ctrl-C in its window and try again.")
                return 2
        else:
            print("Using the demo state already staged in data/.", flush=True)

        if responds(f"http://127.0.0.1:{args.web_port}/api/snapshot"):
            print(f"Evidence server already running on {args.web_port}.", flush=True)
        else:
            print("Starting the evidence server ...", flush=True)
            env = os.environ.copy()
            env["AGENTGATE_WEB_PORT"] = str(args.web_port)
            env["AGENTGATE_WEB_HOST"] = "127.0.0.1"
            children.append(subprocess.Popen([PYTHON, str(ROOT / "web" / "app.py")],
                                             cwd=str(ROOT), env=env))
            if not wait_for(f"http://127.0.0.1:{args.web_port}/api/snapshot"):
                print("The evidence server did not answer. The dashboard still works; its "
                      "right-hand panel will be empty.")

        print("Starting the dashboard ...", flush=True)
        children.append(_spawn([PYTHON, "-m", "streamlit", "run", "app.py",
                                "--server.headless", "true",
                                "--server.port", str(args.port),
                                "--browser.gatherUsageStats", "false"]))
        url = f"http://localhost:{args.port}"
        if not wait_for(url + "/_stcore/health"):
            print("The dashboard did not answer in time. Check the messages above.")
            return 2

        print()
        print(f"  Ready: {url}")
        print("  Section 1 takes a request, section 2 shows the decision, section 3 the reason.")
        print("  Press Ctrl-C here to stop the app.")
        if not args.no_browser:
            webbrowser.open(url)
        while True:
            time.sleep(1)
            for child in children:
                if child.poll() is not None:
                    print("A server stopped unexpectedly. Press Ctrl-C and run start.py again.")
                    return 1
    except KeyboardInterrupt:
        print("\nStopping ...")
        return 0
    finally:
        for child in children:
            child.terminate()
        time.sleep(0.5)
        for child in children:
            if child.poll() is None:
                child.kill()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
