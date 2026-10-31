# Makhdum — Task 2: Policy Integrity and a Red-Team Harness

Branch: `lane/makhdum`. Start with `git fetch origin && git merge origin/main` so you have the merged
resumption code. Read `team/README.md`, then this file.

Your first lane landed and it is good work: 25 tests, real twin assertions, and you proved the tests
were not vacuous by breaking the engine. Keep that instinct — it is the whole point of this task.

## Why this task matters

The gateway trusts two files completely: `data/policies.json` and `data/principals.json`. Anyone who can
edit them can grant anything, and the audit trail will faithfully record the abuse as an authorised
decision. Right now the app re-reads those files on every click, which is good for demos and terrible for
security: a rule swap mid-session silently changes what is allowed.

You are closing that hole, then building the harness that keeps trying.

## Deliverable 1 — policy integrity guard

Create `agentgate/policy_guard.py`:

- `fingerprint(principals_path, policies_path)` — one hash over both files, bytes exactly as loaded.
- `Guard(principals_path, policies_path, token=None)` — records the fingerprint at construction.
- `guard.check()` — raises `PolicyDrift` if the files on disk no longer match the recorded fingerprint.
- `guard.reload(token)` — accepts a new rulebook only with the explicit reload token supplied by the
  operator, and records the old and new fingerprints.
- The gateway must call `check()` before evaluating an action, so a mid-session swap is **denied and
  audited** rather than silently honoured. Use the existing audit path; the rule id should be
  `RULE-POLICY-DRIFT`.

Allowed edits: `agentgate/gateway.py`, `agentgate/policy.py`, `agentgate/sessions.py`, `app.py`.
Do not edit `benchmark/`, `agentgate/store.py` schema, or any existing test's expectations.

**Careful:** the dashboard's resumption demo relies on re-reading the rulebook between runs. Reload must
stay possible through `guard.reload(token)`; make the demo path explicit rather than accidental.

## Deliverable 2 — red-team harness

Create `redteam/attacks.py` and `tests/test_redteam.py` with at least twelve named attacks, each one
function, each asserting the gateway blocks it or produces the safe outcome:

1. Claim a stronger actor in the request body.
2. Claim `origin=human` from an agent path.
3. Hide a source you already read when writing a report.
4. Smuggle a secret through the report title.
5. Lower a label by citing only the public twin of a mixed-source report.
6. Deliver to a recipient whose clearance is one level short.
7. Deliver to an outside address that exists in the directory but is not approved.
8. Read a document whose file was edited to look less sensitive.
9. Deliver a report whose source was tampered with afterwards.
10. Resume a workflow after the rulebook tightened and expect the pending step to stop.
11. Crash between delivery and status write, then resume, and expect exactly one message.
12. Swap `data/policies.json` mid-session and expect a denial under your new guard.
13. Ask a non-officer to release a label.
14. Release a label upward instead of downward.

Add more if you think of them. **If an attack succeeds, do not weaken the assertion.** Write it at the
top of `team/makhdum/REPORT-2.md` under `## Live findings` and keep going — a found hole is worth more
than a green test run.

## Deliverable 3 — report

`team/makhdum/REPORT-2.md`: what you built, what you tried, what worked, what is still open, and the two
things you would do next with four more hours.

## Done means

- `pytest` passes with **at least 67 existing tests still green** plus your new ones.
- `python -m benchmark.runner` still reports 32/32 and `python -m benchmark.mutations` still detects all
  six. If either breaks, you changed behaviour the evidence depends on — fix it, do not edit the table.
- Attack 12 fails closed with `RULE-POLICY-DRIFT` and leaves an audit row.
- `log.txt` has an entry for every turn you took, `tool=` set to your real harness name.

## Rules

Commit small on `lane/makhdum`, stage by name, never `git add -A`, never amend or force-push. When green,
push and add `## Ready to merge` with the commit hash and the final test count to `NOTES.md`. Tanush merges.
