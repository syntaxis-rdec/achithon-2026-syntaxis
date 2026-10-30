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

State lives in `data/agentgate-v2.sqlite`. **Reset demo data** in the dashboard clears it.

## What to try

1. Actor `agent-assistant`, origin `agent (AI)`, document `doc-003` → **BLOCKED** by clearance.
   The injected "ignore all policies" text changes nothing, because policy never reads document text.
2. Actor `analyst`, `save_report` with sources `doc-004` + `doc-001` → report inherits
   `CONFIDENTIAL` and keeps both provenance ids. Its title is derived, never free text.
3. Same actor, deliver that report to `team@corp.example` → **BLOCKED**, recipient clearance too
   low. Delivered messages stays 0.
4. Same report to `manager@corp.example` → allowed; one message in the mock inbox.
5. Declassification as `analyst` → refused, attempt audited. As `security-officer` with a written
   justification → a new linked copy at the lower level; the original is untouched.
6. Tamper test: edit `classification:` inside `data/documents/doc-003-contract-injection.md`,
   restart the app, try to read it → **BLOCKED** by `RULE-DOC-INTEGRITY`. The document stays frozen
   at its registered label.

## Honesty notes

- There is no login. Identities are bound by the session object, not authenticated.
- The mock inbox is a SQLite table, not email.
- The dashboard's tool-execution counter resets with the process; the audit table is the durable record.
