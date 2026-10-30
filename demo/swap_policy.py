"""One command to change the rulebook a running dashboard reads, with no live editing.

    python demo/swap_policy.py tighten    # data/policies.json  <- demo/policies_tight.json
    python demo/swap_policy.py restore    # data/policies.json  <- demo/policies_default.json

The dashboard re-reads the rulebook on every rerun, so the swap lands on the next click and
the fingerprint in the header changes in front of the judge. `demo/policies_tight.json` is
identical to the committed rulebook except one number: SAVE-ANALYST caps analyst reports at
PUBLIC instead of CONFIDENTIAL.

The app cannot call this. It only ever reads `data/policies.json`, so the rule change comes
from outside the trust boundary — which is the point of the resumption beat.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from agentgate.policy import load_policy_set  # noqa: E402

DATA = Path(os.environ.get("AGENTGATE_DATA_DIR") or ROOT / "data")
LIVE = DATA / "policies.json"
PRINCIPALS = DATA / "principals.json"
SOURCES = {"tighten": HERE / "policies_tight.json", "restore": HERE / "policies_default.json"}


def fingerprint() -> str:
    return load_policy_set(PRINCIPALS, LIVE).fingerprint


def swap(mode: str) -> tuple[str, str]:
    """Replace the live rulebook with the pre-staged file for `mode`."""
    source = SOURCES[mode]
    if not source.exists():
        raise SystemExit(f"missing staged rulebook: {source}")
    before = fingerprint()
    shutil.copyfile(source, LIVE)
    after = fingerprint()
    if mode == "tighten" and before == after:
        raise SystemExit("tightened rulebook produced the same fingerprint — the swap is broken")
    return before, after


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "tighten"
    if mode not in SOURCES:
        print(f"usage: python demo/swap_policy.py [{'|'.join(SOURCES)}]")
        return 2
    before, after = swap(mode)
    print(f"{mode}: rulebook fingerprint {before} -> {after}")
    print(f"live file: {LIVE}")
    print("Now click anything in the dashboard; the next decision uses the new rulebook.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
