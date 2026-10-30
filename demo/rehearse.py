"""Rehearse the whole stage demo headlessly, in script order.

    python demo/rehearse.py                          # all twelve beats, extended cut
    python demo/rehearse.py --cut 60                 # beats 1, 2, 3, 4, 7, 8, 9, 12
    python demo/rehearse.py --break-rule SAVE-ANALYST  # deliberate regression, scratch copy only

Every beat is the click sequence `docs/DEMO_SCRIPT.md` tells the presenter to perform, run against
`app.py` through Streamlit's own AppTest, on a scratch copy of `data/` that `demo/seed.py` seeds
first. Nothing here re-implements the page: the driver is the one in `tests/test_demo_beats.py`,
loaded by path, so the file the judge trusts and the file that runs on stage cannot drift apart.

Two beats cannot be driven by AppTest and say so in the table:

* Beat 8 presses Enter in a second terminal. The rehearsal calls `demo/swap_policy.py`'s own
  `swap()` and prints the same line the terminal prints.
* Beat 12's `Run the suite` button rewrites `benchmark/results.json`, a frozen table. The
  rehearsal asserts everything the panel shows, then runs the same `benchmark.runner` function
  with the write suppressed and requires the numbers to agree.

Exit code 0 only when every beat is green; 1 when a beat fails, naming it; 2 when setup fails.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from agentgate import tools  # noqa: E402

EM = "—"


# -- loading the existing beat driver, once -----------------------------------


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


DRIVER = _load("agentgate_demo_driver", ROOT / "tests" / "test_demo_beats.py")
SEED = _load("agentgate_demo_seed", HERE / "seed.py")

DEFAULT_RULEBOOK = DRIVER.DEFAULT_RULEBOOK
TIGHT_RULEBOOK = DRIVER.TIGHT_RULEBOOK


class BeatFailed(Exception):
    """A beat did not render what the script promises."""

    def __init__(self, expected: str, detail: str):
        super().__init__(detail)
        self.expected = expected
        self.detail = detail


@dataclass
class Beat:
    number: int
    name: str
    expected: str
    driven_by: str
    seconds: float = 0.0
    found: bool = False
    detail: str = ""
    note: str = ""
    warning: str = ""


SCRIPT = ROOT / "docs" / "DEMO_SCRIPT.md"


def script_claims() -> tuple[str, str]:
    """The two fingerprints the script tells the presenter to read out loud."""
    text = SCRIPT.read_text(encoding="utf-8")
    found = re.search(r"Fingerprints you will see: default `([0-9a-f]+)`, "
                      r"tightened `([0-9a-f]+)`", text)
    return found.groups() if found else ("", "")


def claim_beat() -> Beat:
    """Beat 0: does the script still describe the rulebook the app actually loads?

    A mismatch here is a documentation defect, not a broken beat: the page shows the real
    fingerprint and the story still works, so this is reported as a warning and the run
    continues, exactly as TASK-3 requires for a promised string the app does not render.
    """
    claim_default, claim_tight = script_claims()
    warning = ""
    if (claim_default, claim_tight) != (DEFAULT_RULEBOOK, TIGHT_RULEBOOK):
        warning = (f"docs/DEMO_SCRIPT.md promises default {claim_default} / tightened "
                   f"{claim_tight or 'unreadable'}; the app renders {DEFAULT_RULEBOOK} / "
                   f"{TIGHT_RULEBOOK}")
    return Beat(number=0, name="script fingerprints match the app",
                expected=f"`{claim_default}` then `{claim_tight}`", driven_by="file read",
                found=True, warning=warning,
                detail="" if not warning else "promised string is stale, see REPORT-3.md")


def _need(haystack: str, needle: str, label: str, promised: str | None = None) -> None:
    if needle not in haystack:
        raise BeatFailed(promised or needle, f"{label} was not on screen")


def _need_equal(actual, expected, label: str, promised: str | None = None) -> None:
    if actual != expected:
        raise BeatFailed(promised or str(expected),
                         f"{label}: expected {expected!r}, got {actual!r}")


# -- the beats, in the order the script numbers them ---------------------------
#
# Each takes the live dashboard and a small context dict shared across the run, and raises
# BeatFailed with the string the script promised if the page does not say it.

def beat_1(stage, ctx) -> str:
    DRIVER.beat_authorized_read(stage)
    _need_equal(stage.verdict(), f"ALLOWED {EM} rule READ-ANALYST", "verdict")
    _need_equal(stage.tool_counter(), 1, "tool counter")
    _need_equal(stage.delivered(), 0, "delivered")
    return f"ALLOWED {EM} rule READ-ANALYST"


def beat_2(stage, ctx) -> str:
    DRIVER.beat_inherit_label(stage)
    _need_equal(stage.verdict(), f"ALLOWED {EM} rule SAVE-ANALYST", "verdict")
    _need(stage.screen(), "Effective sources after read history: doc-001, doc-002", "sources line")
    label = stage.labels()[-1]
    _need_equal(label["classification"], "CONFIDENTIAL", "inherited classification")
    _need_equal(label["provenance"], ["doc-001", "doc-002"], "provenance")
    _need_equal(stage.tool_counter(), 2, "tool counter")
    return f"ALLOWED {EM} rule SAVE-ANALYST"


def beat_3(stage, ctx) -> str:
    promised = f"BLOCKED before execution {EM} rule RULE-RECIPIENT-NOT-PERMITTED"
    before = len(tools.EXECUTIONS)
    DRIVER.beat_block_outside(stage)
    _need_equal(stage.verdict(), promised, "verdict")
    _need(stage.screen(), "No tool was invoked.", "no-tool line", promised)
    _need_equal(stage.delivered(), 0, "delivered", promised)
    _need_equal(stage.tool_counter(), 2, "tool counter", promised)
    if len(tools.EXECUTIONS) != before:
        raise BeatFailed(promised, f"a blocked delivery executed a tool: "
                                   f"{tools.EXECUTIONS[before:]}")
    return promised


def beat_4(stage, ctx) -> str:
    promised = f"BLOCKED before execution {EM} rule RULE-READ-CLEARANCE"
    before = len(tools.EXECUTIONS)
    DRIVER.beat_obey_injection(stage)
    _need_equal(stage.verdict(), promised, "verdict")
    reason = next(str(m.value) for m in stage.at.markdown if str(m.value).startswith("Blocked"))
    _need(reason, "The text was never opened.", "denial reason", promised)
    if len(tools.EXECUTIONS) != before:
        raise BeatFailed(promised, f"the injected instruction reached a tool: "
                                   f"{tools.EXECUTIONS[before:]}")
    return promised


def beat_5(stage, ctx) -> str:
    stage.choose("Actor", "analyst").click("Release")
    promised = "Refused: not a security officer. The attempt is in the audit trail."
    _need(stage.screen(), promised, "release refusal")
    _need_equal(stage.audit_rows()[0]["rule_id"], "RULE-DECLASSIFY-ROLE", "audit rule")
    return promised


def beat_6(stage, ctx) -> str:
    stage.choose("Actor", "security-officer").click("Release")
    promised = "Created report-xxxxxx at PUBLIC. Original untouched."
    if not re.search(r"Created report-\w+ at PUBLIC\. Original untouched\.", stage.screen()):
        raise BeatFailed(promised, "the released copy is not on screen")
    _need(stage.screen(), "Staged for this demo", "prefilled justification label")
    return promised


def beat_7(stage, ctx) -> str:
    DRIVER.beat_resume(stage, "run")
    promised = f"Ran to completion under `{DEFAULT_RULEBOOK}`"
    _need(stage.screen(), promised, "completion banner")
    _need_equal(stage.step_statuses("run"), ["done", "done", "done"], "step statuses")
    _need_equal(stage.delivered(), 1, "delivered")
    ctx["executions_before_beat_9"] = len(tools.EXECUTIONS)
    return promised


def beat_8(stage, ctx) -> str:
    """The terminal beat. AppTest cannot press Enter in another window, so the module runs."""
    before, after = ctx["swap"].swap("tighten")
    if before == after:
        raise BeatFailed("tighten: rulebook fingerprint", "the swap changed nothing")
    if after != TIGHT_RULEBOOK:
        raise BeatFailed(TIGHT_RULEBOOK, f"swap produced {after}")
    print(f"  terminal: tighten: rulebook fingerprint {before} -> {after}")
    stage.rerun()

    promised = f"Rulebook on disk right now: `{TIGHT_RULEBOOK}`"
    _need(stage.screen(), promised, "workflow caption")
    _need_equal(stage.step_statuses("tight"), ["pending", "pending", "pending"], "DEMO-B steps")
    _need_equal(stage.delivered(), 1, "delivered")
    ctx["executions_before_beat_9"] = len(tools.EXECUTIONS)
    return promised


def beat_9(stage, ctx) -> str:
    before = ctx["executions_before_beat_9"]
    DRIVER.beat_resume(stage, "tight")
    promised = f"Stopped at the first block under `{TIGHT_RULEBOOK}`"
    _need(stage.screen(), promised, "halt banner")
    _need_equal(stage.step_statuses("tight"), ["done", "blocked", "halted"], "DEMO-B steps")
    _need_equal([r["Status"] for r in stage.step_rows()], ["done", "blocked", "halted"], "rows")
    blocked = [r for r in stage.audit_rows() if r["rule_id"] == "RULE-SOURCE-TOO-SENSITIVE"]
    if not blocked:
        raise BeatFailed("RULE-SOURCE-TOO-SENSITIVE", "the blocked step is not in the audit trail")
    _need_equal(blocked[0]["policy_hash"], TIGHT_RULEBOOK, "blocked fingerprint")
    _need_equal(stage.delivered(), 1, "delivered")
    if [e for e in tools.EXECUTIONS[before:] if e.startswith("deliver_inbox")]:
        raise BeatFailed(promised, "the halted delivery executed")
    ctx["workflow_under_test"] = stage.staged_id("tight")
    ctx["delivered_after_block"] = stage.delivered()
    return promised


def beat_10(stage, ctx) -> str:
    before, after = ctx["swap"].swap("restore")
    print(f"  terminal: restore: rulebook fingerprint {before} -> {after}")
    if after != DEFAULT_RULEBOOK:
        raise BeatFailed(DEFAULT_RULEBOOK, f"restore produced {after}")
    stage.rerun()
    DRIVER.beat_resume(stage, "tight")

    promised = f"Ran to completion under `{DEFAULT_RULEBOOK}`"
    _need(stage.screen(), promised, "completion banner")
    _need_equal(stage.step_statuses("tight"), ["done", "done", "done"], "DEMO-B steps")
    _need_equal(stage.delivered(), 2, "delivered")
    verdicts = stage.verdicts_for_step("tight", 1)
    _need_equal(verdicts, [(False, TIGHT_RULEBOOK), (True, DEFAULT_RULEBOOK)],
                "the same step under two rulebooks", promised)
    ctx["two_rulebooks"] = verdicts
    ctx["delivered_end"] = stage.delivered()
    return promised


def beat_11(stage, ctx) -> str:
    DRIVER.beat_resume(stage, "run")
    promised = ("Nothing was re-run — every step is already done. A done step is a record of an "
                "effect that happened, not a stored permission.")
    _need(stage.screen(), promised, "no-op banner")
    _need_equal(stage.delivered(), 2, "delivered", promised)
    ctx["delivered_after_noop"] = stage.delivered()
    return promised


def beat_12(stage, ctx) -> str:
    """The panel is asserted on screen; the live re-run is called with the write suppressed."""
    from benchmark.runner import run_suite

    committed = json.loads((ROOT / "benchmark" / "results.json").read_text(encoding="utf-8"))
    metrics = committed["metrics"]
    shown = {m.label: str(m.value) for m in stage.at.metric}
    _need_equal(shown, {
        "Scenarios matched": f"{metrics['scenario_matches']}/{metrics['scenarios']}",
        "Unauthorized executions": str(metrics["unauthorized_executions"]),
        "False allows / false denies": f"{metrics['false_allows']} / {metrics['false_denies']}",
        "Decisions with a complete audit row":
            f"{metrics['audit_complete']}/{metrics['scenarios']}",
    }, "evidence panel")
    promised = "All 32 scenarios matched their frozen expectations."
    _need(stage.screen(), promised, "suite verdict")
    if "Run the suite" not in [b.label for b in stage.at.button]:
        raise BeatFailed("Run the suite", "the button is not on screen")

    live = run_suite(results_path=None)
    if live["metrics"] != metrics:
        raise BeatFailed(promised, "a live run does not reproduce the committed panel")
    return promised


BEATS: list[tuple[int, str, Callable, str, str]] = [
    (1, "gateway says yes", beat_1, "AppTest", ""),
    (2, "label travels with the work", beat_2, "AppTest", ""),
    (3, "blocked before execution", beat_3, "AppTest", ""),
    (4, "document text is not in charge", beat_4, "AppTest", ""),
    (5, "non-officer cannot release", beat_5, "AppTest", ""),
    (6, "officer release makes a copy", beat_6, "AppTest", ""),
    (7, "permitted workflow completes", beat_7, "AppTest", ""),
    (8, "rulebook swapped out of band", beat_8, "module call + AppTest",
     "AppTest cannot press Enter in another terminal window; the rehearsal calls "
     "demo/swap_policy.py's own swap() and prints the same line."),
    (9, "resumption refuses the old step", beat_9, "AppTest", ""),
    (10, "restore keeps both verdicts", beat_10, "module call + AppTest", ""),
    (11, "finished workflow re-runs nothing", beat_11, "AppTest", ""),
    (12, "evidence panel", beat_12, "AppTest + public API",
     "the Run the suite button rewrites benchmark/results.json, a frozen file; the rehearsal "
     "asserts the panel and then calls benchmark.runner.run_suite(results_path=None)."),
]

CUTS = {"full": [b[0] for b in BEATS], "60": [1, 2, 3, 4, 7, 8, 9, 12]}


# -- the run ------------------------------------------------------------------


@dataclass
class Rehearsal:
    beats: list[Beat] = field(default_factory=list)
    ok: bool = False
    failed: Beat | None = None
    seconds: float = 0.0
    break_rule: str | None = None
    rulebook_before: str = ""
    rulebook_after: str = ""
    scratch: str = ""
    error: str = ""
    evidence: dict = field(default_factory=dict)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def rehearse(cut: str = "full", break_rule: str | None = None,
             data: Path | None = None) -> Rehearsal:
    """Seed a scratch world, drive every beat in order, and report where it stopped."""
    run = Rehearsal(break_rule=break_rule)
    started = time.perf_counter()
    repo_rulebook = ROOT / "data" / "policies.json"
    run.rulebook_before = _sha(repo_rulebook)

    scratch = Path(data) if data else Path(tempfile.mkdtemp(prefix="agentgate-rehearsal-"))
    run.scratch = str(scratch)
    if not scratch.exists():
        scratch.mkdir(parents=True)
    shutil.copytree(ROOT / "data", scratch, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("*.sqlite"))

    context: dict = {}
    previous = os.environ.get("AGENTGATE_DATA_DIR")
    os.environ["AGENTGATE_DATA_DIR"] = str(scratch)
    try:
        seeded = SEED.seed(scratch)
        if break_rule:
            _remove_rule(scratch / "policies.json", break_rule)
        # Loaded here, not at import: swap_policy.py reads AGENTGATE_DATA_DIR when it is imported,
        # and pointing it at the repository's data/ would edit the real rulebook.
        tools.reset_executions()
        stage = DRIVER.Dashboard(scratch, seeded)

        context["swap"] = _load(f"agentgate_demo_swap_{id(scratch)}", HERE / "swap_policy.py")
        run.beats.append(claim_beat())
        for number, name, runner, driven_by, note in BEATS:
            if number not in CUTS[cut]:
                continue
            beat = Beat(number=number, name=name, expected="", driven_by=driven_by, note=note)
            clock = time.perf_counter()
            try:
                beat.expected = runner(stage, context)
                beat.found = True
            except BeatFailed as failure:
                beat.expected = failure.expected
                beat.detail = failure.detail
            except AssertionError as failure:  # a driver assertion, e.g. a missing widget
                beat.expected = beat.expected or name
                beat.detail = f"driver assertion: {failure}"
            finally:
                beat.seconds = time.perf_counter() - clock
            run.beats.append(beat)
            if not beat.found:
                run.failed = beat
                break
    except SystemExit as exc:  # demo/seed.py aborts loudly when the world is wrong
        run.error = f"setup failed: {exc}"
    except BeatFailed as exc:
        run.error = f"setup failed: {exc.detail}"
    except Exception as exc:  # a broken scratch world is a setup failure, not a beat failure
        run.error = f"setup failed: {type(exc).__name__}: {exc}"
    finally:
        run.rulebook_after = _sha(repo_rulebook)
        if previous is None:
            os.environ.pop("AGENTGATE_DATA_DIR", None)
        else:
            os.environ["AGENTGATE_DATA_DIR"] = previous

    run.evidence = {key: value for key, value in context.items() if key != "swap"}
    run.seconds = time.perf_counter() - started
    run.ok = run.failed is None and not run.error
    if not data:
        shutil.rmtree(scratch, ignore_errors=True)
    return run


def _remove_rule(policies_file: Path, rule_id: str) -> None:
    """The deliberate regression: one rule gone from a scratch rulebook, never from data/."""
    rules = json.loads(policies_file.read_text(encoding="utf-8"))
    kept = [rule for rule in rules if rule["id"] != rule_id]
    if len(kept) == len(rules):
        raise BeatFailed(rule_id, f"no rule named {rule_id} to remove")
    policies_file.write_text(json.dumps(kept, indent=2), encoding="utf-8")
    print(f"  deliberate breakage: removed rule {rule_id} from {policies_file}")
    print(f"  rules before={len(rules)} after={len(kept)}")


def render(run: Rehearsal) -> str:
    width = max([len(f"{b.number} · {b.name}") for b in run.beats] + [12])
    lines = [f"{'beat'.ljust(width)}  {'found':<5}  {'s':>5}  expected string"]
    for beat in run.beats:
        mark = "NO" if not beat.found else ("warn" if beat.warning else "yes")
        lines.append(f"{(f'{beat.number} · {beat.name}').ljust(width)}  {mark:<5}  "
                     f"{beat.seconds:5.2f}  {beat.expected}")
        if beat.detail:
            lines.append(f"{'':{width}}  {'':5}  {'':5}  ! {beat.detail}")
        if beat.warning:
            lines.append(f"{'':{width}}  {'':5}  {'':5}  ! {beat.warning}")
    lines.append("")
    if run.error:
        lines.append(f"SETUP FAILED — {run.error}")
    elif run.ok:
        scored = [b for b in run.beats if b.number]
        warned = [b for b in run.beats if b.warning]
        lines.append(f"PASS — {len(scored)}/{len(scored)} beats green in {run.seconds:.1f}s "
                     f"(limit 90s)" + (f", {len(warned)} script-claim warning(s)" if warned else ""))
    else:
        lines.append(f"FAIL — beat {run.failed.number} · {run.failed.name} "
                     f"under {run.failed.expected!r} after {run.seconds:.1f}s")
    lines.append(f"repository rulebook unchanged: "
                 f"{run.rulebook_before == run.rulebook_after} ({run.rulebook_after})")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Rehearse the AGENTGATE stage demo headlessly.")
    parser.add_argument("--cut", choices=sorted(CUTS), default="full",
                        help="full = all twelve beats, 60 = the short cut")
    parser.add_argument("--break-rule", default=None, metavar="RULE_ID",
                        help="remove a policy rule from the scratch copy and expect a failure")
    parser.add_argument("--data", default=None, help="scratch directory to use instead of a temp one")
    args = parser.parse_args(argv[1:])

    run = rehearse(cut=args.cut, break_rule=args.break_rule,
                   data=Path(args.data) if args.data else None)
    print(render(run))
    if run.error:
        return 2
    return 0 if run.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
