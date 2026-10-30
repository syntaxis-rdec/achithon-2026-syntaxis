"""AGENTGATE demo dashboard.

Every action goes through a Session. The page never calls a tool directly, and the
policy files are re-read on every run so a rule change on disk is honoured.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from agentgate import tools
from agentgate.gateway import Session, declassify
from agentgate.models import ActionRequest
from agentgate.policy import load_policy_set
from agentgate.store import Store

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "agentgate-v2.sqlite"


def world():
    """Fresh store handle and fresh policy read on every rerun. No caching."""
    store = Store(DB)
    store.load_documents_from_dir(ROOT / "data" / "documents")
    policies = load_policy_set(ROOT / "data" / "principals.json", ROOT / "data" / "policies.json")
    return store, policies


state, policies = world()

st.set_page_config(page_title="AGENTGATE", layout="wide")
st.title("AGENTGATE — permissions enforced before an AI acts")
st.caption(
    "An AI assistant proposes tool calls. A separate, deterministic gateway decides. "
    "Document text has no authority, identities are bound by the session, and security "
    "labels travel with every derived report."
)
st.caption(f"Live · policy fingerprint `{policies.fingerprint}` · document text is untrusted")

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
        st.caption("The title is derived from the sources. Free text cannot enter a report.")
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
        decision, result = Session(state, policies, actor, origin).submit(request)
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
            st.caption("No tool was invoked. Nothing reached the document store, the report store, "
                       "or the inbox.")
    else:
        st.info("Submit an action to see the decision.")

    st.divider()
    st.subheader("Declassification")
    st.caption("Only a human security officer may lower a label. A new linked copy is created; "
               "the original is never edited.")
    artifacts = state.list_artifacts()
    if artifacts:
        target_id = st.selectbox("Report to declassify", [a.id for a in artifacts],
                                 format_func=lambda i: f"{i} — "
                                 f"{next(a.label.classification for a in artifacts if a.id == i)}")
        target_level = st.selectbox("New classification", ["PUBLIC", "INTERNAL", "CONFIDENTIAL"])
        justification = st.text_area("Written justification", height=70)
        if st.button("Declassify"):
            try:
                child = declassify(state, policies, actor, target_id, target_level, justification)
                st.success(f"Created {child.id} at {child.label.classification}. "
                           f"Original untouched.")
            except (PermissionError, ValueError) as error:
                st.error(f"Refused: {error}. The attempt is in the audit trail.")

with right:
    st.subheader("3. Audit trail and mock inbox")
    audit = state.list_audit()
    if audit:
        table = pd.DataFrame(audit)[["ts", "actor", "origin", "tool", "resource", "recipient",
                                     "allowed", "rule_id", "reason", "policy_hash"]]
        table["allowed"] = table["allowed"].map({1: "ALLOWED", 0: "BLOCKED"})
        st.dataframe(table, hide_index=True, height=460)
    outbox = state.list_outbox()
    st.write(f"**Messages actually delivered:** {len(outbox)}")
    for message in outbox:
        st.caption(f"{message['ts']} — {message['artifact_id']} → {message['recipient']}")
    if st.button("Reset demo data"):
        DB.unlink(missing_ok=True)
        st.session_state.clear()
        st.rerun()

st.caption(f"Tool executions recorded in this process: {len(tools.EXECUTIONS)}")
