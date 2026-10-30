# Aryan — Lane Notes

This file merges two deliveries that landed on the same path. Aryan wrote the web presentation layer
on `lane/aryan`; the audit export and submission packaging were built on `lane/makhdum`, because this
branch had no commits on it when the submission deadline came into view. Both are recorded below,
attributed, and the add/add conflict was resolved by keeping both rather than picking a winner.

## Aryan — web presentation layer (`web/`)

### Status, as written by Aryan

Frontend interface implemented in `web/` using Flask and HTML/CSS/JavaScript.

- `web/app.py`: Flask application server.
- `web/templates/index.html`: Dashboard UI with Overview, Tools, Approvals, Workflows, Audit, and Settings.
- `web/README.md`: Run and feature documentation.
- `tests/test_web.py`: Automated tests verifying route availability and required UI panel headings.

### Verification, as written by Aryan

- `python -m pytest tests/test_web.py`: 2 passed.
- Baseline core tests: all passing.

### Caveats recorded at merge time

- **Flask was never declared.** It was absent from `requirements.txt`, so those two tests could not
  pass on a clean clone — verified by `ModuleNotFoundError` in this environment. `requirements.txt`
  now pins `flask>=3.0`, and the two tests run in the normal suite and in CI.
- **The page is static.** `web/app.py` is one route calling `render_template`, and `index.html` makes
  no request to the gateway: zero `fetch()` or `/api/` calls in the template. Every panel is HTML, so
  it must not be presented as live evidence beside the Streamlit dashboard, which is computed by the
  policy engine on every click. Either wire the panels to the gateway, or label the page a mockup.
- **That verification ran 21 commits behind `main`.** "Baseline core tests: all passing" was measured
  against code older than the policy guard, the proposer and the rehearsal; the current suite is the
  number to trust.

## Makhdum — audit export and submission packaging

Built at the finder's request while this lane was empty, on `lane/makhdum`, then merged here. All four
files were new; no existing file was edited to add them:

- `agentgate/export.py`
- `tests/test_export.py` (12 tests)
- `docs/SUBMISSION.md`
- `team/aryan/NOTES.md` (this file)

```bash
python -m agentgate.export data/agentgate-v3.sqlite exports/
export: 1 decisions (1 allowed, 0 blocked), 0 messages, 1 artifacts, 0 redaction(s) -> exports
[audit.csv, audit.json, outbox.csv, summary.json]
```

That is the real output from a database freshly seeded by `demo/seed.py` into a scratch directory: one
staged report, one ALLOWED decision, no delivery yet. Exit `0`; exit `2` with a message when the
database is missing or the arguments are wrong. The directory is created, `exports/` stays git-ignored.

### Findings worth keeping

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

### Verification

```
pytest tests/test_export.py -q        -> 12 passed
pytest                                -> full suite green, web tests included
```

Covers: known actions produce the documented columns and row count; the outbox records the addressee
and classification; a fake `sk-`/`ghp_`/`Bearer`/JWT/hex secret in a justification is replaced and
counted while the policy fingerprint survives; summary counts equal the rows in the files beside it; the
output directory is created when missing; the CLI writes four files and prints exactly one line; a
missing database exits 2; each secret shape is redacted on its own; ordinary decision text is untouched.

### Requests

- None blocking. `docs/SUBMISSION.md` and the run-guide table are in this same commit series, so the
  checklist is reachable from the docs that already exist.
- If the web page is kept, its panels need a decision: wire them to the gateway, or rename it in
  `web/README.md` so nobody demos it as live.
- If the export is ever shown live, drive a few demo beats first: the seeded database produces a thin
  pack (one decision).
