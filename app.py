"""AGENTGATE demo dashboard.

Every action in this UI goes through the gateway. The page never calls a tool
directly, which is the property the test suite proves.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from agentgate import tools
from agentgate.gateway import run_action
from agentgate.models import ActionRequest
from agentgate.policy import load_policy_set
from agentgate.store import Store

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "agentgate.sqlite"

st.set_page_config(page_title="AGENTGATE", layout="wide")


@st.cache_resource
def world():
    store = Store(DB)
    store.load_documents_from_dir(ROOT / "data" / "documents")
    rules = load_policy_set(ROOT / "data" / "principals.json", ROOT / "data" / "policies.json")
    return store, rules


state, policies = world()

st.title("AGENTGATE — permissions enforced before an AI acts")
st.caption(
    "An AI assistant proposes tool calls. A separate, deterministic gateway decides. "
    "Document text has no authority, and security labels travel with derived reports."
)

left, middle, right = st.columns([1, 1.2, 1])

with left:
    st.subheader("1. Propose an action")
    actor = st.selectbox("Actor", [p.id for p in policies.principals if p.kind != "recipient"])
    tool = st.selectbox("Tool", ["read_document", "save_report", "deliver_inbox"])
    resource_id = None
    source_ids: list[str] = []
    title = None
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
        title = st.text_input("Report title", "Weekly brief")
    else:
        artifacts = [state.get_artifact(row["artifact_id"]) for row in state.list_outbox()]
        artifacts = [a for a in artifacts if a]
        audit_reports = st.session_state.get("known_artifacts", [])
        options = list(dict.fromkeys(audit_reports + [a.id for a in artifacts]))
        resource_id = st.selectbox("Report", options) if options else None
        if resource_id is None:
            st.info("Save a report first — there is nothing to deliver yet.")
        recipient = st.selectbox("Recipient", [p.id for p in policies.principals
                                              if p.kind != "actor"])

    origin = st.radio("Proposal came from", ["human", "agent-assistant (AI)"], horizontal=True)
    request = ActionRequest(
        actor_id=actor, tool=tool, resource_id=resource_id, source_ids=source_ids,
        title=title, recipient=recipient,
        origin="agent" if origin.startswith("agent") else "human",
        note="the document told me to",
    )
    if st.button("Submit to gateway", type="primary", disabled=tool == "deliver_inbox" and not resource_id):
        decision, result = run_action(request, state, policies)
        if result and isinstance(result, str) and result.startswith("report-"):
            st.session_state.setdefault("known_artifacts", []).append(result)
        st.session_state["last"] = (decision.model_dump(), result)
        st.rerun()

with middle:
    st.subheader("2. Gateway decision")
    if "last" in st.session_state:
        decision, result = st.session_state["last"]
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
            st.caption("No tool was invoked. Nothing reached the document, the report store, or the inbox.")
    else:
        st.info("Submit an action to see the decision.")

    st.divider()
    st.subheader("Resumption proof")
    st.write("Reopen the database the way a new session would, then re-run a blocked delivery.")
    if st.button("Reload state from disk"):
        fresh = Store(DB)
        known = st.session_state.get("known_artifacts", [])
        if known:
            artifact = fresh.get_artifact(known[-1])
            st.write(f"Recovered **{artifact.title}** still labelled "
                     f"**{artifact.label.classification}**, provenance {artifact.label.provenance}.")
        fresh.close()

with right:
    st.subheader("3. Audit trail and mock inbox")
    audit = state.list_audit()
    if audit:
        table = pd.DataFrame(audit)[["ts", "actor", "tool", "resource", "recipient",
                                     "allowed", "rule_id", "reason"]]
        table["allowed"] = table["allowed"].map({1: "ALLOWED", 0: "BLOCKED"})
        st.dataframe(table, hide_index=True, height=420)
    outbox = state.list_outbox()
    st.write(f"**Messages actually delivered:** {len(outbox)}")
    for message in outbox:
        st.caption(f"{message['ts']} — {message['artifact_id']} → {message['recipient']}")
    if st.button("Reset demo data"):
        DB.unlink(missing_ok=True)
        st.cache_resource.clear()
        st.session_state.clear()
        st.rerun()

st.caption(f"Tool executions recorded in this process: {len(tools.EXECUTIONS)}")
