"""A read-only evidence view of a live AGENTGATE database.

    python web/app.py            # http://127.0.0.1:5000

Every number on the page is read from the SQLite file the gateway writes, from the rulebook on
disk, and from the artifacts the rest of the repository publishes (`benchmark/results.json`,
`redteam/results.json`). Nothing is typed into the template, and an empty database renders zeros
rather than demo data.

The page is deliberately **read-only**. It has no route that approves, resumes or executes: those
belong to the guarded gateway path in `app.py`, and a second action surface would be a second thing
to secure. `python -m agentgate.export` is the way to take the same rows away as files.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentgate.policy import load_policy_set  # noqa: E402
from agentgate.store import Store  # noqa: E402

app = Flask(__name__)

TOOL_META = {
    "read_document": {"name": "Document Reader", "icon": "\u25a4",
                      "desc": "Read approved documents and extract requested information.",
                      "scope": "Read-only access", "risk": "Controlled"},
    "save_report": {"name": "Report Saver", "icon": "\u25a7",
                    "desc": "Save generated reports with source labels and provenance metadata.",
                    "scope": "Create report", "risk": "Controlled"},
    "deliver_inbox": {"name": "Mock Inbox Delivery", "icon": "\u2709",
                      "desc": "Deliver approved reports to a simulated inbox.",
                      "scope": "External-style action", "risk": "Approval required"},
}
WORKFLOW_STATUS = {"active": "In progress", "completed": "Completed", "halted": "Halted"}


def data_dir() -> Path:
    """Same switch the dashboard and the demos use, so both can share a scratch world."""
    return Path(os.environ.get("AGENTGATE_DATA_DIR") or ROOT / "data")


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _rules_in_force(folder: Path) -> dict | None:
    principals_file = folder / "principals.json"
    policies_file = folder / "policies.json"
    if not (principals_file.exists() and policies_file.exists()):
        return None
    try:
        policies = load_policy_set(principals_file, policies_file)
    except (OSError, ValueError):
        return None
    granted: dict[str, int] = Counter()
    for rule in policies.rules:
        granted[rule.tool] += 1
    return {"fingerprint": policies.fingerprint,
            "rules": len(policies.rules),
            "principals": len(policies.principals),
            "grants": dict(granted)}


def snapshot(data: Path | None = None) -> dict:
    """Everything the page shows, computed from the live store or from an honest empty state."""
    folder = Path(data) if data is not None else data_dir()
    db = folder / "agentgate-v3.sqlite"
    live = db.exists()
    store = Store(db if live else ":memory:")
    try:
        audit = store.list_audit(limit=500) if live else []
        outbox = store.list_outbox() if live else []
        artifacts = store.list_artifacts() if live else []
        workflows = store.list_workflows() if live else []
        documents = store.list_documents() if live else []
        steps = {item["id"]: store.steps_for(item["id"]) for item in workflows}
    finally:
        store.close()

    policy = _rules_in_force(folder)
    grants = (policy or {}).get("grants", {})

    tools = []
    for tool, meta in TOOL_META.items():
        tools.append({"id": tool, **meta, "enabled": bool(grants.get(tool)),
                      "scope": f"{grants.get(tool, 0)} rule(s)" if grants else meta["scope"]})

    events = []
    for index, row in enumerate(audit):
        tool = row["tool"]
        events.append({
            "id": f"EVT-{len(audit) - index:04d}",
            "tool": TOOL_META.get(tool, {}).get("name", tool),
            "action": tool,
            "decision": "Allowed" if row["allowed"] else "Blocked",
            "reason": row["reason"],
            "time": str(row["ts"])[11:19] or str(row["ts"]),
        })

    approvals = []
    for item in workflows:
        for step in steps.get(item["id"], []):
            if step["status"] != "pending":
                continue
            request = step["request"]
            tool = request.get("tool", "")
            approvals.append({
                "id": f"{item['id']}/{step['idx']}",
                "tool": TOOL_META.get(tool, {}).get("name", tool or "unknown"),
                "action": f"{tool or 'step'} {request.get('resource_id') or ''}".strip(),
                "risk": "High" if tool == "deliver_inbox" else "Medium",
            })

    board = []
    for item in workflows:
        rows = steps.get(item["id"], [])
        done = sum(1 for step in rows if step["status"] == "done")
        board.append({
            "id": item["id"],
            "name": item["payload"].get("title", item["id"]),
            "checkpoint": f"Step {done} of {len(rows)}",
            "status": WORKFLOW_STATUS.get(item["status"], item["status"].title()),
        })

    allowed = sum(1 for row in audit if row["allowed"])
    benchmark = _read_json(ROOT / "benchmark" / "results.json") or {}
    redteam = _read_json(ROOT / "redteam" / "results.json") or {}

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "database": str(db),
            "live": live,
            "read_only": True,
        },
        "policy": policy,
        "tools": tools,
        "events": events,
        "approvals": approvals,
        "workflows": board,
        "documents": [{"id": doc.id, "title": doc.title, "classification": doc.classification,
                       "owner": doc.owner} for doc in documents],
        "outbox": [{"artifact_id": row["artifact_id"], "recipient": row["recipient"],
                    "classification": row.get("classification", ""), "ts": row["ts"]}
                   for row in outbox],
        "counts": {
            "decisions": len(audit),
            "allowed": allowed,
            "blocked": len(audit) - allowed,
            "delivered": len(outbox),
            "artifacts": len(artifacts),
            "documents": len(documents),
            "workflows": len(workflows),
            "pending_steps": len(approvals),
            "distinct_actors": len({row["actor"] for row in audit}),
            "distinct_rules": len({row["rule_id"] for row in audit}),
            "artifacts_by_classification": dict(sorted(
                Counter(artifact.label.classification for artifact in artifacts).items())),
        },
        "evidence": {
            "benchmark": benchmark.get("metrics", {}),
            "redteam": {key: redteam[key] for key in
                        ("attacks", "refused_or_safe", "succeeded", "open_findings")
                        if key in redteam},
        },
    }


@app.get("/")
def dashboard():
    return render_template("index.html", snapshot=snapshot())


@app.get("/api/snapshot")
def api_snapshot():
    return jsonify(snapshot())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
