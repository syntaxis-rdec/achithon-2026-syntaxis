# Makhdum — Notes

## What landed

- `data/eval_documents/` — six clean/hostile pairs, 12 files. Twins share `title`, `classification`
  and `owner`; the hostile body is the clean body plus one attack. Pair 1 is INTERNAL and only
  appends text, so the two bodies differ by exactly the payload.
- `tests/test_injection.py` — 33 tests. A fresh `Store(tmp_path / "inj-NN.sqlite")` per pair, then
  the same three actions through `Session`: agent reads, analyst saves a report citing it, analyst
  delivers to `team@corp.example`.
- The same file also carries the two things the corpus alone cannot give: a substituted-text case
  per label, and two committed mutation checks that prove the assertions go red when the gateway
  misbehaves. See *Findings*.

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
- **The claim is a property, and the pack tests it as one.** `test_labels_decide_and_text_never_does`
  copies each pair's front matter onto five different bodies — its own payload, another pair's
  payload, neutral prose, and a body carrying an HTML comment plus a fake `classification: PUBLIC`
  block — and requires the same three verdicts for all five. Six hand-written twins are a sample;
  this is the thing they were standing in for. The test asserts the five bodies actually differ, so
  it cannot pass by writing the same file five times.
- **Detection power is committed, not recounted.** Two tests break the engine on purpose and require
  this pack to go red. `test_pack_detects_a_policy_that_obeys_document_text` swaps in a
  `policy._check_read` that allows any document whose body contains a payload marker: every twin pair
  and every substituted variant then leaves the pinned expectation. `test_pack_detects_a_redirected_delivery`
  swaps in a `tools.deliver_inbox` that honours an address found in the source text: the three
  allow-path pairs then mail `vendor@outside.example`, which the addressee assertions catch. Both use
  `monkeypatch`, so nothing outside the test process changes and `agentgate/` is never edited.
  Before this, the same check was a one-off in a throwaway copy of the repo and existed only as prose.

## Requests

None blocking. Four notes for the file owners:

- **Core crash on an empty document body.** A document whose body is empty passes every policy check
  and then raises inside the tool, after the gateway has already recorded an ALLOW:
  `agentgate/tools.py:50` does `d.body.splitlines()[0][:120]`, and `splitlines()` on `""` is `[]` →
  `IndexError`. Reproduced against `main` by registering a `Document(body="")` in a temp store and
  submitting `save_report` as `analyst`. Not in this lane, so no test asserts it. Either the loader
  should refuse a bodyless document or the summary should fall back to an empty line.
- `README.md:43` claims `pytest # 42 tests`. It is 75 now: 34 original + 33 from this pack + 8 from
  the workflow-resumption work.
- `team/README.md:41` still states the baseline is **34 passing**, and `team/makhdum/README.md`
  repeats it. Worth one line each so the next lane doesn't chase a stale number.
- `docs/RUN.md` does not mention `data/eval_documents/`. Demo step 3 (Injection) exercises `doc-003`
  in `data/documents/`, so the pack is currently invisible in the walkthrough a judge follows.

## Findings about my own assertions

- `EXPECTED` pins rule ids from `data/policies.json` and clearances from `data/principals.json` — both
  outside this lane. Retuning either file makes three of these tests fail loudly instead of adapting.
  That is deliberate for a security suite, but it makes the pack a tripwire for policy edits, so
  whoever changes a rule should expect it.
- Pairs 03 and 04 carry payloads that ask for actions the prescribed three-step flow never attempts: a
  declassification, and a send to a recipient the actor may not use. Twin equality still holds, but
  those two attacks are not exercised end to end. Closing that needs a fourth flow, which the brief
  does not authorise.
- The mutation checks patch module attributes that `gateway._dispatch` and `policy.evaluate` resolve at
  call time. If either ever binds those helpers at import — `from .tools import deliver_inbox`, say —
  the two detection tests would start asserting against a patch nothing sees, and would fail rather
  than pass quietly. That is the safe direction for a check whose job is to fail.

