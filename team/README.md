# Lanes

Two independent lanes, each owned by one person. The core gateway is frozen while the resumption
work lands, so neither lane edits `agentgate/` internals, `app.py`, or `benchmark/`.

| Person | Lane | Folder | Branch |
|---|---|---|---|
| Makhdum | Injection-resistance evidence pack | `team/makhdum/` | `lane/makhdum` |
| Aryan | Audit export and submission packaging | `team/aryan/` | `lane/aryan` |

`main` belongs to Tanush. Never commit or push to `main`. Work only on your lane branch.

## Branch workflow

```bash
git fetch origin
git switch lane/makhdum          # or lane/aryan
git pull --ff-only origin lane/makhdum
# ... do the work, commit small ...
git push origin lane/makhdum
```

When your lane is green and you want it merged, add a line to `team/<name>/NOTES.md` under
`## Ready to merge` with the commit hash and the test count. Tanush merges. You do not merge.

If `main` has moved ahead, bring it in without rewriting anything:

```bash
git fetch origin
git merge origin/main            # never rebase, never force-push
```

## Rules for both lanes

- Read the top-level `AGENTS.md` first. The problem statement is already chosen: **PS08 AGENTGATE**.
  Do not delete, move, or clean any `PS##.md` file.
- Append a `## [timestamp] <title>` entry to the repo-root `log.txt` after every turn, with a
  non-empty `tool=` line naming your exact harness. Never log secrets. Log conflicts are expected;
  keep both entries and commit the merge.
- Run the test suite with `.venv\Scripts\python.exe -m pytest` (Windows) or `.venv/bin/python -m pytest`.
  All existing tests must still pass before you commit. Baseline: **34 passing**.
- Own only your files. If you need a change in someone else's file, write it in your own `NOTES.md`
  under a `## Requests` heading and continue with a fallback.
- Commit small, with `type: what works` messages. Never amend, never force-push, never reset.
- Do not run `git add -A` from the repo root; stage the files you own by name.
