# Makhdum — Task 3: Automated Rehearsal

Branch: `lane/makhdum`. Start with `git fetch origin && git merge origin/main`. Read `team/README.md`,
then `docs/DEMO_SCRIPT.md`, `docs/DEMO_RUNSHEET.md`, `demo/seed.py`, `demo/swap_policy.py`.

Your first two lanes are merged and the product is complete. What remains is the riskiest thing left:
nobody has ever run the whole demo from start to finish in one sitting. You are going to make that
impossible to skip.

## Outcome

One command that rehearses the entire stage demo headlessly, in order, and either passes or names the
beat that broke.

## Deliverables

1. `demo/rehearse.py` — drives every beat in `docs/DEMO_SCRIPT.md` using
   `streamlit.testing.v1.AppTest` against a scratch data directory (`AGENTGATE_DATA_DIR`), seeded first
   with `demo/seed.py`. For each beat: perform the exact clicks, assert the exact on-screen strings the
   script promises, and record wall time. Print a table: beat, expected string found, seconds.
2. The resumption beat must use `demo/swap_policy.py` and assert the blocked step plus the two different
   policy fingerprints in the audit trail.
3. `tests/test_rehearsal.py` — the same rehearsal as a test, so a future change that breaks the demo
   breaks the build.
4. `team/makhdum/REPORT-3.md` — the real output of one successful run, the total wall time, and every
   beat you could not drive with AppTest, with the reason and the fallback you used.

## Rules

- If AppTest cannot drive a beat, do not fake it. Use the public API path for that beat, say so in the
  report, and keep the on-screen assertion for the parts you can see.
- Never edit `agentgate/`, `app.py`, `benchmark/`, or `docs/DEMO_SCRIPT.md`. If the script promises a
  string the app does not render, that is a finding: record it in the report under `## Live findings`
  and keep going.
- All existing tests must stay green. Add yours on top.
- One deliberate breakage must make the rehearsal fail: remove one policy rule in a scratch copy and
  show the failing beat. Include that output in the report.

## Done means

`python demo/rehearse.py` exits 0 in under 90 seconds with every beat green, `pytest` is fully green,
and the report contains both the clean run and the broken run.

Commit small on `lane/makhdum`, stage by name, log every turn with your real harness name, push, and add
`## Ready to merge` to `NOTES.md` with the commit hash.