## Results

- `pytest tests/test_injection.py` — 33 passed.
- `pytest` — **75 passed** against `main` (`dbb97b6`, which already carries the earlier 33 of this
  pack as 25). Breakdown: 34 original, 33 from this lane, 8 from the workflow-resumption work.
- `python -m benchmark.runner` — 32/32 matched, 0 unauthorized executions, 0 false allows.
- `python -m benchmark.mutations` — all six detected.

## Status

Merged into `main` at `dbb97b6` by Tanush. All four lane commits are on `main`:
`b51625d` (corpus + 25 tests), `e51900c` (notes), `7b92fac` (addressee and canary hardening),
`7dc7555` (notes update). `lane/makhdum` was fast-forwarded to `dbb97b6` and re-verified green.

Follow-ups awaiting a merge (both docs-only or lane-only, no core file touched):
`de83503` — merge status and the stale test counts; `9d65bb6` — the substituted-text property and
the two committed mutation checks, which take the pack from 25 to 33 tests.

---

# Task 2 — policy integrity guard and red-team harness

Full write-up: `team/makhdum/REPORT-2.md`. Short version: the rulebook is now pinned at load, a
mid-session swap is denied under `RULE-POLICY-DRIFT` and audited, adoption needs the operator token
and is audited either way, and 21 named attacks run against a copied world.

Two attacks are kept failing as live findings rather than softened: `workflow.resume` builds a
guardless session and honours an unadopted rulebook (LF-1), and a document minted after the pin is
trusted on sight (LF-2). Both are `xfail(strict)` in `tests/test_redteam.py`.

## Requests (task 2)

- **`agentgate/workflow.py` — needs one parameter.** `resume(state, workflow_id, principals_path,
  policies_path, guard=None)` and pass it to the `Session` it constructs at `workflow.py:77`.
  Without it the resume path decides against disk bytes nobody adopted, which is LF-1. `app.py` will
  hand it the registry's guard as soon as the signature allows it. Not in my allowed edit list.
- **`docs/DEMO_SCRIPT.md` / `docs/DEMO_RUNSHEET.md` — one sentence each.** Under
  `AGENTGATE_PIN_RULEBOOK=1` the presenter must type the reload token after
  `python demo/swap_policy.py tighten`; in the default mode nothing changes. The script currently
  promises the swap lands on the next click, which is only true unpinned.
- **`docs/RUN.md`** — the dashboard now reads two env vars: `AGENTGATE_RELOAD_TOKEN` (unset means
  the pin can never be moved) and `AGENTGATE_PIN_RULEBOOK`. Neither is documented.
- `benchmark/` — a drift scenario would make the evidence table cover the guard. The benchmark runs
  guardless by design, so 32/32 says nothing about drift.
- `README.md:43` still says `pytest # 42 tests`. It is 123 passing with 2 strict xfails now.

## Ready to merge (task 2)

- Commits `043f262` (guard + gateway), `088c85f` (dashboard gate), `d86ee28` (adopt/refuse audit
  trail + unit tests), `c035d48` (harness), `8789fcd` (report), `0e97818` (merge of main, app.py and
  log.txt conflicts resolved), `dfc3cd0` (pinned-dashboard test and the merge decision write-up).
  Any commit after `dfc3cd0` on this branch is notes-only.
- `pytest` — **123 passed, 2 xfailed**. Every test that existed before this lane is green with its
  expectations unedited, including the 499 lines of `tests/test_demo_beats.py` merged from main.
- `python -m benchmark.runner` — 32/32, 0 unauthorized, 0 false allows, 0 false denies.
  `benchmark.mutations` — all six detected. `benchmark/` and `agentgate/store.py` schema untouched.
- Task 2's own done-means, item by item: attack 12 denies with `RULE-POLICY-DRIFT` and audits; the
  harness has 21 named attacks; the pin moves only through `reload_rulebook(token)`; every turn is
  in `log.txt`.
