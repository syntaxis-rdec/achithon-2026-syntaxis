# Aryan — Notes

## Status: delivered, but not on this branch

`lane/aryan` was byte-identical to `main` (zero commits) while the submission packaging was the last
unbuilt deliverable on the team's critical path. At the finder's request these four files were built on
`lane/makhdum` instead, so nothing of anyone else's was touched and Tanush can merge them normally. All
four are **new files**; no existing file was edited:

- `agentgate/export.py`
- `tests/test_export.py` (12 tests)
- `docs/SUBMISSION.md`
- `team/aryan/NOTES.md` (this file)

If the lane is to carry its own commits, fast-forward `lane/aryan` to the export commit rather than
cherry-picking; the history is already linear.

## What the export does

```bash
python -m agentgate.export data/agentgate-v3.sqlite exports/
export: 1 decisions (1 allowed, 0 blocked), 0 messages, 1 artifacts, 0 redaction(s) -> exports
[audit.csv, audit.json, outbox.csv, summary.json]
```

That is the real output from a database freshly seeded by `demo/seed.py` into a scratch directory: one
staged report, one ALLOWED decision, no delivery yet. Exit `0`; exit `2` with a message when the database
is missing or the arguments are wrong. The directory is created, `exports/` stays git-ignored.

## Findings worth keeping

- **`list_audit` is newest-first.** `ORDER BY id DESC` is deliberate in `store.py`, so the CSV inherits
  it. The test asserts the order explicitly rather than pretending it is chronological — a reviewer
  reading the last row expecting the newest would be misled otherwise.
- **The redaction floor is 32 hex characters, and that number matters.** The rulebook fingerprint is 16
  hex characters and appears in every audit row. A 16-character threshold would have redacted
  `policy_hash` and destroyed the one column that proves which rulebook decided what. The test asserts
  the fingerprint survives *and* that a 32-character run does not.
- **A bare JWT is a real leak shape.** The brief lists `sk-`, `ghp_`, `Bearer ` and 32+ hex. A token
  pasted without its `Bearer ` prefix — which is what usually ends up in a justification field — would
  have slipped through, so `eyJ…` was added. It is not in the brief; it is in the guard.
- **`Bearer` with nothing after it is not redacted.** The pattern needs a token to match. That is the
  right trade-off (the word alone is not a secret) but it is worth knowing.
- **The export reads at most 100,000 audit rows** (`list_audit(limit=100_000)`). Beyond that, export a
  window instead of silently trusting a cap. A demo database has tens of rows; this is a note for
  whoever points it at a long-lived trail.
- **`summary.json` carries a fingerprint over the three data files.** Two exports of the same database
  at different times differ in `generated_at` and in that hash, so a reviewer can tell whether a pack
  was regenerated or edited by hand.

## Verification

```
pytest tests/test_export.py -q        -> 12 passed
pytest                                -> 222 passed, 1 xfailed (the documented LF-2 red team finding)
```

Covers: known actions produce the documented columns and row count; the outbox records the addressee
and classification; a fake `sk-`/`ghp_`/`Bearer`/JWT/hex secret in a justification is replaced and
counted while the policy fingerprint survives; summary counts equal the rows in the files beside it; the
output directory is created when missing; the CLI writes four files and prints exactly one line; a
missing database exits 2; each secret shape is redacted on its own; ordinary decision text is untouched.

## Requests

- None blocking. `docs/SUBMISSION.md` and the run-guide table are in this same commit series, so the
  checklist is reachable from the docs that already exist.
- If the demo ever shows the export live, the seeded database produces a thin pack (one decision). Drive
  a few beats first, then export, or run the export after the rehearsal has walked the demo.
