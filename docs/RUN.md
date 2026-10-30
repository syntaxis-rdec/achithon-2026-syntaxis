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

## Evidence

`python -m benchmark.runner` runs 32 frozen scenarios and writes `benchmark/results.json`.
`python -m benchmark.mutations` breaks the gateway six ways and checks that the suite notices.

Dashboard section 4 shows the same numbers. Current result: 32/32 matched, 0 unauthorized
executions, 0 false allows, 0 false denies, 32/32 complete audit rows, all six mutations detected.

Honest caveat: the expectations were written by this team from the specification and frozen before the
run. They are not independently authored. The mutation check is what makes the number meaningful.

## Honesty notes

- There is no login. Identities are bound by the session object, not authenticated.
- The mock inbox is a SQLite table, not email.
- The dashboard's tool-execution counter resets with the process; the audit table is the durable record.
- Denial reasons name documents by id, never by title, so a block cannot leak what it protects.
