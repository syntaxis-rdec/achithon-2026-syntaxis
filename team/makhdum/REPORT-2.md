# Makhdum — Task 2 report: policy integrity guard and red-team harness

## Live findings

**Status, later the same day: both findings below are closed.** LF-1 by `workflow.resume` taking a
guard, LF-2 by the guard pinning the document set as well as the rulebook. The text is left as it was
written, because a finding that was true at the time is part of the record. What closes them, and what
is still opt-in, is at the end under *Addendum*.

**LF-2 — a document minted after the pin is trusted on sight.** The guard pins two files. Drop
`doc-999-forged.md` with `classification: PUBLIC`, `owner: attacker` into the documents folder after
the pin, call `load_documents_from_dir`, and the intern reads it with `integrity=ok` and rule
`READ-INTERN` (`redteam.attacks.mint_a_forged_document`, kept `xfail(strict)`). This is a proposal,
not a shipped guarantee: the guard as specified covers the rulebook, and pinning the document set
would collide with the tamper demo, which edits `data/documents/` on purpose. Fixing it means a
second pin over the folder listing plus each document's fingerprint, adopted through the same token
door — the work I would do first with more time.

**LF-1 — closed, and the finding is now an attack that must keep passing.** `workflow.resume` built a
guardless session and re-read disk, so an unadopted edit to both JSON files let an intern read a
CONFIDENTIAL document and audit it as authorised. `resume` now takes an optional `guard` and passes it
to every step's session, and the dashboard hands it the registry's guard; the same edit produces
`RULE-POLICY-DRIFT` and a halted run. `redteam.attacks.resume_checks_the_policy_pin` holds that door.
Two things came with the fix:

- `declassify` also refuses on drift (`RULE-POLICY-DRIFT`, audited), so no decision path is left
  unguarded.
- `policy_guard.unadopted_rows(state, guard)` finds audit rows stamped with a rulebook hash the
  guard never adopted. Anything that forgets the guard in future is *findable* rather than invisible,
  and `decisions_under_an_unadopted_rulebook_are_findable` runs the guardless path on purpose to
  prove the detector sees it. The dashboard shows the count in the Guard panel.

## What I built

**`agentgate/policy_guard.py`** — `fingerprint(principals, policies)` builds one hash over both
files, byte-identical to how `load_policy_set` builds `PolicySet.fingerprint`, so a pin and a loaded
rulebook are directly comparable. `Guard` records that pin at construction; `check()` raises
`PolicyDrift(expected, found)`; `drift_status()` is the non-raising form for the dashboard;
`reload(token)` returns a fresh rulebook only on the operator's token and appends
`(old, new)` to `guard.reloads`. A `Guard` built without a token can never reload — fail closed.

**`agentgate/gateway.py`** — `Session` takes an optional `guard` and calls `check()` before
evaluating. On drift it audits `RULE-POLICY-DRIFT` through the existing audit path and returns
before `evaluate`, so no tool runs and nothing is read. Identity binding still happens first, so the
denial is attributed correctly.

**`agentgate/sessions.py`** — a guarded registry refuses `refresh()` with any rulebook that does not
match the current pin; the only way in is `reload_rulebook(token)`, which audits both outcomes:
`POLICY-RELOAD` when adopted, `RULE-POLICY-RELOAD-REFUSED` when not.

**`app.py`** — the guard lives in `st.session_state`, the pin is shown next to the live fingerprint,
drift turns into a red banner plus a token field, and Resume is disabled while drifted. The reload
token comes from `AGENTGATE_RELOAD_TOKEN`; unset means reload is impossible.

**`redteam/` + tests** — 22 named attacks, each its own function, in an `Arena` that copies the
documents, the rulebook and its own SQLite file into a tmp directory, so tampering never touches
`data/`. Two meta tests assert the harness is at least twelve attacks deep and that the repository's
own rulebook hash is unchanged after the whole run. Plus thirteen direct unit tests of the guard API.

Beyond the brief, three things the task did not ask for and an MVP needs:

- **`python -m redteam`** prints the attack board and `--json` writes `redteam/results.json`, the same
  one-command evidence shape as `python -m benchmark.runner`. Arenas close their SQLite handle
  explicitly because Windows holds an open file and `TemporaryDirectory` cleanup then fails.
