# Makhdum — Task 3 report: automated rehearsal of the stage demo

## 1. Objective

One command that walks the whole `docs/DEMO_SCRIPT.md` demo headlessly, in script order, and either
passes every beat or names the beat that broke — plus a pytest test that fails when the demo breaks, and
proof that the rehearsal detects a real policy regression.

## 2. Implementation summary

`demo/rehearse.py` seeds a scratch directory with `demo/seed.py`, opens `app.py` through
`streamlit.testing.v1.AppTest`, performs the script's click sequence beat by beat, asserts the string
each beat promises, times each beat and prints a table. Exit code `0` all green, `1` a named beat
failed, `2` setup failed.

It does not re-implement the page. The click driver (`Dashboard`, `beat_authorized_read`,
`beat_inherit_label`, `beat_block_outside`, `beat_obey_injection`, `beat_resume`) is loaded by path from
`tests/test_demo_beats.py` — the file that already drives the same beats in pytest — so the rehearsal
and the merged demo tests cannot drift apart. `demo/seed.py` is loaded the same way, and
`demo/swap_policy.py` is loaded *inside* the run, after `AGENTGATE_DATA_DIR` points at the scratch
directory, because that module captures its data path at import and loading it early would have edited
the repository's real rulebook.

`tests/test_rehearsal.py` imports that same module and drives `rehearse()` — one implementation, two
entry points. It asserts the clean run, the resumption evidence, and that the deliberate breakage fails
on the expected beat.

## 3 and 4. Every beat, and the exact string each one asserts

| # | Beat | Expected string (as rendered) | Driven by | s |
|---|---|---|---|---|
| 0 | script fingerprints match the app | `12a49fe3ae7fc597` then `c0a7b0e1860531db` | file read | 0.00 |
| 1 | gateway says yes | `ALLOWED — rule READ-ANALYST` | AppTest | 0.39 |
| 2 | label travels with the work | `ALLOWED — rule SAVE-ANALYST` | AppTest | 0.20 |
| 3 | blocked before execution | `BLOCKED before execution — rule RULE-RECIPIENT-NOT-PERMITTED` | AppTest | 0.18 |
| 4 | document text is not in charge | `BLOCKED before execution — rule RULE-READ-CLEARANCE` | AppTest | 0.32 |
| 5 | non-officer cannot release | `Refused: not a security officer. The attempt is in the audit trail.` | AppTest | 0.12 |
| 6 | officer release makes a copy | `Created report-xxxxxx at PUBLIC. Original untouched.` | AppTest | 0.13 |
| 7 | permitted workflow completes | ``Ran to completion under `12a49fe3ae7fc597` `` | AppTest | 0.18 |
| 8 | rulebook swapped out of band | ``Rulebook on disk right now: `b76a1526a887e3d2` `` | module call + AppTest | 0.06 |
| 9 | resumption refuses the old step | ``Stopped at the first block under `b76a1526a887e3d2` `` | AppTest | 0.17 |
| 10 | restore keeps both verdicts | ``Ran to completion under `12a49fe3ae7fc597` `` | module call + AppTest | 0.23 |
| 11 | finished workflow re-runs nothing | `Nothing was re-run — every step is already done. A done step is a record of an effect that happened, not a stored permission.` | AppTest | 0.14 |
| 12 | evidence panel | `All 32 scenarios matched their frozen expectations.` | AppTest + public API | 2.43 |

Each beat also asserts the numbers around the string, not only the string: the tool counter (1, 2, 2),
`Messages actually delivered` (0, 0, 1, 1, 2, 2), the inherited label and provenance (`CONFIDENTIAL`,
`["doc-001", "doc-002"]`), the step rows (`done/blocked/halted`, then `done/done/done`), the refusal's
audit rule (`RULE-DECLASSIFY-ROLE`), and that no `deliver_inbox` execution happens inside a blocked
beat.

## 5, 6, 7. Actual clean run, per-beat times, total

