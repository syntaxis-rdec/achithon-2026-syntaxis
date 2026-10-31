# Running AGENTGATE

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python demo/seed.py            # stage the demo: one report, two queued workflows
python web/app.py              # terminal 1: evidence server on :5000 (the dashboard embeds it)
streamlit run app.py           # terminal 2: the dashboard
```

macOS / Linux:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python demo/seed.py
python web/app.py &            # terminal 1: evidence server on :5000
streamlit run app.py           # terminal 2
```

Tests:

```bash
pytest
```

Two processes, two ports. The evidence server prints the read-only view the dashboard embeds in its dark-mode panel; without it that panel is blank and everything else still works. `demo/seed.py` is what gives the workflow beats anything to click, and re-running it is how you reset state.

State lives in `data/agentgate-v3.sqlite`. To reset it, stop the server and run `python demo/seed.py`; the in-page reset button is not reliable on Windows.

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

## Environment switches (all optional, all off by default)

| Variable | Effect |
|---|---|
| `AGENTGATE_DATA_DIR` | Point the dashboard, the demos, the rehearsal and the web viewer at a scratch copy of `data/` instead of the live folder. |
| `AGENTGATE_RELOAD_TOKEN` | The token an operator types to adopt a rulebook that changed on disk. Unset means the pin can never be moved. |
| `AGENTGATE_PIN_RULEBOOK=1` | Keep the rulebook pin across dashboard reruns, so a policy file swapped between clicks is refused under `RULE-POLICY-DRIFT` until adopted. |
| `AGENTGATE_PIN_DOCUMENTS=1` | Also pin the document set, so a document minted or edited after the pin is refused under `RULE-DOCUMENT-DRIFT`. Off by default because the tamper demo edits a document on purpose. |
| `AGENTGATE_WEB_PORT` / `AGENTGATE_WEB_HOST` | Where the read-only evidence server listens; the dashboard iframe assumes 5000. |

## One command per claim

| Claim | Command |
|---|---|
| the suite is green | `pytest` — 344 tests, 343 pass, 1 skipped, 0 failures |
| the frozen table is matched | `python -m benchmark.runner` — 32/32 |
| the table would notice a break | `python -m benchmark.mutations` — 6/6 detected |
| the attacks are refused | `python -m redteam` — 22 of 22 held, none open |
| the demo script actually runs | `python demo/rehearse.py` — 12 beats, exit 0, under 90 s |
| the trail can leave the app | `python -m agentgate.export <db> exports/` |
| the trail can be read in a browser | `python web/app.py` — read-only, every number from SQLite |

`python demo/rehearse.py` exits `1` and names the beat when the demo breaks; add
`--break-rule SAVE-ANALYST` to watch it do that on purpose against a scratch rulebook.

## Honesty notes

- There is no login. Identities are bound by the session object, not authenticated.
- The mock inbox is a SQLite table, not email.
- The dashboard's tool-execution counter resets with the process; the audit table is the durable record.
- Denial reasons name documents by id, never by title, so a block cannot leak what it protects.