- **The dashboard has a Guard panel** — mode, pin, disk hash, enforced hash, adoption history, the
  count of decisions made off the pin, and the attack board with whatever is still open. An audience
  can see the security state without reading code.
- **The guard fails closed, not open.** An unreadable or deleted rulebook is a `RULE-POLICY-DRIFT`
  denial with an audit row, not a traceback inside the decision path; adoption of a rulebook that does
  not parse is refused; the token is compared with `hmac.compare_digest`.

## What I tried, and what stopped it

| # | Attack | Stopped by |
|---|---|---|
| 1 | name `analyst` in the request body | `RULE-READ-CLEARANCE`, session identity won |
| 2 | claim `origin=human` from an agent path | audit row records `agent` |
| 3 | hide a source you already read | provenance recovered, label CONFIDENTIAL |
| 4 | smuggle a secret in the report title | title is derived, secret dropped |
| 5 | cite only the public twin to downgrade | label stayed CONFIDENTIAL |
| 6 | deliver one clearance short | `RULE-RECIPIENT-CLEARANCE`, inbox empty |
| 7 | deliver to an approved-directory vendor | `RULE-RECIPIENT-NOT-PERMITTED` |
| 8 | edit a RESTRICTED file to say INTERNAL | `RULE-DOC-INTEGRITY`, label frozen |
| 9 | tamper with the source after the report | `RULE-PROVENANCE-TAMPERED` |
| 10 | resume after the rulebook tightened | step blocked, later steps halted, no send |
| 11 | crash between delivery and status write | resume produced exactly one inbox row |
| 12 | swap `policies.json` mid-session | **`RULE-POLICY-DRIFT` plus an audit row** |
| 12b | same swap, adopted with the token | new rulebook decides, no drift denial |
| 12c | swap attempted with the wrong token | refused, and audited refused |
| 13 | ask a non-officer to release | `RULE-DECLASSIFY-ROLE` |
| 14 | release a label upward | `RULE-DECLASSIFY-DIRECTION`, no second artifact |
| 15 | act as a recipient mailbox | `RULE-RECIPIENT-NOT-ACTOR` |
| 16 | act as an unknown actor | `RULE-UNKNOWN-ACTOR` |
| 17 | forge a `$9` step reference | blocked as a missing artifact, nothing sent |
| 18 | resume against an unadopted rulebook edit | **`RULE-POLICY-DRIFT`, run halted — LF-1 closed** |
| 19 | decide off-pin anyway, through a guardless resume | `unadopted_rows` names the row by hash |
| 20 | mint a forged document after the pin | **LF-2 — succeeds today, kept failing** |

## Evidence

- `pytest` — **128 passed, 1 xfailed** against merged `main` (`4d34945`, which added the demo
  seeder, swap tool and 499 lines of `tests/test_demo_beats.py`). Every pre-existing test is green
  and none of their expectations were edited. My lane adds 13 guard unit tests, 24 red-team tests and
  the 33 task-1 injection tests.
- `python -m redteam` — **22 attacks, 21 held, 1 documented open finding**, artifact committed at
  `redteam/results.json` so the board is evidence and not a live opinion.
- Attack 12 fails closed with `RULE-POLICY-DRIFT` and leaves an audit row — the task's explicit
  done-means, asserted in `redteam.attacks.swap_the_rulebook_mid_session`.
- The dashboard path is tested, not assumed: `test_the_dashboard_refuses_a_rulebook_swapped_between_clicks`
  renders the real `app.py` through Streamlit's own `AppTest`, swaps `policies.json` between two
  renders, asserts the drift banner, then drives the reload form twice — a wrong token is refused
  and audited as `RULE-POLICY-RELOAD-REFUSED`, the right token adopts and audits `POLICY-RELOAD`.
- `python -m benchmark.runner` — 32/32, 0 unauthorized executions, 0 false allows, 0 false denies,
  32/32 audit rows. `python -m benchmark.mutations` — all six detected.
- `benchmark/` untouched (including `results.json`, restored after every run), `agentgate/store.py`
  schema untouched, no existing test file edited. Not exercised in an actual browser.

## What the merge forced me to decide

