"""AGENTGATE demo dashboard.

Every tool call goes through a Session held in a registry, so read history survives
clicks. Policy files are re-read on every run, but a guarded registry only adopts a
rulebook whose bytes still match the pin taken at load; a mid-session swap is denied
under RULE-POLICY-DRIFT until an operator reloads with the token. Declassification is a
separate store action, not a tool, and the page says so. Workflows store proposals only;
the Resume button re-reads the rulebook from disk and re-decides every step that is done.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from agentgate import tools, workflow
from agentgate.gateway import declassify
from agentgate.models import ActionRequest, PolicySet
from agentgate.policy import load_policy_set
from agentgate.policy_guard import Guard, unadopted_rows
from agentgate.sessions import SessionRegistry
from agentgate.store import Store

ROOT = Path(__file__).resolve().parent
# AGENTGATE_DATA_DIR lets demo/seed.py and the beat tests point the dashboard at a
# scratch copy of data/ instead of the live folder. Unset, nothing changes.
DATA = Path(os.environ.get("AGENTGATE_DATA_DIR") or ROOT / "data")
DB = DATA / "agentgate-v3.sqlite"
PRINCIPALS = DATA / "principals.json"
POLICIES_FILE = DATA / "policies.json"
DOCS_DIR = DATA / "documents"
DEMO_STATE = DATA / "demo_seed.json"
REDTEAM_REPORT = ROOT / "redteam" / "results.json"
# The only credential that lets an adopted rulebook change what the gateway allows.
# Unset means the pin can never be moved: demo/swap_policy.py alone will not do it.
RELOAD_TOKEN = os.environ.get("AGENTGATE_RELOAD_TOKEN")


def world():
    """Fresh store handle and fresh policy read on every rerun. No caching."""
    store = Store(DB)
    store.load_documents_from_dir(DOCS_DIR)
    policies = load_policy_set(PRINCIPALS, POLICIES_FILE)
    return store, policies


def staged_justification() -> str:
    """Text written in advance by demo/seed.py, so the release beat needs no typing."""
    if not DEMO_STATE.exists():
        return ""
    return json.loads(DEMO_STATE.read_text(encoding="utf-8")).get("justification", "")


state, policies = world()

# The registry and its SQLite handle live for one run only. A connection belongs to the
# thread that opened it, and Streamlit may rerun a page on a different thread, so keeping a
# handle in session_state can crash mid-demo. Read history is in the read_history table, not
# in the Session object, so a fresh registry per run behaves the same.
#
# The guard is different: it is two paths and a hash, so it can survive reruns. With
# AGENTGATE_PIN_RULEBOOK=1 the pin taken on the first render is kept for the whole session, and
# a rulebook swapped between clicks is then refused under RULE-POLICY-DRIFT until an operator
# types the reload token. Unset, every render re-pins what is on disk — the demo's "swap the
# rulebook and watch the next click use it" stays exactly as scripted, and the guard still
# covers any session that outlives a rerun, which is what an agent runtime does.
PIN_RULEBOOK = os.environ.get("AGENTGATE_PIN_RULEBOOK", "") == "1"
# Pinning the document *set* as well catches a document minted after the pin, which per-document
# fingerprints cannot see. Off by default: the tamper demo edits a document on purpose, and that
# edit would then refuse the whole run instead of showing RULE-DOC-INTEGRITY.
PIN_DOCUMENTS = os.environ.get("AGENTGATE_PIN_DOCUMENTS", "") == "1"

if PIN_RULEBOOK and "guard" in st.session_state:
    guard: Guard = st.session_state["guard"]
    adopted: PolicySet = st.session_state["pinned_policies"]
else:
    guard = Guard(PRINCIPALS, POLICIES_FILE, token=RELOAD_TOKEN,
                documents_path=DOCS_DIR if PIN_DOCUMENTS else None)
    adopted = policies
    if PIN_RULEBOOK:
        st.session_state["guard"] = guard
        st.session_state["pinned_policies"] = adopted
registry = SessionRegistry(state, adopted, guard)
drift = guard.drift_status() if PIN_RULEBOOK else None

st.set_page_config(page_title="AGENTGATE", layout="wide")

# Modern High-Contrast Theme & Card Styling
st.markdown("""
<style>
    /* Metric Cards */
    div[data-testid="stMetric"] {
        background: #131d36;
        border: 1px solid #24355a;
        border-radius: 10px;
        padding: 14px 18px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }
    div[data-testid="stMetric"]:hover {
        border-color: #00e5ff;
    }
    div[data-testid="stMetricLabel"] {
        color: #94a3b8;
        font-weight: 600;
        font-size: 0.85rem;
    }
    div[data-testid="stMetricValue"] {
        color: #00e676;
        font-weight: 800;
    }
    /* Primary Action Buttons */
    div.stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
        border: none;
        font-weight: 600;
        letter-spacing: 0.3px;
        border-radius: 6px;
        transition: all 0.2s ease;
    }
    div.stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
        box-shadow: 0 0 15px rgba(14, 165, 233, 0.4);
    }
    /* Security Posture Ribbon */
    .security-badge-ribbon {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 10px 0 16px 0;
    }
    .sec-badge {
        background: rgba(15, 23, 42, 0.8);
        border: 1px solid #334155;
        border-radius: 6px;
        padding: 4px 10px;
        font-size: 0.78rem;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .sec-badge-green { border-color: #059669; color: #34d399; background: rgba(6, 78, 59, 0.25); }
    .sec-badge-cyan { border-color: #0284c7; color: #38bdf8; background: rgba(12, 74, 110, 0.25); }
    .sec-badge-purple { border-color: #7c3aed; color: #c084fc; background: rgba(88, 28, 135, 0.25); }
    .sec-badge-gold { border-color: #d97706; color: #fbbf24; background: rgba(120, 53, 15, 0.25); }
</style>
""", unsafe_allow_html=True)

st.title("AGENTGATE — permissions enforced before an AI acts")
st.caption(
    "An AI assistant proposes tool calls. A separate, deterministic gateway decides. "
    "Document text has no authority, identities are bound by the session, and security "
    "labels travel with every derived report."
)
st.caption(f"Live · policy fingerprint `{policies.fingerprint}` · document text is untrusted")

st.markdown("""
<div class="security-badge-ribbon">
    <span class="sec-badge sec-badge-green">🛡️ ZERO-AUTHORITY GATEWAY: ACTIVE</span>
    <span class="sec-badge sec-badge-cyan">📄 DOCUMENT TEXT: UNTRUSTED & UNPARSED</span>
    <span class="sec-badge sec-badge-purple">⛓️ MERKLE AUDIT CHAIN: TAMPER-EVIDENT</span>
    <span class="sec-badge sec-badge-gold">🪤 CANARY HONEYTOKENS: ARMED</span>
    <span class="sec-badge sec-badge-cyan">🌐 FLASK EVIDENCE SERVER: http://localhost:5000</span>
</div>
""", unsafe_allow_html=True)

with st.expander("✨ NEW: Live Dark-Mode Control Center (Embedded UI)", expanded=True):
    st.markdown(
        "👉 **Viewing modes:** Scroll within this interactive dark-mode dashboard, or open fullscreen at "
        "[**http://localhost:5000**](http://localhost:5000) (live Flask backend)."
    )
    if hasattr(st, "iframe"):
        st.iframe("http://127.0.0.1:5000", height=880)
    else:
        st.markdown(
            '<iframe src="http://127.0.0.1:5000" width="100%" height="880" frameborder="0" style="background:#0B1120;border-radius:12px;"></iframe>',
            unsafe_allow_html=True,
        )

with st.expander("👉 Evaluator & Judge Quick-Start Guide (Click to expand)"):
    st.markdown("""
    **Five Step Live Demonstration Flow:**
    1. **Beat 1 (Green Path):** Keep defaults (*analyst* / *read_document* / *doc-001*), click **Submit to gateway** ➔ `ALLOWED` (rule `READ-ANALYST`).
    2. **Beat 2 (Provenance Lattice):** Switch Tool to `save_report`, select `doc-001` & `doc-002`, submit ➔ Report dynamically inherits `CONFIDENTIAL` classification.
    3. **Beat 3 (Blocked Exfiltration):** Switch Tool to `deliver_inbox`, recipient `vendor@outside.example`, submit ➔ **BLOCKED before execution** (`RULE-RECIPIENT-NOT-PERMITTED`). Tool executions count stays constant; mock inbox receives 0 messages.
    4. **Beat 4 (Prompt Injection Defense):** Switch Actor to `agent-assistant`, select `doc-003` (contract containing injection prompt), submit ➔ **BLOCKED before execution** (`RULE-READ-CLEARANCE`). Document text is never opened.
    5. **Beat 5 (Policy Drift & Resumption):** In Section 5, click **Resume** ➔ Paused workflow re-reads policies on disk and halts at tightened boundaries instead of acting on stale permissions.
    """)

if not PIN_RULEBOOK:
    st.caption("Rulebook pin · off · `AGENTGATE_PIN_RULEBOOK=1` refuses a rulebook swapped "
               "between clicks until an operator adopts it; `AGENTGATE_PIN_DOCUMENTS=1` also pins "
               "the document set, so a minted document is refused")
elif drift is None:
    st.caption(f"Rulebook integrity · pinned `{guard.recorded}` · re-checked before every decision")
else:
    st.error(
        f"{drift.kind.title()} drift · pinned `{drift.expected}`, on disk `{drift.found}`. Every "
        "action is denied under "
        f"`{'RULE-DOCUMENT-DRIFT' if drift.kind == 'documents' else 'RULE-POLICY-DRIFT'}` and "
        "audited until an operator reloads."
    )
    with st.form("reload_rulebook"):
        token = st.text_input("Operator reload token", type="password")
        if st.form_submit_button("Accept the rulebook now on disk"):
            try:
                fresh = registry.reload_rulebook(token or None)
            except PermissionError as exc:
                st.error(str(exc))
            else:
                st.session_state["pinned_policies"] = fresh
                st.success(f"Adopted `{fresh.fingerprint}`. Reload history: {guard.reloads}")
                st.rerun()

with st.expander("Guard status · red-team board"):
    mode = ("pinned across clicks — a rulebook swapped between clicks is refused"
            if PIN_RULEBOOK else "re-pinned on every render — the swap demo runs as scripted")
    st.markdown(f"- **Mode**: {mode}\n"
                f"- **Pin** `{guard.recorded}` · **disk** `{policies.fingerprint}` · "
                f"**enforced** `{adopted.fingerprint}`\n"
                f"- **Adoptions this session**: {len(guard.reloads) or 'none'}"
                + "".join(f"\n  - `{old}` → `{new}`" for old, new in guard.reloads[-3:]))
    if PIN_RULEBOOK:
        ghosts = unadopted_rows(state, guard)
        if ghosts:
            st.warning(f"{len(ghosts)} audit row(s) were decided with a rulebook this session never "
                       "adopted. The stamp is `policy_hash`; the guard would have refused them.")
        else:
            st.caption("Nothing in this trail was decided under an unadopted rulebook.")
    if REDTEAM_REPORT.exists():
        board = json.loads(REDTEAM_REPORT.read_text(encoding="utf-8"))
        st.markdown(f"**Red team** · {board['refused_or_safe']}/{board['attacks']} attacks held"
                    + (f" · open findings: {', '.join(board['open_findings'])}"
                       if board["open_findings"] else " · none open"))
        for row in board["results"]:
            if not row["safe"]:
                st.caption(f"OPEN · {row['attack']} · {row['detail']}")
    else:
        st.caption("Run `python -m redteam --json` to refresh the attack board.")

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
        prefilled = staged_justification()
        if prefilled and "release_justification" not in st.session_state:
            st.session_state["release_justification"] = prefilled
        if prefilled:
            st.caption("Staged for this demo: the justification below was written in advance by "
                       "demo/seed.py so this beat is click-only. In normal use the officer types it.")
        justification = st.text_area("Written justification", height=70,
                                     key="release_justification")
        if st.button("Release"):
            try:
                child = declassify(state, adopted, actor, target_id, target_level,
                                   justification, guard)
                st.success(f"Created {child.id} at {child.label.classification}. Original untouched.")
            except (PermissionError, ValueError) as error:
                st.error(f"Refused: {error}. The attempt is in the audit trail.")

with right:
    st.subheader("3. Audit trail and mock inbox")
    audit = state.list_audit()
    if audit:
        from agentgate.audit_chain import verify_audit_chain
        chain_valid, chain_err, chain_count = verify_audit_chain(state)
        if chain_valid and chain_count > 0:
            st.caption(f"🛡️ **Cryptographic Merkle Chain**: Verified ({chain_count} tamper-evident blocks)")
        elif not chain_valid:
            st.error(f"⚠️ Audit Tamper Alert: {chain_err}")
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
        # Close the connection first: on Windows an open handle makes unlink raise WinError 32.
        try:
            state.close()
        except Exception:
            pass
        deleted = False
        for _ in range(3):
            try:
                DB.unlink(missing_ok=True)
                deleted = True
                break
            except PermissionError:
                time.sleep(0.2)
        if not deleted and DB.exists():
            # Fallback for Windows file locks: truncate tables cleanly rather than raising
            try:
                import sqlite3
                conn = sqlite3.connect(DB)
                conn.executescript("""
                    DELETE FROM audit;
                    DELETE FROM outbox;
                    DELETE FROM artifacts;
                    DELETE FROM workflow_steps;
                    DELETE FROM workflows;
                    DELETE FROM read_history;
                    VACUUM;
                """)
                conn.commit()
                conn.close()
            except Exception:
                pass
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
        st.caption(f"Rulebook on disk right now: `{policies.fingerprint}` · "
                   f"pinned `{guard.recorded}`")
        if drift is not None:
            st.warning("Resume is closed while the rulebook on disk differs from the pin. "
                       "Reload with the operator token first.")
        if st.button("Resume", key="wf_resume", disabled=drift is not None):
            st.session_state["wf_report"] = workflow.resume(
                state, chosen, PRINCIPALS, POLICIES_FILE,
                guard=guard if PIN_RULEBOOK else None)
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
