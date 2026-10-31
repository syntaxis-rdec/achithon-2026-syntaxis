# AGENTGATE web interface (Aryan's lane)

A read-only evidence view of a live AGENTGATE database.

```bash
python web/app.py        # http://127.0.0.1:5000
```

Point it at a scratch world with `AGENTGATE_DATA_DIR`, the same switch the dashboard and the demos
use:

```bash
export AGENTGATE_DATA_DIR=/path/to/scratch/data      # PowerShell: $env:AGENTGATE_DATA_DIR = "..."
python demo/seed.py
python web/app.py
```

## What the page is

Every number on the page is read at request time from `agentgate-v3.sqlite` (the audit trail, the
outbox, artifacts, workflows and their steps), from the rulebook on disk, and from the two published
evidence artifacts (`benchmark/results.json`, `redteam/results.json`). Nothing is typed into the
template. With no database present it renders zeros and says so — it never shows demo data that did
not happen.

It is **read-only by construction**: the only routes are `GET /` and `GET /api/snapshot`, so a POST
returns 405. Approving, resuming, pausing and executing belong to the Streamlit dashboard, which
goes through the guarded gateway — a second action surface would be a second thing to secure. The
buttons on this page therefore refuse and say where the action really happens.

## Panels

- **Overview** — decisions, blocked count, delivered count, registered tools and whether a rule
  currently grants each one.
- **Protected tools** — the three real tools with their live grant count from the rulebook.
- **Authorization requests** — pending workflow steps, read from `workflow_steps`, not invented.
- **Workflows** — real stored workflows with `Step n of m` and their stored status.
- **Audit trail** — the 500 most recent audit rows with rule id, verdict and plain-English reason,
  filterable; the CSV button downloads exactly the rows on screen.
- **Settings** — the rulebook fingerprint and the pinned paths; the toggles are inert and say so.

## JSON

```bash
curl http://127.0.0.1:5000/api/snapshot
```

Returns `meta` (database path, live/empty, read_only), `policy`, `counts`, `events`, `approvals`,
`workflows`, `documents`, `outbox` and `evidence` — the same object the page is rendered from.

## Tests

```bash
pytest tests/test_web.py tests/test_web_live.py
```

`tests/test_web_live.py` drives the real gateway and requires the page to agree with the database,
including the empty state, the refusal to accept POST, and that rendering writes no rows.
