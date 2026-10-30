# Submitting PS08 — AGENTGATE

One page. Everything here is checkable from a clean clone; the numbers are the ones the repository
prints today.

## Before you package: four commands, all green

```bash
python -m venv .venv && .venv/Scripts/activate     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pytest                                    # 225 tests: 224 pass, 1 documented xfail
python -m benchmark.runner                # 32/32 scenarios, 0 unauthorized, 0 false allows
python -m benchmark.mutations             # 6/6 deliberate breakages detected
python -m redteam                         # 22 attacks: 21 held, 1 open finding (LF-2)
python demo/rehearse.py                   # 12/12 stage-demo beats, under 90 seconds
```

If any of those differs from the number above, stop and read `team/*/REPORT-*.md` before submitting:
every deviation is either documented as an open finding or is a regression.

## What goes in the archive

```
agentgate/        gateway, policy, labels, tools, store, sessions, workflow, proposer, guard, export
app.py            the Streamlit dashboard
benchmark/        scenarios.json, runner, mutations, results.json (the frozen table)
data/             principals.json, policies.json, documents/, eval_documents/
demo/             seed.py, swap_policy.py, policies_default.json, policies_tight.json, rehearse.py
redteam/          attacks.py, results.json
tests/            the suite, including the export, guard, red-team and rehearsal tests
docs/             RUN, DEMO_SCRIPT, DEMO_RUNSHEET, JUDGE_QA, PROPOSER, SUBMISSION, PLAN
team/             lane briefs and the three reports (NOTES/REPORT files)
README.md  AGENTS.md  requirements.txt  pytest.ini  log.txt
```

Keep `benchmark/results.json` and `redteam/results.json`: they are the frozen evidence, not build output.

## What never goes in the archive

- `.venv/`, `__pycache__/`, `.pytest_cache/` — rebuildable, large, and machine-specific.
- Any `*.sqlite` or `*.db` — live state, may contain the staged demo report and the audit trail.
- `.env`, `.env.*`, `AGENTGATE_MODEL_KEY`, any `sk-`/`ghp_`/`Bearer` value. If a key was ever typed into
  the dashboard, run the export guard below before packaging anything.
- Screenshots. The trace is text.
- Anything under `exports/` unless the submission form asks for attachments — it is derived data, and
  the model key is redacted, not absent.
- Personal data: home directories, usernames in paths, browser profile paths.

## The agent trace

```
agent-trace/
└── PS08/
    └── <harness>/            e.g. qoder-desktop/
        ├── session-01.txt    raw turn log: prompt, actions, commands
        └── README.txt        harness name and version, which model, one line per session
```

Rules:

1. Raw session files, never screenshots. One file per session, appended in order.
2. Redact before copying: keys, tokens, cookies, `.env` values, home paths. The pattern list the
   project already enforces is `sk-…`, `ghp_…`, `Bearer …`, `eyJ…` (a bare JWT), and any run of 32+
   hex characters. Replace the whole match with `[REDACTED]`, never just the prefix.
3. `agent-trace/` is git-ignored. It is packaged at submission time, not committed.

## Audit export, if evidence is requested as data

```bash
python -m agentgate.export data/agentgate-v3.sqlite exports/
```

Writes `audit.csv`, `audit.json`, `outbox.csv`, `summary.json`, prints one line, creates the directory
if missing. Every string field is scanned for the secret shapes above before writing, and
`summary.json` records how many replacements were made (`redactions`) plus a `fingerprint` over the
three data files, so a reviewer can tell two packs apart. Seeded demo database: 1 decision, 1 artifact,
0 messages — use a database you actually drove if you want the export to show the demo.

## Final checklist

- [ ] Clean clone, `pip install -r requirements.txt`, all six commands above reproduce.
- [ ] `python -m agentgate.export` on the database you are shipping leaves every audit row readable.
- [ ] Archive contains no `.venv`, no `*.sqlite`, no `.env`, no screenshots.
- [ ] `agent-trace/PS08/<harness>/` present in the package, redacted, not committed.
- [ ] `docs/JUDGE_QA.md` read once out loud: no claim contradicts the code.
- [ ] Known limits stated, not hidden: LF-2 (a document minted after the policy pin is trusted on
      sight), the guard being opt-in per session, and the demo script's stale fingerprint note in
      `team/makhdum/REPORT-3.md`.
