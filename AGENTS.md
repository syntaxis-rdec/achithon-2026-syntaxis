# AGENTS.md

Working rules for AI agents in this repository. This repo is the finished solution, not a brief
library: there are no problem-statement files to inspect, and nothing to select or delete.

## What this project is

AGENTGATE — a policy gateway that authorizes AI-proposed tool actions before they execute. Python,
Streamlit, Pydantic, SQLite, pytest. Local only. Start with `README.md`, then `docs/RUN.md`.

## Rules

1. **Log every turn.** Append to `log.txt` at the repo root after each response:

   ```text
   ## [ISO-8601 TIMESTAMP] <short title, max 80 chars>

   User Prompt (verbatim, secrets redacted):
   <the user message>

   Agent Response Summary:
   <2-5 sentences: what changed, why, any decision>

   Actions:
   * <file edited / command run>

   Context:
   tool=<exact harness name>
   problem_id=PS08
   branch=<current branch>
   repo_root=<absolute path>
   ```

   Append only. Never rewrite, reorder, or delete prior entries. One shared log for all agents.

2. **Never log secrets.** Redact keys, tokens, cookies, passwords, private keys, and personal data.

3. **Branch discipline.** `main` is protected. Makhdum works on `lane/makhdum`, Aryan on `lane/aryan`.
   Never commit to `main`, never force-push, never amend, never reset.

4. **Stay in your lane.** Edit only the files your lane owns. If you need a change elsewhere, record it
   under `## Requests` in your `NOTES.md` and continue with a fallback.

5. **Verify before claiming.** Run `.venv\Scripts\python.exe -m pytest` before you commit. The baseline
   is 34 passing. A green claim without a run is not a claim.

6. **Commit small.** `type: what now works`, present tense, no `wip`. Stage files by name, never
   `git add -A` from the root.

## Submission trace

The hackathon may ask for an agent trace. Keep raw session files, never screenshots, redacted for
secrets and personal data, staged under `agent-trace/<harness>/`. Do not commit that folder; package it
at submission time. Aryan owns `docs/SUBMISSION.md`, which records the exact layout.
