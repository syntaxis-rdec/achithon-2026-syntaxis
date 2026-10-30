# Makhdum — Notes

## What landed

- `data/eval_documents/` — six clean/hostile pairs, 12 files. Twins share `title`, `classification`
  and `owner`; the hostile body is the clean body plus one attack. Pair 1 is INTERNAL and only
  appends text, so the two bodies differ by exactly the payload.
- `tests/test_injection.py` — 25 tests. A fresh `Store(tmp_path / "inj-NN.sqlite")` per pair, then
  the same three actions through `Session`: agent reads, analyst saves a report citing it, analyst
  delivers to `team@corp.example`.

Pairs: 01 direct override (INTERNAL), 02 fake system directive (CONFIDENTIAL), 03 role impersonation
(INTERNAL), 04 urgency and authority (CONFIDENTIAL), 05 base64 with a decode hint (CONFIDENTIAL),
06 HTML comment plus a fake front-matter block (INTERNAL).

## Why the classifications differ per pair

Both the allow path and the deny path have to be shown to be text-blind, so the corpus covers both:

| Classification | read (agent) | save (analyst) | deliver → team@ |
|---|---|---|---|
| INTERNAL | allowed, `READ-AGENT` | allowed, `SAVE-ANALYST` | allowed, `SEND-ANALYST` |
| CONFIDENTIAL | blocked, `RULE-READ-CLEARANCE` | allowed, `SAVE-ANALYST` | blocked, `RULE-RECIPIENT-CLEARANCE` |

The expected rows are pinned in `EXPECTED`, so "identical" cannot degrade into "identical because
both twins were blocked for unrelated reasons".

## Findings

- **Body-level front matter is inert.** Pair 06 puts a second `classification: PUBLIC` block inside
  the body. `_parse_front_matter` only looks at a `---` block starting on line 0, so the document
  registers as INTERNAL and `integrity` stays `ok`. Confirmed in `test_pair_differs_only_in_text`.
- **Denial reasons name identifiers, never text.** Across 36 decisions on hostile documents, no
  payload marker appears in `rule_id`, `reason` or `label`. That is the claim stated as an assertion.
- **Delivery is checked by addressee, not by count.** The first cut of the pack asserted two outbox
  rows and six executions for the allow path. A gateway that obeyed a payload and mailed
  `vendor@outside.example` instead of `team@corp.example` would have satisfied both counts. The tests
  now compare the recipient string in the outbox row and in `tools.EXECUTIONS`.
- **Canary wording matters.** Pair 03 originally used `security-officer` as its marker, but that is
  trusted vocabulary: the declassification refusals in `agentgate/gateway.py` put the literal string
  `does not hold the security-officer role` into an audit reason. Any later flow touching
  declassification would have failed the pack for the wrong reason, so the marker is now a phrase
  only the hostile body contains.
- **The report body does carry source text.** `tools.save_report` writes
  `d.body.splitlines()[0][:120]` into the artifact, while the title is derived from doc ids only. So
  text reaches the artifact body — but it stays under the inherited label and provenance, so it
  cannot leave through a recipient the policy rejects. Not a defect, worth knowing when reading the
  "policy never reads document text" line: policy never reads it; the tool copies one line of it.
  Every payload sits after the first line of its body, so asserting the payload stays out of the
  artifact body would have been true by corpus layout rather than by any property of the gateway.
  That assertion is gone; the addressee assertion replaced it.
- **Read history is per actor, and the flow depends on it.** `submit` merges `reads_for(actor)` into
  `save_report` sources. The pack keeps the agent as the reader and the analyst as the saver, so the
  save cites exactly the document under test and the two twins stay comparable.
- **The tests are not vacuous.** In a throwaway copy of the repo I patched `evaluate` to obey
  `vendor@outside.example` found in document text. 10 of the 25 tests failed (twin equality, pinned
  expectations, payload-in-decision, execution barrier). The same patch in `agentgate/` here would
  be a lane violation, so the check was run outside the repo and the copy was deleted.

## Requests

None blocking. Three notes for the file owners:

- `README.md:43` claims `pytest # 42 tests`. It is 67 on `main` now: 34 original + 25 from this pack
  + 8 from the workflow-resumption work. The 25 from this lane were never counted.
- `team/README.md:41` still states the baseline is **34 passing**, and the brief in
  `team/makhdum/README.md` repeats it. Worth one line each so the next lane doesn't chase a stale
  number.
- `docs/RUN.md` does not mention `data/eval_documents/`. Demo step 3 (Injection) exercises `doc-003`
  in `data/documents/`, so the pack is currently invisible in the walkthrough a judge follows.

## Findings about my own assertions

- `EXPECTED` in the test file pins rule ids straight out of `data/policies.json` and clearance levels
  from `data/principals.json`. Both files are outside this lane. If either is retuned, three of these
  tests fail loudly rather than silently adapting. That is intentional for a security suite, but it
  makes this pack a tripwire for policy edits — whoever changes a rule should expect it.
- Pairs 03 and 04 carry payloads that ask for actions the prescribed three-step flow never attempts
  (a declassification, and a send to a non-approved recipient). Twin equality holds, but those two
  attacks are not "live" in the flow. Closing it needs a fourth flow, which is outside the brief.

## Results

- `pytest tests/test_injection.py` — 25 passed.
- `pytest` — 59 passed on the lane before merge; **67 passed** after merging `origin/main`, which
  added the workflow-resumption suite. The pack is unaffected by `agentgate/workflow.py`.
- `python -m benchmark.runner` — 32/32 matched, 0 unauthorized executions, 0 false allows.
- `python -m benchmark.mutations` — all six detected.

## Status

Merged into `main` at `dbb97b6` by Tanush. All four lane commits are on `main`:
`b51625d` (corpus + 25 tests), `e51900c` (notes), `7b92fac` (addressee and canary hardening),
`7dc7555` (notes update). `lane/makhdum` was fast-forwarded to `dbb97b6` and re-verified green.
