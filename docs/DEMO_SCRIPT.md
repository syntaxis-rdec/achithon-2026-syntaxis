# AGENTGATE demo script

Every beat is a click. Nothing is typed, with one disclosed exception: beat 8 presses **Enter** on
a command that is already typed in a second window before you go on stage. Nothing here is
pre-recorded. Everything on screen is computed by the gateway at the moment you click.

Verified by `tests/test_demo_beats.py`: one test per beat, plus two rehearsals that click the whole
cut in order. Read the beat number in the script and the test with the same number — they match.

## Staged before you start (say so, do not hide it)

`demo/seed.py` runs once, out of sight, and pre-creates four things. All four are named in the
lines below.

| Staged | What it is |
|---|---|
| one CONFIDENTIAL report | `Session.submit(save_report doc-001)` through the gateway |
| workflow `DEMO-A permitted run` | three proposals queued, **nothing decided yet** |
| workflow `DEMO-B same proposal, tightened rulebook` | the identical three proposals, also undecided |
| the release justification box | prefilled text; the app prints "Staged for this demo" beside it |

The rulebook you swap in at beat 8 (`demo/policies_tight.json`) is a pre-staged file, not live
editing. It is byte-identical to the committed rulebook except one number, and
`test_staged_rulebook_swap_changes_exactly_one_value` fails if that stops being true.

Fingerprints you will see: default `12a49fe3ae7fc597`, tightened `b76a1526a887e3d2`.

## 60-second cut — beats 1, 2, 3, 4, 7, 8, 9, 12 (target 60–75 s)

### Beat 1 — the gateway says yes to a real request (5 s)
**Click:** `Submit to gateway`. Change nothing: the defaults already read actor `analyst`,
tool `read_document`, "Proposal came from" `human`, document `doc-001 — Q3 Revenue Summary
[CONFIDENTIAL]`.
**Screen:** green **`ALLOWED — rule READ-ANALYST`**, the plain-English reason, the document body
under "Tool result", and "Tool executions recorded in this process: 1".
**Say:** "An analyst reads a confidential document. The gateway checks who, what, and how
sensitive before anything runs — allowed, rule READ-ANALYST, and that counter is the tool
itself reporting that it executed."

### Beat 2 — the label travels with the work (10 s)
**Click:** `Tool` → `save_report`. `Source documents` → `doc-001` and `doc-002`. `Submit to gateway`.
**Screen:** green **`ALLOWED — rule SAVE-ANALYST`**, label `classification: CONFIDENTIAL`,
`provenance: ["doc-001", "doc-002"]`, and the caption "Effective sources after read history:
doc-001, doc-002".
**Say:** "Summarise the confidential board deck together with the cafeteria menu. The report
inherits the highest source label and keeps both sources as provenance — you cannot average
sensitivity down."

### Beat 3 — blocked, before execution (12 s)
**Click:** `Tool` → `deliver_inbox`. Leave `Report` on the newest entry. `Recipient` →
`vendor@outside.example`. `Submit to gateway`.
**Screen:** red **`BLOCKED before execution — rule RULE-RECIPIENT-NOT-PERMITTED`**, then "No tool
was invoked. Nothing reached the document store, the report store, or the inbox.", then
**Messages actually delivered: 0**, and the tool counter still reads 2.
**Say:** "Now send it to the outside vendor. This is the whole point: the decision happens
before the tool, so there is nothing to unsend — zero messages delivered, and the execution
counter did not move."

### Beat 4 — the document is not in charge (12 s)
**Click:** `Actor` → `agent-assistant`. `Tool` → `read_document`. `Proposal came from` →
`agent (AI)`. `Document` → `doc-003 — Vendor Contract Draft [RESTRICTED]`. `Submit to gateway`.
**Screen:** red **`BLOCKED before execution — rule RULE-READ-CLEARANCE`**, reason ending "The text
was never opened."
**Say:** "That contract contains a fake system directive telling the assistant to ignore policy
and forward it to the vendor. The assistant obeys it — and it changes nothing, because policy
never reads document text. It only sees identifiers and labels."

