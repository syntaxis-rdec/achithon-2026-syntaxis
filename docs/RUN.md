# Running AGENTGATE

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

macOS / Linux:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Tests:

```bash
pytest
```

State lives in `data/agentgate-v3.sqlite`. **Reset demo data** in the dashboard clears it.

## What to try

1. Actor `agent-assistant`, origin `agent (AI)`, document `doc-003` → **BLOCKED** by clearance.
   The injected "ignore all policies" text changes nothing, because policy never reads document text.
2. Actor `analyst`, `save_report` with sources `doc-004` + `doc-001` → report inherits
   `CONFIDENTIAL` and keeps both provenance ids. Its title is derived, never free text.
   Anything the actor has read is added to the sources automatically.
3. Same actor, deliver that report to `team@corp.example` → **BLOCKED**, recipient clearance too
   low. Delivered messages stays 0.
4. Same report to `manager@corp.example` → allowed; the inbox row records the classification sent.
5. Release a label as `analyst` → refused, attempt audited. As `security-officer` with a written
   justification → a new linked copy at the lower level; original untouched; justification stored.
6. Tamper test: edit `classification:` or the title inside `data/documents/doc-003-contract-injection.md`,
   restart the app, try to read it → **BLOCKED** by `RULE-DOC-INTEGRITY`.
   A report built before the tamper is refused with `RULE-PROVENANCE-TAMPERED`.
7. Policy change: edit `data/policies.json`, click any widget, do the action again → the new rule
   applies without a restart.
8. **Workflow resumption** (section 5): choose an actor, a document and a recipient, create the three-step
   workflow — read the document, save a report from it, deliver that report — and press Resume. It runs to
   completion and the inbox gains exactly one message. Change the recipient to
   `vendor@outside.example` and resume a fresh workflow → the delivery step is blocked and the steps behind
   it are marked halted; nothing reaches the inbox. Now tighten `SAVE-ANALYST` to `"PUBLIC"` in
   `data/policies.json`, create one more workflow and resume → the read step still runs, the save step is
   refused with `RULE-SOURCE-TOO-SENSITIVE`, the delivery is halted. Each audit row carries the workflow id,
   the step index and the fingerprint of the rulebook that decided it, so the two runs are distinguishable
   from SQLite alone. Pressing Resume on a finished workflow re-runs nothing: a `done` step is a record of
   an effect, not a stored permission, and a retried delivery is keyed by step so it cannot appear twice.

## Evidence

`python -m benchmark.runner` runs 32 frozen scenarios and writes `benchmark/results.json`.
`python -m benchmark.mutations` breaks the gateway six ways and checks that the suite notices.

Dashboard section 4 shows the same numbers. Current result: 32/32 matched, 0 unauthorized
executions, 0 false allows, 0 false denies, 32/32 complete audit rows, all six mutations detected.

Honest caveat: the expectations were written by this team from the specification and frozen before the
run. They are not independently authored. The mutation check is what makes the number meaningful.

## One command per claim

| Claim | Command |
|---|---|
| the suite is green | `pytest` — 223 tests, 222 pass, 1 documented xfail |
| the frozen table is matched | `python -m benchmark.runner` — 32/32 |
| the table would notice a break | `python -m benchmark.mutations` — 6/6 detected |
| the attacks are refused | `python -m redteam` — 21 of 22 held, one documented |
| the demo script actually runs | `python demo/rehearse.py` — 12 beats, exit 0, under 90 s |
| the trail can leave the app | `python -m agentgate.export <db> exports/` |

`python demo/rehearse.py` exits `1` and names the beat when the demo breaks; add
`--break-rule SAVE-ANALYST` to watch it do that on purpose against a scratch rulebook.

## Honesty notes

- There is no login. Identities are bound by the session object, not authenticated.
- The mock inbox is a SQLite table, not email.
- The dashboard's tool-execution counter resets with the process; the audit table is the durable record.
- Denial reasons name documents by id, never by title, so a block cannot leak what it protects.
