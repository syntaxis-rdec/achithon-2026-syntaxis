# Aryan — Frontend Lane (replaces the export brief)

Branch: `lane/aryan`. Start with `git fetch origin && git merge origin/main`.

You are building the presentation layer. That is fine, but three other people are editing this repo at
once, so the boundaries matter more than the features.

## Hard boundaries — read these twice

- **Do not edit `app.py`.** It is the working demo surface and two other lanes touch it. Build in your own
  folder.
- **Do not edit anything in `agentgate/`, `benchmark/`, `demo/`, `docs/`, or `team/` other than your own
  folder.** Those are owned elsewhere.
- Your files live under **`web/`** plus **`tests/test_web.py`**. Nothing else.
- Push to `lane/aryan` only. Never `main`. Never force-push.

## What to build

`web/` — a presentation layer that reads the same SQLite state the gateway writes and renders:

1. **Decision timeline** — every audit row in order, with the rule id, the actor, the origin, and the
   plain-English reason. Blocked and allowed must be visually obvious.
2. **Label flow** — for each artifact, its classification and the documents it came from.
3. **Inbox panel** — what actually left the building, with the classification that went out.
4. **Workflow panel** — steps, statuses, and the policy fingerprint each decision was made under.
5. **Evidence panel** — read `benchmark/results.json` and show the three headline numbers plus any failing
   scenario. Do not recompute them; display the frozen file.

Read-only. It must never call a tool, never import `agentgate.tools`, and never write to the database.

## How to prove it works

- `tests/test_web.py` asserts the render functions produce the expected rows from a seeded store.
- Boot it headless, fetch the page, and confirm each panel's heading is present. Put the exact command and
  the output you saw in `team/aryan/NOTES.md`.
- A screenshot is not proof that it runs. A command and its output are.

## Still owed from the original brief

`docs/SUBMISSION.md` — the one-page submission checklist. If you are out of time, say so in `NOTES.md` and
someone else takes it. Do not leave the README pointing at a file that does not exist.

## Done means

`pytest` passes with all existing tests green, your page boots, and `log.txt` has an entry for every turn
with your real harness name in `tool=`.
