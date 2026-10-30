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

1. `python -m benchmark.runner` runs 32 frozen scenarios and writes `benchmark/results.json`.
2. `python -m benchmark.mutations` breaks the gateway six ways and checks that the suite notices.
3. `python -m redteam` runs 22 adversarial attack vectors (prompt injections, unauthorized roles,
   data exfiltration, policy drift) and outputs `redteam/results.json`.
4. `python demo/rehearse.py` headlessly rehearses all 12 beats in `docs/DEMO_SCRIPT.md` via Streamlit
   `AppTest` in under 6 seconds, asserting all promised strings and exit 0.
5. `python -m agentgate.export data/agentgate-v3.sqlite exports/` exports the live database into
   `audit.csv`, `audit.json`, `outbox.csv`, and `summary.json` with automatic secret redaction.

Dashboard section 4 shows the benchmark and red team attack board live.

## Environment Variables

- `AGENTGATE_PIN_RULEBOOK=1`: enforces cryptographic rulebook pinning in the dashboard. When set,
  any out-of-band change to `data/policies.json` halts execution with `RULE-POLICY-DRIFT` until
  explicitly adopted.
- `AGENTGATE_RELOAD_TOKEN`: the secret authorization token required to adopt an updated rulebook
  under pinned mode.
- `AGENTGATE_DATA_DIR`: override the data directory (used by the test suite and rehearsal to run in a
  clean scratch environment without touching live state).

## Honesty notes

- There is no login. Identities are bound by the session object, not authenticated.
- The mock inbox is a SQLite table, not email.
- The dashboard's tool-execution counter resets with the process; the audit table is the durable record.
- Denial reasons name documents by id, never by title, so a block cannot leak what it protects.