```
  terminal: tighten: rulebook fingerprint 12a49fe3ae7fc597 -> b76a1526a887e3d2
  terminal: restore: rulebook fingerprint b76a1526a887e3d2 -> 12a49fe3ae7fc597
beat                                    found      s  expected string
0 · script fingerprints match the app   warn    0.00  `12a49fe3ae7fc597` then `c0a7b0e1860531db`
                                                      ! promised string is stale, see REPORT-3.md
                                                      ! docs/DEMO_SCRIPT.md promises default 12a49fe3ae7fc597 / tightened c0a7b0e1860531db; the app renders 12a49fe3ae7fc597 / b76a1526a887e3d2
1 · gateway says yes                    yes     0.39  ALLOWED — rule READ-ANALYST
2 · label travels with the work         yes     0.20  ALLOWED — rule SAVE-ANALYST
3 · blocked before execution            yes     0.18  BLOCKED before execution — rule RULE-RECIPIENT-NOT-PERMITTED
4 · document text is not in charge      yes     0.32  BLOCKED before execution — rule RULE-READ-CLEARANCE
5 · non-officer cannot release          yes     0.12  Refused: not a security officer. The attempt is in the audit trail.
6 · officer release makes a copy        yes     0.13  Created report-xxxxxx at PUBLIC. Original untouched.
7 · permitted workflow completes        yes     0.18  Ran to completion under `12a49fe3ae7fc597`
8 · rulebook swapped out of band        yes     0.06  Rulebook on disk right now: `b76a1526a887e3d2`
9 · resumption refuses the old step     yes     0.17  Stopped at the first block under `b76a1526a887e3d2`
10 · restore keeps both verdicts        yes     0.23  Ran to completion under `12a49fe3ae7fc597`
11 · finished workflow re-runs nothing  yes     0.14  Nothing was re-run — every step is already done. A done step is a record of an effect that happened, not a stored permission.
12 · evidence panel                     yes     2.43  All 32 scenarios matched their frozen expectations.

PASS — 12/12 beats green in 5.8s (limit 90s), 1 script-claim warning(s)
repository rulebook unchanged: True (b4a31dcad8537753)
```

Exit code 0. Total wall time **5.8 s** against the 90 s limit. Beat 0 is not a click: it is the check
that makes the warning above impossible to miss (see §14).

## 8 and 9. What AppTest drove, and the two beats it could not

Ten of the thirteen rows are driven entirely through AppTest: real widget selections, real button
clicks, and assertions read back off the rendered page (`st.success`, `st.error`, `st.metric`, the
dataframes, the JSON label block).

Two beats reach outside the page, and both are labelled in the table:

* **Beat 8 (and beat 10's restore)** — the script says *Alt-Tab to the second window and press Enter on
  `..\.venv\Scripts\python.exe demo\swap_policy.py tighten`*. AppTest has no second terminal.
* **Beat 12** — the script says *click `Run the suite`*. That button calls `benchmark.runner.run_suite()`
  with its default arguments, which rewrites `benchmark/results.json` — a frozen evidence file this
  lane is forbidden to modify.

## 10. Why each fallback was necessary, and what it still proves

Beat 8/10 call `demo/swap_policy.py`'s own public `swap("tighten"/"restore")`, assert the returned
`(before, after)` pair equals the expected rulebook fingerprints, and print the same line the terminal
prints. The page is then asserted through AppTest exactly as the script promises. What is *not* proven:
that the typed shell command itself is correct. That gap is named in §15.

Beat 12 asserts every metric the panel shows against the committed
`benchmark/results.json`, asserts the success banner and the presence of the button, then calls
`benchmark.runner.run_suite(results_path=None)` — the same function the button calls, with the write
suppressed — and requires the live metrics to equal the committed ones. What is *not* proven: the
button's wiring from click to function; the button is confirmed to exist and the function behind it is
confirmed to reproduce the panel.

## 11. Resumption fingerprint verification

The rehearsal does not merely look for two hashes. After beat 10 it asks the store for the audit rows
that belong to the workflow under test and its blocked step:

```
verdicts_for_step(workflow_under_test, 1) == [(False, "b76a1526a887e3d2"),
                                              (True,  "12a49fe3ae7fc597")]
```

That is one step, decided twice, by two known rulebooks — the tightened one that refused it and the
default one that later allowed it. Alongside it, the run asserts:

* the intended step is blocked: rows read `done / blocked / halted`, and the blocked row's rule is
  `RULE-SOURCE-TOO-SENSITIVE`;
* the workflow does not complete under the tightened rulebook: the banner reads
  ``Stopped at the first block under `b76a1526a887e3d2` ``;
* the blocked action did not execute: no `deliver_inbox` appears in the tool counter after the block;
* nothing unintended reached the inbox: delivered count is 1 after the block, 2 after the legitimate
  restore, and still 2 after resuming a finished workflow.

## 12. Full pytest results

```
204 passed, 1 xfailed in 65.95s (0:01:05)
```

The single xfail is the pre-existing LF-2 red-team finding from Task 2 (a document minted after the
policy pin is trusted on sight), kept `strict`. No existing test was edited, skipped or weakened;
`tests/test_demo_beats.py`, `agentgate/`, `app.py`, `benchmark/` and `docs/DEMO_SCRIPT.md` are untouched.

Focused run:

```
collected 11 items
tests\test_rehearsal.py ...........                                      [100%]
11 passed in 12.88s
```

## 13. Deliberate-breakage experiment

Scratch copy only: `demo/seed.py` seeds a temp directory, then `SAVE-ANALYST` is deleted from that copy's
`policies.json` (8 rules → 7), then the same rehearsal runs.

```
  deliberate breakage: removed rule SAVE-ANALYST from C:\Users\shaki\AppData\Local\Temp\agentgate-rehearsal-uj1m2sx4\policies.json
  rules before=8 after=7
beat                                   found      s  expected string
0 · script fingerprints match the app  warn    0.00  `12a49fe3ae7fc597` then `c0a7b0e1860531db`
                                                     ! promised string is stale, see REPORT-3.md
                                                     ! docs/DEMO_SCRIPT.md promises default 12a49fe3ae7fc597 / tightened c0a7b0e1860531db; the app renders 12a49fe3ae7fc597 / b76a1526a887e3d2
1 · gateway says yes                   yes     0.40  ALLOWED — rule READ-ANALYST
2 · label travels with the work        NO      0.22  ALLOWED — rule SAVE-ANALYST
                                                     ! verdict: expected 'ALLOWED — rule SAVE-ANALYST', got 'BLOCKED before execution — rule RULE-NO-GRANT'

FAIL — beat 2 · label travels with the work under 'ALLOWED — rule SAVE-ANALYST' after 1.9s
repository rulebook unchanged: True (b4a31dcad8537753)
```

Exit code **1**. The failing beat is named, the reason is the missing rule (`RULE-NO-GRANT` is what
"this role has no rule for this tool" is called), beat 1 still passes so the failure is not a blanket
breakage, and the repository rulebook hash is identical before and after (`b4a31dcad8537753`). The clean
rehearsal passes again afterwards — the same command, run twice, in §5 and §7 above.

## 14. Live findings

**LF-3 — `docs/DEMO_SCRIPT.md` quotes a tightened fingerprint the app never renders.** Line 26 says
"Fingerprints you will see: default `12a49fe3ae7fc597`, tightened `c0a7b0e1860531db`". The default is
correct; the tightened one is not. The app renders `b76a1526a887e3d2` at beats 8, 9 and 10, because
`demo/policies_tight.json` + `data/principals.json` hash to that. This has been true since the file was
introduced in `380d0ec` — the single historical revision of `demo/policies_tight.json` also hashes to
`b76a1526a887e3d2`, so `c0a7b0e1860531db` was stale when it was written, not broken later.

Impact: a presenter reading beats 8–10 aloud would say a hash that is not on screen. It does not prevent
completion, and no assertion in the demo depends on it. The script is a protected file, so it is recorded
here rather than edited: the fix is one string in `docs/DEMO_SCRIPT.md` and, if the intent was to freeze
a fingerprint, a note that the file must not be reformatted afterwards.

Handling: the rehearsal asserts the *live* fingerprints (asserting the stale one would fail the run for a
documentation typo), and beat 0 in the table compares the script's promise against what the app renders
and prints the mismatch on every run. It is reported, not hidden, and it cannot fail the rehearsal —
which is the behaviour TASK-3 asked for when a promised string is missing.

No other promised string was missing. Every `Screen:` string in the script renders verbatim, including
the longer ones the per-beat tests only match by prefix (`Refused: not a security officer. The attempt is
in the audit trail.` and the full "Nothing was re-run — every step is already done…" caption).

## 15. Remaining limitations

* AppTest renders the script and returns elements; it does not open a browser. CSS, layout, scroll
  position and real keyboard focus are not covered.
* Beat 8/10 never execute the shell command quoted in the script. A wrong path in that line would not be
  caught here; it is caught the first time a human runs the runsheet.
* The click list lives in code, not in the prose. If someone rewrites the script's prose without
  changing a promised string, the rehearsal keeps passing.
* Beat 12 confirms the button exists and that its underlying function reproduces the panel; it does not
  click the button, because doing so rewrites `benchmark/results.json`.
* Timings are AppTest wall time on this machine. 5.7 s against a 90 s budget leaves room, but a much
  slower CI box would grow beat 12 most (it runs the 32-scenario suite live).
* The rehearsal trusts `demo/seed.py`; if the seeder produced a different starting world, beats 2 and 7
  would fail rather than pass silently, because both assert the seeded objects by id.
