# Makhdum — Task 2 report: policy integrity guard and red-team harness

## Live findings

Two attacks are kept failing rather than softened. Both run under `xfail(strict=True)` in
`tests/test_redteam.py`, so the suite is honest today and fails loudly the day either is fixed.

**LF-1 — `workflow.resume` honours a rulebook nobody adopted.** `agentgate/workflow.py:77`
builds `Session(state, policies, ...)` with no guard, and `resume` re-reads both JSON files from
disk at line 64. Reproduced by `redteam.attacks.resume_ignores_the_policy_pin`: an `intern` step to
read `doc-001` is blocked on the first resume, then `principals.json` and `policies.json` are edited
(intern granted RESTRICTED, `READ-INTERN` raised to RESTRICTED) with **no** operator reload, and the
next resume **allows the read and audits it as authorised**. That is precisely the abuse the guard is
meant to refuse. Mitigation that did land: `app.py` disables the Resume button while disk and pin
differ, so the demo path is closed — direct `resume()` calls are not.

**LF-2 — a document minted after the pin is trusted on sight.** The guard pins two files. Drop
`doc-999-forged.md` with `classification: PUBLIC`, `owner: attacker` into the documents folder after
the pin, call `load_documents_from_dir`, and the intern reads it with `integrity=ok` and rule
`READ-INTERN` (`redteam.attacks.mint_a_forged_document`). This is a proposal, not a shipped
guarantee: the guard as specified covers the rulebook, and pinning the document set would collide
with the demo, which edits `data/documents/` on purpose. It is listed because it is the same class
of trust as LF-1, not because it is out of scope.

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

**`redteam/` + tests** — 21 named attacks, each its own function, in an `Arena` that copies the
documents, the rulebook and its own SQLite file into a tmp directory, so tampering never touches
`data/`. Two meta tests assert the harness is at least twelve attacks deep and that the repository's
own rulebook hash is unchanged after the whole run. Plus nine direct unit tests of the guard API.

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
| 18 | resume against a drifted rulebook | **LF-1 — succeeds today** |
| 19 | mint a forged document after the pin | **LF-2 — succeeds today** |

## Evidence

- `pytest` — **123 passed, 2 xfailed** against merged `main` (`4d34945`, which added the demo
  seeder, swap tool and 499 lines of `tests/test_demo_beats.py`). Every pre-existing test is green
  and none of their expectations were edited. My lane adds 9 guard unit tests, 23 red-team tests and
  the 33 task-1 injection tests.
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

- LF-1 needs one parameter on `workflow.resume` (`guard=None`) and `app.py` passing the registry
  guard. Requested, not done.
- LF-2 needs a product decision: pinning the document set would break the tamper demo, which edits
  documents deliberately.
- The guard is opt-in per `Session`. The existing suite and the benchmark construct guardless
  sessions, so wiring it by default would have rewritten expectations I was told not to touch.
  Anything that runs through the registry or a guarded session is covered; anything else is not.
- The reload token is an env var with no rotation or expiry, and `guard.reloads` is in-memory only —
  the audit row is the durable record, the list is not.
- The trust boundary is unchanged and still worth saying out loud: whoever can write
  `data/policies.json` can also write `agentgate/policy_guard.py`.
- `docs/DEMO_SCRIPT.md` and `docs/DEMO_RUNSHEET.md` still tell the presenter that a bare
  `swap_policy.py tighten` lands on the next click. True in the default mode, false under
  `AGENTGATE_PIN_RULEBOOK=1` — where the extra line is "then type the reload token". If the pinned
  mode is what you want to show a judge, those two files need that one sentence, and they are his.
- The pin defaults to off in the dashboard. That is a deliberate product call to avoid breaking the
  scripted beat, not an accident, but it does mean the security story is opt-in until someone sets
  the flag.

## With four more hours

1. **Close LF-1.** Add `guard` to `workflow.resume` and have `app.py` hand it the registry's guard,
   so a resumed step checks the pin like every live click. Then delete LF-1's xfail marker — the
   strict marker means the suite fails the moment it passes without the report being updated.
2. **Pin the document set the way the rulebook is pinned.** A second pin over the folder listing and
   each document's fingerprint, `load_documents_from_dir` refusing a new or changed id without an
   explicit adopt, and LF-2's marker deleted. If the demo needs new documents mid-run, the adopt is
   the same token door the rulebook already uses — one mechanism, two trusted inputs.
