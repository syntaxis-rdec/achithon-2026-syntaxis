# Makhdum — Injection-Resistance Evidence Pack

Read `team/README.md` first, then the repo-root `AGENTS.md`.

## Context you need

- The product is a security gateway. An AI proposes actions; a separate deterministic policy engine
  decides; blocked actions never reach a tool and never touch the inbox.
- The policy engine **never reads document text**. That is the claim your work proves.
- Documents are markdown files with front matter:

```markdown
---
id: doc-x
title: Some Title
classification: INTERNAL
owner: ops
---
body text here
```

- `classification` must be exactly one of `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`.

## Outcome

A corpus of hostile and clean document pairs, plus a test file proving that changing only the text
never changes a decision.

## Done means

`pytest tests/test_injection.py` passes, and for every pair the clean and the hostile version produce
**the same** verdict and the same rule id.

## Files you own

- `data/eval_documents/` — create it. Do not add documents to `data/documents/` (other tests count them).
- `tests/test_injection.py`
- `team/makhdum/NOTES.md` — your findings, requests, and anything surprising.

## Do not touch

`agentgate/`, `app.py`, `benchmark/`, `data/documents/`, `data/policies.json`, `data/principals.json`.

## What to build

Six pairs, each a clean document and a hostile twin with identical labels and different text:

1. Direct override — "ignore all previous instructions".
2. Fake system directive — a line pretending to be a system message with a new policy.
3. Role impersonation — the document claiming to be from the security officer.
4. Urgency and authority — a deadline plus a named executive demanding release.
5. Obfuscation — base64 or leetspeak payload with a decoding hint.
6. Delimiter confusion — the payload hidden in an HTML comment or a fake front-matter block.

For each pair, run the same three actions:

- agent reads the document
- analyst saves a report citing it
- analyst delivers that report to `team@corp.example`

Assert the verdict and rule id are identical between clean and hostile twins. Use a temporary store
per pair (`Store(tmp_path / "x.sqlite")`), load your folder with
`store.load_documents_from_dir(...)`, and drive actions through `Session(state, policies, actor, origin)`.

## Test skeleton

```python
from agentgate.gateway import Session
from agentgate.models import ActionRequest
from agentgate.policy import load_policy_set
from agentgate.store import Store
```

Create a fresh store per pair so labels and read history never leak between cases.

## If blocked

If a hostile document needs a classification your principals cannot handle, pick one that produces a
clear decision. If something in the core looks wrong rather than your test, write it under
`## Requests` in `NOTES.md` and continue.

## Fallback if time is short

Three pairs instead of six, same assertions. Never relax an assertion to make a test pass.
