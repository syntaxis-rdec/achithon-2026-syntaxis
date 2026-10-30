# Lanes

Two independent lanes, each owned by one person. The core gateway is frozen while the resumption
work lands, so neither lane edits `agentgate/` internals, `app.py`, or `benchmark/`.

| Person | Lane | Folder |
|---|---|---|
| Makhdum | Injection-resistance evidence pack | `team/makhdum/` |
| Aryan | Audit export and submission packaging | `team/aryan/` |

Rules for both lanes:

- Read the top-level `AGENTS.md` first. The problem statement is already chosen: **PS08 AGENTGATE**.
  Do not delete, move, or clean any `PS##.md` file.
- Append a `## [timestamp] <title>` entry to the repo-root `log.txt` after every turn, with a
  non-empty `tool=` line naming your exact harness. Never log secrets.
- Run the test suite with `.venv\Scripts\python.exe -m pytest` (Windows) or `.venv/bin/python -m pytest`.
  All existing tests must still pass before you commit.
- Own only your files. If you need a change in someone else's file, write it in your own `NOTES.md`
  under a `## Requests` heading and continue with a fallback.
- Commit small, with `type: what works` messages. Never amend or force-push.
