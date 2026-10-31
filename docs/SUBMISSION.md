# Submission Checklist — PS08 AGENTGATE

Archithon 2026 — Team 9-11 (Syntaxis)  
Problem Statement: **PS08 AGENTGATE**

---

## 1. What Goes in the Submission Archive

The final submission archive must be a clean `.zip` or `.tar.gz` containing only the repository assets
necessary to run, verify, and inspect the gateway:

- `agentgate/` — core gateway, policy engine, tools, workflow runner, proposer, policy guard, export
- `app.py` — Streamlit interactive stage dashboard
- `benchmark/` — benchmark runner, 32 frozen scenarios, mutation tests
- `redteam/` — 22-attack red team suite and automated attack board
- `web/` — read-only evidence view of the same SQLite file (`python web/app.py`)
- `demo/` — stage seed script, policy swap utility, automated rehearsal engine (`rehearse.py`)
- `data/` — documents, policies, evaluation injection documents
- `docs/` — `RUN.md`, `DEMO_SCRIPT.md`, `DEMO_RUNSHEET.md`, `JUDGE_QA.md`, `PROPOSER.md`, `SUBMISSION.md`
- `tests/` — complete test suite (343 passing, 1 skipped, 0 failures)
- `requirements.txt`, `pytest.ini`, `README.md`, `AGENTS.md`, `log.txt`
- `agent-trace/PS08/<harness>/` — raw, redacted agent transcripts for auditability

---

## 2. What Must NEVER Be Included

Do **NOT** package:
- `.venv/` or any virtual environment directory
- `__pycache__/`, `*.pyc`, `.pytest_cache/`
- Real secrets, tokens, API keys (`sk-*`, `ghp_*`, `Bearer *`, private hex keys)
- Live database binary state (`*.sqlite-wal`, `*.sqlite-shm`, temporary scratch databases)
- Screenshots or binary image recordings (traces must be text/JSON session logs)

---

## 3. Agent Trace Directory Layout

Stage raw agent transcripts under:

```text
agent-trace/
└── PS08/
    ├── qoder/
    │   └── session-trace.jsonl (or session-trace.txt)
    └── antigravity/
        └── session-trace.jsonl
```

### Trace Redaction Rule
Before packaging, ensure all session files are scanned and scrubbed. No keys, passwords, cookies, or
personal identifying tokens may appear in `agent-trace/`. All matches must be replaced with `[REDACTED]`.

---

## 4. Pre-Submission Verification Commands

Run all four verification commands before archiving:

1. **Full Test Suite:**
   ```powershell
   .venv\Scripts\python.exe -m pytest
   ```
   *Expected: 343 passed, 1 skipped, 0 failed.*

2. **Automated Stage Demo Rehearsal:**
   ```powershell
   .venv\Scripts\python.exe demo/rehearse.py
   ```
   *Expected: PASS — 12/12 beats green in < 10s.*

3. **Benchmark Scenarios & Mutations:**
   ```powershell
   .venv\Scripts\python.exe -m benchmark.runner
   .venv\Scripts\python.exe -m benchmark.mutations
   ```
   *Expected: 32/32 scenarios, 0 unauthorized, all 6 mutations detected.*

4. **Red Team Attacks:**
   ```powershell
   .venv\Scripts\python.exe -m redteam
   ```
   *Expected: 22 attacks, 22 held, 0 open findings.*

5. **Evidence Pack Export:**
   ```powershell
   .venv\Scripts\python.exe -m agentgate.export data/agentgate-v3.sqlite exports/
   ```
   *Expected: audit.csv, audit.json, outbox.csv, summary.json generated with zero unredacted secrets.*