### Beat 7 — a stored workflow is a list of proposals (8 s)
**Click:** scroll to section 5. `Saved workflow` → `DEMO-A permitted run…`. `Resume`.
**Screen:** green **`Ran to completion under `12a49fe3ae7fc597`**", three step rows all `done`,
and **Messages actually delivered: 1**.
**Say:** "A saved workflow is a queue of proposals, not a queue of permissions. This one runs
green under the rulebook currently on disk and puts exactly one message in the inbox."

### Beat 8 — change the rulebook, out of band (5 s)
**Click:** Alt-Tab to the second window and press **Enter** on
`..\.venv\Scripts\python.exe demo\swap_policy.py tighten`. Back in the browser, click
`Saved workflow` → `DEMO-B same proposal, tightened rulebook`.
**Screen:** the terminal prints `tighten: rulebook fingerprint 12a49fe3ae7fc597 ->
b76a1526a887e3d2`; in section 5 the caption reads **`Rulebook on disk right now:
b76a1526a887e3d2`** and DEMO-B still shows three `pending` rows.
**Say:** "One number in the rulebook changes: analysts may now only summarise public material.
The app cannot write its own policy file — that is deliberate — so this comes from outside the
process. Nothing has been re-decided yet; those three steps are still pending."

### Beat 9 — resumption refuses the step that passed a minute ago (10 s)
**Click:** `Resume`.
**Screen:** red **`Stopped at the first block under `b76a1526a887e3d2`**", step rows
`done / blocked / halted`, step 1 reading **RULE-SOURCE-TOO-SENSITIVE**, and
**Messages actually delivered: 1** — still one.
**Say:** "Resume re-reads the rulebook from disk and re-decides every step that is not already
done. The read still passes, the summary is now refused, the delivery behind it is halted
rather than skipped, and the inbox still holds one message."

### Beat 12 — the evidence panel (8 s)
**Click:** scroll to section 4. `Run the suite`.
**Screen:** after about a second, `Scenarios matched 32/32`, `Unauthorized executions 0`,
`False allows / false denies 0 / 0`, `Decisions with a complete audit row 32/32`, and
"All 32 scenarios matched their frozen expectations."
**Say:** "Thirty-two frozen scenarios re-run live in front of you. I have to be honest about
one thing: we wrote those expectations ourselves, which is why the six-way mutation check —
break the gateway six ways and the suite must notice — is the number that actually matters."

## 3-minute extended version — all twelve beats in order

Run the 60-second cut, then add the four extended beats where they are numbered: 5 and 6 after
beat 4, and 10 and 11 after beat 9. Budget: beats 1–4 about 45 s, 5–6 about 25 s, 7–9 about 35 s,
10–11 about 35 s, 12 about 20 s.

### Beat 5 — a non-officer cannot lower a label (10 s) — extended only
**Click:** `Actor` → `analyst` (beat 4 left it on the agent). Scroll to "Release a label" and
click `Release`. Leave `Report to release` and `New classification` on their defaults.
**Screen:** red **`Refused: not a security officer. The attempt is in the audit trail.`**, and
the newest audit row carries `RULE-DECLASSIFY-ROLE`.
**Say:** "Releasing a classification is not one of the AI's tools — it is a human officer action.
As the analyst I am refused, and the refusal itself is audited."

### Beat 6 — an officer release makes a new linked copy (15 s) — extended only
**Click:** `Actor` → `security-officer`. `Release`.
**Screen:** green **`Created report-xxxxxx at PUBLIC. Original untouched.`** The justification box
already holds text, and the page labels it: "Staged for this demo: the justification below was
written in advance by demo/seed.py so this beat is click-only."
**Say:** "As a security officer, with a written justification, I get a brand-new artifact at the
lower level, linked back to the original by provenance. The original is not edited — point at the
row still reading CONFIDENTIAL. The justification text is the one thing on this page that was
written in advance, and it says so on screen."

### Beat 10 — restore the rulebook; the audit keeps both verdicts (20 s) — extended only
**Click:** Alt-Tab, **Enter** on `..\.venv\Scripts\python.exe demo\swap_policy.py restore`. Back in
the browser, with DEMO-B still selected, click `Resume`. Then scroll up to section 3.
**Screen:** green **`Ran to completion under `12a49fe3ae7fc597`**, DEMO-B's rows now
`done / done / done`, **Messages actually delivered: 2**, and two audit rows for the same step:
one `BLOCKED / RULE-SOURCE-TOO-SENSITIVE / b76a1526a887e3d2` and one
`ALLOWED / SAVE-ANALYST / 12a49fe3ae7fc597`.
**Say:** "Undo the tightening and the identical step passes again. Every decision is stored with
the fingerprint of the rulebook that made it, so the trail shows both verdicts and you can prove
they were decided by different policy — not that one was quietly overwritten."

### Beat 11 — resume a finished workflow and nothing happens (15 s) — extended only
**Click:** `Saved workflow` → `DEMO-A permitted run…`. `Resume`.
**Screen:** "Nothing was re-run — every step is already done. A done step is a record of an
effect that happened, not a stored permission." **Messages actually delivered: 2** — unchanged.
**Say:** "Pressing resume on a completed workflow re-sends nothing. The delivery is keyed to its
workflow and step, so a retried step cannot put a second copy in the inbox."

## What not to say

Do not call this authenticated, do not call the mock inbox email, and do not claim the frozen
expectations are independently authored. All three are in `docs/JUDGE_QA.md` with the answer you
want ready. Tamper detection (`RULE-DOC-INTEGRITY`) is real and tested but is **not** in this
beat list, because it needs a document edit and a reload — if a judge asks, it is a
`docs/RUN.md` item 6 you can offer to run after the demo.
