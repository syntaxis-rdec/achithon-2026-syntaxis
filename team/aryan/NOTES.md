# Aryan — Notes

Two deliveries landed on this lane and both are in the repository. The export and submission checklist
were written twice — once here on `lane/aryan`, once on `main` while this lane looked empty — so this note
records one implementation as canonical and says what happened to the other.

## What landed (canonical: `main`)

- `agentgate/export.py`
  - `export_audit(store, directory)`: writes `audit.csv` and `audit.json`, ordered by sequential id.
  - `export_outbox(store, directory)`: writes `outbox.csv` with delivery records.
  - `export_summary(store, directory)`: writes `summary.json` with aggregate metrics (decisions,
    allowed, blocked, distinct actors, distinct rules, messages delivered, artifacts by classification,
    redaction count).
  - `export_all(store, directory)`: convenience orchestrator.
  - `Redactor`: regex scanner redacting `sk-`, `ghp_`, `Bearer `, 32+ hex strings — plus a bare `eyJ…`
    JWT, added after the merge below — with `[REDACTED]`.
  - `__main__` CLI: `python -m agentgate.export <db_path> <out_dir>`, creating the directory and
    printing one summary line.
- `tests/test_export.py`: 8 automated tests — row counts, redaction of every shape, summary metrics,
  directory auto-creation, CLI subprocess execution, and the bare-JWT case above.
- `docs/SUBMISSION.md`: submission checklist, archive layout, `agent-trace/PS08/<harness>/` rule,
  redaction rule, never-include list, verification runbook.

### The duplicate, and what was kept

A second export (`audit.csv`/`audit.json`/`outbox.csv`/`summary.json`, 32-hex redaction floor, file
fingerprint) was written on `lane/makhdum` while this lane had no commits. At merge time `main`'s
version won: it is the one `package_submission.py` sits beside and the one documented above. From that
second version, exactly one thing was worth keeping and was ported — the **bare-JWT** pattern, because
a token copied without `Bearer ` is a realistic leak and none of the other four patterns catches it.
The rest was dropped rather than maintained twice.

## The web layer (`web/`) — built on this lane, completed on `lane/makhdum`

`web/app.py`, `web/templates/index.html`, `web/README.md`, `tests/test_web.py`.

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

- **Flask was never declared.** It was absent from `requirements.txt`, so those two tests could not pass
  on a clean clone — verified by `ModuleNotFoundError`. It is now pinned as `flask>=3.0`, and the tests
  run with everything else, in CI too.
- **The page was static; it is now computed.** As merged it rendered hardcoded demo rows, with counters
  that added constants (`+ 7`, `128 + events.length - 4`) to look busy. `web/app.py` now builds a
  snapshot per request from `agentgate-v3.sqlite`, the rulebook on disk and the two published evidence
  artifacts; an empty database renders zeros and says so. `GET /api/snapshot` returns the same object.
- **It is read-only by construction.** Only `GET /` and `GET /api/snapshot` exist, so a POST returns 405.
  The approve/deny/resume/pause controls now refuse and point at the Streamlit dashboard, which goes
  through the guarded gateway — a second action surface would be a second thing to secure.
- **That verification ran 21 commits behind `main`.** "Baseline core tests: all passing" was measured
  against code older than the policy guard, the proposer, the audit chain and the rehearsal; the
  current suite is the number to trust.
- `tests/test_web_live.py` (8 tests) drives the real gateway and requires the page to agree with the
  database, including the empty state, the POST refusal, and that rendering writes no rows.

## Requests

- None blocking. If the web page is shown on stage, say it is a read-only view: the numbers are real,
  but the actions happen in the Streamlit dashboard.
