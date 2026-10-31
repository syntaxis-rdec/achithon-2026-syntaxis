# AGENTGATE — judge Q&A

Ten questions, answers you can say out loud. Everything below is true of this branch; the things
we could not do are in the answer, not hidden from it.

**1. How do you know a blocked action was not executed, rather than executed and then logged as a
block?**
Three things that would all have to fail together. The tools refuse to run without the gateway's
capability object — `tools.py::_require_gate`, and a direct `tools.read_document(...)` call raises
`PermissionError` in `test_tools_refuse_direct_calls`. The on-screen counter grows only *inside* a
tool body, so beat 3 leaves it at 2. And the outbox is a table with zero rows in it. The benchmark
counts exactly this across 32 scenarios: `unauthorized_executions 0`, and the mutation suite breaks
that metric on purpose to show it can move.

**2. Where is the trust boundary?**
This Python process and the files it reads. Anyone who can edit `data/policies.json`,
`data/principals.json` or `data/agentgate-v3.sqlite` can change an outcome; the gateway mediates
proposals, not the operator. Document tampering is detected by fingerprint; a deliberate edit to
the policy file is not, and cannot be — a file cannot defend itself against someone with write
access to it.

**3. Is there authentication?**
No. There is no login and no account. The `Session` binds actor and origin so a request cannot
claim to be someone else (`test_request_cannot_claim_a_different_actor`,
`test_request_cannot_claim_to_be_human`), but nothing verifies who is holding the keyboard. That
was a cut we made deliberately: identity *binding*, not identity verification.

**4. Who wrote the 32 scenario expectations?**
We did, from the specification, frozen before any run. They are not independently authored, and the
dashboard says that on the panel in front of the numbers. What makes 32/32 worth reading is
`python -m benchmark.mutations`: six deliberate breakages of the gateway, each of which must
degrade a metric. All six are detected. About nine seconds.

**5. What does the audit trail prove, and how is it protected against tampering?**
Every audit entry is cryptographically sealed in SQLite using a SHA-256 Merkle hash chain (`agentgate/audit_chain.py`):
EntryHash_i = SHA256(CanonicalFields_i || EntryHash_{i-1}), linked back to a 64-zero genesis root.
Any row modification, deletion, or reordering breaks the chain and is detected by `verify_audit_chain(store)`.
The audit record captures: actor, origin, tool, resource id, recipient, decision, rule id,
plain-English reason, and policy fingerprint. Reasons name documents by ID, never by title or content,
so a denial never leaks what it protects.

**6. What if it crashes between the tool running and the status being written?**
A delivery carries `workflow:step` as a unique effect key, so a retried step reuses the row and
cannot send twice — `test_a_crash_between_execute_and_status_write_does_not_deliver_twice`. A
report has no natural key: crash exactly between `save_report` and its status write and the retry
creates a second artifact, leaving the first orphaned while the workflow points at the newer one.
We are naming that gap rather than papering over it.

**7. Your injection defence — what does it actually cover?**
Policy reads identifiers and labels only: actor, role, clearance, tool, resource id, recipient,
classification, provenance. It never inspects `Document.body`. `data/eval_documents` holds twelve
documents as six clean/hostile twins with identical front matter and different bodies; every twin
pair produces identical verdicts, and the hostile payload strings appear in no rule id, reason or
label. Beat 4 shows the live version: a RESTRICTED contract ordering the agent to forward it to the
vendor, refused by clearance with the text never opened.
What it does not cover: a model paraphrasing hostile text *into* a report. The body does go into
the artifact, so derived text inherits the label but is not screened for content.

**8. Would a real agent framework be stopped by this?**
Only if the agent can reach the tools no way other than through the gateway — which is the design:
a capability token, not a nicer prompt. An agent that can import `agentgate.tools` and call it
directly is outside the boundary and gets a `PermissionError`. We do not do network egress control,
OS sandboxing, or per-tool rate limits, and there is no LLM in this demo loop at all: the proposals
come from your clicks and from the queued workflow, so nothing had to be asked to behave.

**9. Why is declassification not one of the three tools?**
Because an AI must not be able to lower its own visibility. `declassify` is a separate store action:
human with the security-officer role only, a written justification of at least 15 characters, the
officer's own clearance at or above the current label, downward only, and it creates a *new linked*
artifact instead of editing the original. Refusals are audited too (beat 5). And a released copy
still has to pass the delivery checks — releasing a label is not a right to send.

**10. What is not real in this demo?**
The inbox is a SQLite table, not email. Principals are JSON entries, not accounts. Documents are
markdown files. There is no LLM and no external policy service. Four things are staged before you
walk in, and the script says so: `demo/seed.py` pre-creates one CONFIDENTIAL report and two queued
workflows through the gateway, the release justification is prefilled — with a line on screen
calling that out — and the tightened rulebook is a pre-staged file swap, not live editing. The
evidence panel prints the committed `results.json` until you press `Run the suite`, which then
recomputes all 32 scenarios in about a second. Nothing anywhere here is a recording.
