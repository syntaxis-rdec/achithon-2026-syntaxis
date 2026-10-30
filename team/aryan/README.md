# Aryan — Audit Export and Submission Packaging

**Your branch:** `lane/aryan`. Never commit or push to `main`. Read `team/README.md` first, then the
repo-root `AGENTS.md`.

## Context you need

- Every decision, allowed or blocked, is written to the `audit` table in SQLite.
- Row fields: `ts, actor, origin, tool, resource, recipient, allowed, rule_id, reason, label,
  policy_hash, workflow_id, step_index, justification`.
- Delivered messages live in the `outbox` table: `artifact_id, recipient, classification, ts`.
- `Store` is in `agentgate/store.py` and exposes `list_audit(limit)`, `list_outbox()`,
  `list_artifacts()`, `list_workflows()`.

## Outcome

One command that turns a live database into a reviewable evidence pack, plus the submission checklist
for the hackathon.

## Done means

`python -m agentgate.export data/agentgate-v3.sqlite exports/` writes three files and prints a
one-line summary. `pytest tests/test_export.py` passes. No secret-looking string ever appears in the
output.

## Files you own

- `agentgate/export.py`
- `tests/test_export.py`
- `docs/SUBMISSION.md`
- `team/aryan/NOTES.md`

## Do not touch

`agentgate/policy.py`, `gateway.py`, `tools.py`, `store.py`, `sessions.py`, `app.py`, `benchmark/`.

## What to build

1. `export_audit(store, directory)` → `audit.csv` and `audit.json`.
2. `export_outbox(store, directory)` → `outbox.csv`.
3. `export_summary(store, directory)` → `summary.json` with counts: decisions, allowed, blocked,
   distinct actors, distinct rules, messages delivered, artifacts by classification.
4. A `__main__` entry point taking `db_path` and `out_dir`, creating the directory if missing.
5. A redaction guard: before writing, scan every string field for patterns matching `sk-`, `ghp_`,
   `Bearer `, or a 32+ character hex string, and replace the match with `[REDACTED]`. Record how many
   replacements were made in `summary.json`.
6. `docs/SUBMISSION.md`: the checklist for submitting PS08 — what goes in the archive, the
   `agent-trace/PS08/<harness>/` layout, the redaction rule, and what must never be included
   (secrets, `.venv`, screenshots). One page maximum.

## Tests to write

- Export a store with a known set of actions; assert row counts and columns.
- Put a fake `sk-` key inside a justification, export, assert the file contains `[REDACTED]` and not
  the key.
- Assert `summary.json` counts match the rows.
- Assert the output directory is created when missing.

## Constraints

- Standard library plus `pandas` only. No new dependencies.
- `exports/` is git-ignored; never commit generated files.
- Keep functions small and readable; a judge may read this file.

## If blocked

Write the blocker and your fallback under `## Requests` in `NOTES.md`, then continue with the parts
that do not need it.

## Fallback if time is short

CSV plus summary only. Drop JSON. Keep the redaction guard — never drop that.
