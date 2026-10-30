"""Reset the demo and pre-create exactly what docs/DEMO_SCRIPT.md clicks on.

    python demo/seed.py

Everything is built through the public gateway and workflow API. The staged report comes from
a `Session.submit` of a `save_report` proposal; the two workflows come from `workflow.create`.
No tool is called directly — `agentgate/tools.py` would refuse it — and no SQL is written: the
store is handed a fresh file and asked to load the sample documents, the same call the
dashboard makes on every rerun.

When it finishes the dashboard is in the starting position for beat one: open it, and the
first click is `Submit to gateway` with the defaults still showing `analyst` /
`read_document` / `human` / `doc-001`.

Run the printed checks yourself if you doubt any of it; the script asserts them and exits
non-zero if the state is not what the script claims.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from agentgate import workflow  # noqa: E402
from agentgate.gateway import Session  # noqa: E402
from agentgate.models import ActionRequest  # noqa: E402
from agentgate.policy import load_policy_set  # noqa: E402
from agentgate.store import Store  # noqa: E402

DEFAULT_DATA = ROOT / "data"

# The three beats that need a pre-existing object. Each one is named in the script as
# staged, because none of them was created by a click in front of the judge.
STAGED_REPORT_SOURCES = ["doc-001"]
WORKFLOW_DOC = "doc-004"          # INTERNAL: passes the default rulebook, fails the tight one
# manager, not team: beat one reads doc-001, so by the time this workflow runs the analyst's
# read history pushes the report to CONFIDENTIAL and team@corp.example could not receive it.
WORKFLOW_RECIPIENT = "manager@corp.example"
TITLES = {
    "run": "DEMO-A permitted run (read, save, deliver)",
    "tight": "DEMO-B same proposal, tightened rulebook",
}
JUSTIFICATION = (
    "Q3 revenue figures were published in the annual report this week, so this summary no "
    "longer needs CONFIDENTIAL handling. Releasing a PUBLIC copy for the vendor pack."
)


def data_dir() -> Path:
    return Path(os.environ.get("AGENTGATE_DATA_DIR") or DEFAULT_DATA)


def _read_save_send() -> list[ActionRequest]:
    """The same three-step proposal list the dashboard's own create button builds."""
    return [
        ActionRequest(actor_id="analyst", tool="read_document", resource_id=WORKFLOW_DOC),
        ActionRequest(actor_id="analyst", tool="save_report", source_ids=[WORKFLOW_DOC]),
        ActionRequest(actor_id="analyst", tool="deliver_inbox", resource_id="$1",
                      recipient=WORKFLOW_RECIPIENT),
    ]


def seed(target: Path | None = None) -> dict:
    """Rebuild demo state in `target`; returns what the script is allowed to claim."""
    data = Path(target) if target is not None else data_dir()
    db = data / "agentgate-v3.sqlite"
    policies_file = data / "policies.json"
    principals_file = data / "principals.json"
    demo_state = data / "demo_seed.json"

    shutil.copyfile(HERE / "policies_default.json", policies_file)
    db.unlink(missing_ok=True)
    demo_state.unlink(missing_ok=True)

    state = Store(db)
    loaded = state.load_documents_from_dir(data / "documents")
    policies = load_policy_set(principals_file, policies_file)

    analyst = Session(state, policies, "analyst", "human")
    decision, staged_report = analyst.submit(
        ActionRequest(tool="save_report", source_ids=list(STAGED_REPORT_SOURCES)))
    if not decision.allowed:
        raise SystemExit(f"seed could not create the staged report: {decision.rule_id}")

    wf_run = workflow.create(state, _read_save_send(), title=TITLES["run"])
    wf_tight = workflow.create(state, _read_save_send(), title=TITLES["tight"])

    report = {
        "justification": JUSTIFICATION,
        "policy_fingerprint": policies.fingerprint,
        "documents": loaded,
        "staged": {
            "report_id": staged_report,
            "report_rule": decision.rule_id,
            "workflows": {"run": wf_run, "tight": wf_tight},
            "note": ("Created by demo/seed.py, not by a click. The justification box is "
                     "prefilled from this file so the release beat needs no typing."),
        },
    }
    _check(state, report)
    demo_state.write_text(json.dumps(report, indent=2), encoding="utf-8")
    state.close()
    return report


def _check(state: Store, report: dict) -> None:
    """Every claim docs/DEMO_SCRIPT.md makes about the starting position, or abort."""
    assert report["documents"] == 4, "expected four sample documents"
    assert state.list_outbox() == [], "beat three says the inbox is empty; it is not"
    assert state.reads_for("analyst") == [], "read history leaked into the seed"
    assert state.integrity_of(WORKFLOW_DOC) == "ok", f"{WORKFLOW_DOC} is not clean"

    artifacts = state.list_artifacts()
    assert len(artifacts) == 1, "expected exactly one staged report"
    assert artifacts[0].label.classification == "CONFIDENTIAL"
    assert artifacts[0].label.provenance == STAGED_REPORT_SOURCES

    workflows = {item["id"]: item for item in state.list_workflows()}
    assert len(workflows) == 2, "expected the two demo workflows"
    for key in ("run", "tight"):
        steps = state.steps_for(report["staged"]["workflows"][key])
        assert [s["status"] for s in steps] == ["pending", "pending", "pending"], key
        assert steps[2]["request"]["resource_id"] == "$1", "step 3 must chain to step 2"
    assert len(state.list_audit()) == 1, "seed should leave one audit row, not none or many"
    assert len(JUSTIFICATION) >= 15, "the gateway refuses a short justification"


def main(argv: list[str]) -> int:
    report = seed()
    staged = report["staged"]
    print(f"demo state: {data_dir() / 'agentgate-v3.sqlite'}")
    print(f"rulebook on disk: {report['policy_fingerprint']} (default)")
    print(f"staged report   : {staged['report_id']} "
          f"[CONFIDENTIAL <- {', '.join(STAGED_REPORT_SOURCES)}] via {staged['report_rule']}")
    print(f"staged workflow : {staged['workflows']['run']} — {TITLES['run']} (3 pending)")
    print(f"staged workflow : {staged['workflows']['tight']} — {TITLES['tight']} (3 pending)")
    print("staged input    : release justification prefilled")
    print("inbox           : 0 messages delivered")
    print()
    print("Ready. Start the dashboard and begin at beat 1:")
    print(r"    ..\team-9-11\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8570")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
