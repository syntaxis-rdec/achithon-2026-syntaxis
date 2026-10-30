"""AGENTGATE demo dashboard.

Every tool call goes through a Session held in a registry, so read history survives
clicks. Policy files are re-read on every run, but a guarded registry only adopts a
rulebook whose bytes still match the pin taken at load; a mid-session swap is denied
under RULE-POLICY-DRIFT until an operator reloads with the token. Declassification is a
separate store action, not a tool, and the page says so. Workflows store proposals only;
the Resume button re-reads the rulebook from disk and re-decides every step that is done.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from agentgate import tools, workflow
from agentgate.gateway import declassify
from agentgate.models import ActionRequest
from agentgate.policy import load_policy_set
from agentgate.policy_guard import Guard
from agentgate.sessions import SessionRegistry
from agentgate.store import Store

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "agentgate-v3.sqlite"
PRINCIPALS = ROOT / "data" / "principals.json"
POLICIES_FILE = ROOT / "data" / "policies.json"
RELOAD_TOKEN = os.environ.get("AGENTGATE_RELOAD_TOKEN")


def world():
    """Fresh store handle and fresh policy read on every rerun. No caching."""
    store = Store(DB)
    store.load_documents_from_dir(ROOT / "data" / "documents")
    policies = load_policy_set(PRINCIPALS, POLICIES_FILE)
    return store, policies


state, policies = world()

if "registry" not in st.session_state:
    st.session_state["guard"] = Guard(PRINCIPALS, POLICIES_FILE, token=RELOAD_TOKEN)
    st.session_state["registry"] = SessionRegistry(state, policies, st.session_state["guard"])
guard: Guard = st.session_state["guard"]
registry: SessionRegistry = st.session_state["registry"]

drift = guard.drift_status()
if drift is None:
    registry.refresh(policies)

st.set_page_config(page_title="AGENTGATE", layout="wide")
st.title("AGENTGATE — permissions enforced before an AI acts")
st.caption(
    "An AI assistant proposes tool calls. A separate, deterministic gateway decides. "
    "Document text has no authority, identities are bound by the session, and security "
    "labels travel with every derived report."
)
st.caption(f"Live · policy fingerprint `{policies.fingerprint}` · document text is untrusted")

if drift is None:
    st.caption(f"Rulebook integrity · pinned `{guard.recorded}` · re-checked before every decision")
else:
    st.error(
        f"Rulebook drift · pinned `{drift.expected}`, on disk `{drift.found}`. Every action is "
        "denied under `RULE-POLICY-DRIFT` and audited until an operator reloads."
    )
    with st.form("reload_rulebook"):
        token = st.text_input("Operator reload token", type="password")
        if st.form_submit_button("Accept the rulebook now on disk"):
            try:
                adopted = registry.reload_rulebook(token or None)
            except PermissionError as exc:
                st.error(str(exc))
            else:
                st.success(f"Adopted `{adopted.fingerprint}`. Reload history: {guard.reloads}")
                st.rerun()

left, middle, right = st.columns([1, 1.2, 1])

with left:
    st.subheader("1. Propose an action")
    actor = st.selectbox("Actor", [p.id for p in policies.principals if p.kind != "recipient"])
    tool = st.selectbox("Tool", ["read_document", "save_report", "deliver_inbox"])
    origin_label = st.radio("Proposal came from", ["human", "agent (AI)"], horizontal=True)
    origin = "agent" if origin_label.startswith("agent") else "human"

    resource_id = None
    source_ids: list[str] = []
    recipient = None

    if tool == "read_document":
        docs = state.list_documents()
        resource_id = st.selectbox(
            "Document", [d.id for d in docs],
            format_func=lambda i: f"{i} — {next(d.title for d in docs if d.id == i)} "
                                 f"[{next(d.classification for d in docs if d.id == i)}]")
    elif tool == "save_report":
        docs = state.list_documents()
        source_ids = st.multiselect(
            "Source documents", [d.id for d in docs],
            format_func=lambda i: f"{i} — {next(d.title for d in docs if d.id == i)} "
                                 f"[{next(d.classification for d in docs if d.id == i)}]")
        st.caption("Titles are derived. Anything this actor has read is added automatically.")
    else:
        artifacts = state.list_artifacts()
        resource_id = st.selectbox(
            "Report", [a.id for a in artifacts],
            format_func=lambda i: f"{i} — {next(a.title for a in artifacts if a.id == i)} "
                                 f"[{next(a.label.classification for a in artifacts if a.id == i)}]",
        ) if artifacts else None
        if resource_id is None:
            st.info("Save a report first — there is nothing to deliver yet.")
        recipient = st.selectbox("Recipient", [p.id for p in policies.principals if p.kind != "actor"])

    if st.button("Submit to gateway", type="primary",
                 disabled=(tool == "deliver_inbox" and not resource_id)):
        request = ActionRequest(tool=tool, resource_id=resource_id, source_ids=source_ids,
                                recipient=recipient)
        decision, result = registry.get(actor, origin).submit(request)
        st.session_state["last"] = (decision.model_dump(), result, request.model_dump())
        st.rerun()

with middle:
    st.subheader("2. Gateway decision")
    if "last" in st.session_state:
        decision, result, sent = st.session_state["last"]
        if decision["allowed"]:
            st.success(f"ALLOWED — rule {decision['rule_id']}")
        else:
            st.error(f"BLOCKED before execution — rule {decision['rule_id']}")
        st.write(decision["reason"])
        if decision["label"]:
            st.json(decision["label"], expanded=False)
        if result is not None:
            st.subheader("Tool result")
            st.write(result)
        else:
            st.caption("No tool was invoked. Nothing reached the document store, the report store, "
                       "or the inbox.")
        if sent.get("source_ids"):
            st.caption(f"Effective sources after read history: {', '.join(sent['source_ids'])}")
    else:
        st.info("Submit an action to see the decision.")

    st.divider()
    st.subheader("Release a label")
    st.caption("Declassification is a store action, not a tool. Only a human security officer may "
               "use it; a new linked copy is created and the original is never edited.")
    artifacts = state.list_artifacts()
    if artifacts:
        target_id = st.selectbox("Report to release", [a.id for a in artifacts],
                                 format_func=lambda i: f"{i} — "
                                 f"{next(a.label.classification for a in artifacts if a.id == i)}")
        target_level = st.selectbox("New classification", ["PUBLIC", "INTERNAL", "CONFIDENTIAL"])
        justification = st.text_area("Written justification", height=70)
        if st.button("Release"):
            try:
                child = declassify(state, policies, actor, target_id, target_level, justification)
                st.success(f"Created {child.id} at {child.label.classification}. Original untouched.")
            except (PermissionError, ValueError) as error:
                st.error(f"Refused: {error}. The attempt is in the audit trail.")

with right:
    st.subheader("3. Audit trail and mock inbox")
    audit = state.list_audit()
    if audit:
        table = pd.DataFrame(audit)[["ts", "actor", "origin", "tool", "resource", "recipient",
                                     "allowed", "rule_id", "reason", "policy_hash"]]
        table["allowed"] = table["allowed"].map({1: "ALLOWED", 0: "BLOCKED"})
        st.dataframe(table, hide_index=True, height=420)
    outbox = state.list_outbox()
    st.write(f"**Messages actually delivered:** {len(outbox)}")
    for message in outbox:
        st.caption(f"{message['ts']} — {message['artifact_id']} "
                   f"[{message.get('classification', '')}] → {message['recipient']}")
    if st.button("Reset demo data"):
        DB.unlink(missing_ok=True)
        st.session_state.clear()
        st.rerun()

st.caption(f"Tool executions recorded in this process: {len(tools.EXECUTIONS)}")

st.divider()
st.subheader("4. Evidence — 32 frozen scenarios")
st.caption("Expectations were written from the specification by this team and frozen before the run. "
           "They are not independently authored; the mutation check below is what makes the number "
           "worth reading.")
run_col, note_col = st.columns([1, 3])
with run_col:
    if st.button("Run the suite"):
        from benchmark.runner import run_suite
        report = run_suite()
        st.session_state["evidence"] = report
with note_col:
    st.caption("A suite that cannot fail is not evidence. Six deliberate breakages are run against "
               "the same table; each one must degrade a metric.")

report = st.session_state.get("evidence")
if report is None:
    results_file = ROOT / "benchmark" / "results.json"
    if results_file.exists():
        import json
        report = json.loads(results_file.read_text(encoding="utf-8"))
if report:
    metrics = report["metrics"]
    a, b, c, d = st.columns(4)
    a.metric("Scenarios matched", f"{metrics['scenario_matches']}/{metrics['scenarios']}")
    b.metric("Unauthorized executions", metrics["unauthorized_executions"])
    c.metric("False allows / false denies",
             f"{metrics['false_allows']} / {metrics['false_denies']}")
    d.metric("Decisions with a complete audit row",
             f"{metrics['audit_complete']}/{metrics['scenarios']}")
    failures = [row for row in report["rows"] if not row["scenario_ok"]]
    if failures:
        st.error(f"{len(failures)} scenario(s) did not match the frozen expectation.")
        for row in failures:
            st.write(f"**{row['id']} {row['title']}** — expected "
                     f"{row['expected']['allowed']}/{row['expected']['rule']}, got "
                     f"{row['actual']['allowed']}/{row['actual']['rule']}")
    else:
        st.success("All 32 scenarios matched their frozen expectations.")
    st.caption(f"scenario file `{report['scenario_file_sha256']}` · policy "
               f"`{report['policy_fingerprint']}`")

st.divider()
st.subheader("5. Workflow resumption")
st.caption(
    "A workflow is a stored list of proposals — actor, tool, sources, recipient — not a stored "
    "decision. Resume re-reads `data/policies.json` from disk, walks the steps from the first one "
    "that is not done, and puts each through the same gateway a live click uses. Tighten a rule "
    "while the app is closed and an already-queued step is refused; the steps behind it are marked "
    "halted instead of quietly skipped."
)

builder, viewer = st.columns([1, 2])
with builder:
    wf_actor = st.selectbox("Workflow actor",
                            [p.id for p in policies.principals if p.kind != "recipient"],
                            key="wf_actor")
    known_docs = state.list_documents()
    wf_doc = st.selectbox(
        "Document", [d.id for d in known_docs], key="wf_doc",
        format_func=lambda i: f"{i} — {next(d.title for d in known_docs if d.id == i)} "
                              f"[{next(d.classification for d in known_docs if d.id == i)}]")
    wf_recipient_choices = [p for p in policies.principals if p.kind != "actor"]
    wf_recipient = st.selectbox(
        "Recipient", [p.id for p in wf_recipient_choices],
        index=next((i for i, p in enumerate(wf_recipient_choices) if p.kind == "recipient"), 0),
        key="wf_recipient")
    st.caption("Three steps: read the document, save a report from it, deliver that report. "
               "Step 3 points at step 1's output, which does not have an id until it runs.")
    if st.button("Create 3-step workflow", key="wf_create", type="primary"):
        created = workflow.create(
            state,
            [ActionRequest(actor_id=wf_actor, tool="read_document", resource_id=wf_doc),
             ActionRequest(actor_id=wf_actor, tool="save_report", source_ids=[wf_doc]),
             ActionRequest(actor_id=wf_actor, tool="deliver_inbox", resource_id="$1",
                           recipient=wf_recipient)],
            title=f"{wf_actor}: read {wf_doc}, summarise, send to {wf_recipient}")
        st.session_state["wf_pick"] = created
        st.session_state.pop("wf_report", None)
        st.rerun()

with viewer:
    saved = state.list_workflows()
    if not saved:
        st.info("Create a workflow on the left, then resume it.")
    else:
        ids = [item["id"] for item in saved]
        by_id = {item["id"]: item for item in saved}
        chosen = st.selectbox(
            "Saved workflow", ids, index=0, key="wf_pick",
            format_func=lambda i: f"{i} — {by_id[i]['status']} · "
                                  f"{by_id[i]['payload'].get('title', '')}")
        steps = state.steps_for(chosen)
        st.dataframe(
            pd.DataFrame([{"#": step["idx"], "Proposal": workflow.describe(step),
                           "Status": step["status"],
                           "Why": step["reason"][:110] or "not attempted yet"}
                          for step in steps]),
            hide_index=True, height=160)
        st.caption(f"Rulebook on disk right now: `{policies.fingerprint}`")
        if st.button("Resume", key="wf_resume"):
            st.session_state["wf_report"] = workflow.resume(state, chosen, PRINCIPALS,
                                                            POLICIES_FILE)
            st.rerun()

        result = st.session_state.get("wf_report")
        if result and result["workflow_id"] == chosen:
            if result["status"] == "completed":
                st.success(f"Ran to completion under `{result['policy_fingerprint']}`.")
            else:
                st.error(f"Stopped at the first block under `{result['policy_fingerprint']}`.")
            if not result["steps"]:
                st.caption("Nothing was re-run — every step is already done. A done step is a "
                           "record of an effect that happened, not a stored permission.")
            for step in result["steps"]:
                st.caption(f"**{step['idx']} · {step['step']}** — {step['status']} · "
                           f"{step['rule_id']} — {step['reason']}")
            st.caption("The audit trail above carries the workflow id, the step index and the "
                       "policy fingerprint of the run that decided it.")
