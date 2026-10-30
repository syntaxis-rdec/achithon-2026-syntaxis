"""One command to run the red-team board.

    python -m redteam            # print the board
    python -m redteam --json     # print and write redteam/results.json

Every attack gets its own throwaway world, so the run touches neither the repository's
`data/` nor a live database. The shape deliberately matches `python -m benchmark.runner`:
a table a presenter can put on screen and a committed artifact a judge can diff.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from agentgate import tools
from agentgate.policy_guard import fingerprint

from .attacks import ATTACKS, LIVE_FINDINGS, POLICIES, PRINCIPALS, Arena

HERE = Path(__file__).resolve().parent


def run_all() -> dict:
    rows = []
    for attack in ATTACKS:
        with tempfile.TemporaryDirectory(prefix="agentgate-arena-", ignore_cleanup_errors=True) as tmp:
            tools.reset_executions()
            arena = Arena(Path(tmp))
            try:
                result = attack(arena)
            finally:
                arena.close()
        rows.append({"attack": result.name, "safe": result.safe, "rule_id": result.rule_id,
                     "detail": result.detail, "open_finding": result.name in LIVE_FINDINGS})
    held = sum(1 for row in rows if row["safe"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rulebook_fingerprint": fingerprint(PRINCIPALS, POLICIES),
        "attacks": len(rows),
        "refused_or_safe": held,
        "succeeded": len(rows) - held,
        "open_findings": [row["attack"] for row in rows if row["open_finding"]],
        "results": rows,
    }


def render(report: dict) -> str:
    width = max(len(row["attack"]) for row in report["results"])
    lines = [f"{'attack'.ljust(width)}  verdict   rule"]
    for row in report["results"]:
        verdict = "REFUSED" if row["safe"] else "OPEN FINDING"
        lines.append(f"{row['attack'].ljust(width)}  {verdict:<12} {row['rule_id'] or '-'}")
        if not row["safe"] or row["detail"]:
            lines.append(f"{'':{width}}  {row['detail']}")
    lines.append("")
    open_findings = report["open_findings"]
    tail = (f" - documented open findings: {', '.join(open_findings)}" if open_findings else ".")
    lines.append(f"{report['refused_or_safe']}/{report['attacks']} attacks held; "
                 f"{report['succeeded']} succeeded{tail}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    report = run_all()
    print(render(report))
    if "--json" in argv:
        target = HERE / "results.json"
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {target.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