Tanush's demo beat is: `python demo/swap_policy.py tighten`, click the dashboard, watch the next
decision use the tightened rulebook. That is the exact convenience TASK-2 told me to close — "good
for demos and terrible for security". His `tests/test_demo_beats.py` asserts the swapped fingerprint
appears on screen mid-session, so a permanent pin in `app.py` would have broken 499 lines of green
tests and the presentation script at the same time.

The resolution keeps both, and it is a switch rather than a compromise on enforcement:

- **`AGENTGATE_PIN_RULEBOOK=1`** — the pin taken on the first render survives reruns. A rulebook
  swapped between clicks is refused under `RULE-POLICY-DRIFT`, decisions are made with the last
  *adopted* rulebook, and only the operator token moves the pin.
- **Unset (default)** — every render re-pins what is on disk, so the scripted beat lands unchanged.
  The guard still refuses for any session that outlives a rerun, which is the model an agent runtime
  actually uses, and that is what attacks 12, 12b and 12c exercise.

His per-run-registry fix (a SQLite handle must not outlive the thread that opened it) is preserved;
only the pin, which is two paths and a hash, lives across reruns. `app.py` shows which mode it is in,
so nobody presents one believing it is the other.

## Still open

- LF-2 (a document minted after the pin) is the one finding still succeeding.
- The pin defaults to off in the dashboard. That is a deliberate product call to avoid breaking the
  scripted swap beat, not an accident — but it does mean the cross-click story is opt-in until a
  presenter sets `AGENTGATE_PIN_RULEBOOK=1`, and the flag is documented nowhere but this report and
  the on-screen panel.
- `docs/DEMO_SCRIPT.md` and `docs/DEMO_RUNSHEET.md` still tell the presenter a bare
  `swap_policy.py tighten` lands on the next click. True in the default mode, false pinned — where
  the extra line is "then type the reload token". Those files are Tanush's.
- The guard is opt-in per `Session`: a caller can still build one without a guard. The audit hash
  makes that visible (`unadopted_rows`), which is the honest position — enforcement where the product
  runs, detection everywhere.
- The reload token is an env var with no rotation or expiry, and `guard.reloads` is in-memory only;
  the audit rows are the durable record.
- The trust boundary is unchanged and still worth saying out loud: whoever can write
  `data/policies.json` can also write `agentgate/policy_guard.py`.

## With four more hours

1. **Close LF-2 the way LF-1 was closed.** A second pin over the document set — the folder listing
   plus each document's fingerprint — `load_documents_from_dir` refusing a new or changed id without
   an adopt, and the same token door the rulebook already uses. Then delete LF-2's xfail marker and
   the board reads 22/22. One mechanism, two trusted inputs.
2. **Put drift in the evidence table.** A 33rd scenario that swaps the rulebook mid-run and expects
   `RULE-POLICY-DRIFT`, plus the mutation suite breaking the pin check so the number has teeth the
   same way the other six do. `benchmark/` is Tanush's lane, so this is a request I would bring with
   the scenario JSON written and tested in my own lane first.

## Addendum — both findings closed

- **LF-1** closed by `guard` parameters on `workflow.resume` and `declassify`, plus
  `policy_guard.unadopted_rows()` so a guardless path is findable in the audit trail even when nothing
  refused it. Attacks 18 and 19 hold the door and the alarm.
- **LF-2** closed by a second pin over the whole document set: `documents_fingerprint(directory)` hashes
  every file name and body in sorted, length-prefixed order, and `Guard(..., documents_path=...)` refuses
  a minted or edited document with `RULE-DOCUMENT-DRIFT`. `Guard.reload(token)` re-pins both, so one
  operator action adopts one state of the world.
- **What is still a limitation, said plainly:** both pins are opt-in in the dashboard
  (`AGENTGATE_PIN_RULEBOOK=1`, `AGENTGATE_PIN_DOCUMENTS=1`) because the stage demo swaps the rulebook and
  tampers with a document deliberately. Without a pin, a minted document is still trusted on sight — that
  is the default posture, not a hidden one. The board now reads 22/22 because the harness enables the pin
  the attack tests, and `tests/test_policy_guard.py::test_without_a_document_pin_a_minted_document_is_still_trusted`
  asserts the opposite case stays true.
