# The proposer

`agentgate/proposer.py` turns one English sentence into ordered `ActionRequest` objects.
It is a convenience layer with **zero authority**:

- it does not evaluate policy;
- it does not call a tool;
- it cannot change a security label;
- it cannot choose who is asking.

Every proposal still goes through `agentgate.gateway.Session.submit`, which binds the
session's actor and origin, evaluates the rulebook from disk, and only then executes.
Turning the proposer off removes typing convenience and nothing else: the gateway, the
policy engine, the labels, the audit trail and the workflows behave exactly as before.

## API

```python
from agentgate.gateway import Session
from agentgate.policy import load_policy_set
from agentgate.proposer import propose
from agentgate.store import Store

state = Store("data/agentgate-v3.sqlite")
policies = load_policy_set("data/principals.json", "data/policies.json")
session = Session(state, policies, "analyst", origin="agent")

proposal = propose("summarise doc-002 and doc-004",
                   session=session, state=state, policies=policies)
for action in proposal.actions:
    decision, result = session.submit(action)
```

`proposal.backend` is `"scripted"` or `"model"`. When the proposer declines, `actions`
is empty and `proposal.refusal` holds a plain-English reason.

## Two backends, one interface

### Scripted — the default, always offline

A deterministic parser. It only accepts sentence shapes it fully understands; anything
else is refused rather than guessed at.

| Sentence | Proposal |
|---|---|
| `read doc-004` | `read_document` doc-004 |
| `read doc-004 and doc-002` | two `read_document` actions |
| `summarise doc-002 and doc-004` | `save_report` with both sources, in order |
| `write a report from doc-002` | `save_report` from doc-002 |
| `summarise all documents` | `save_report` from every registered document |
| `send report-abc123 to manager@corp.example` | `deliver_inbox` that report |
| `send the report to manager@corp.example` | `deliver_inbox` the latest saved report |
| `send everything to vendor@outside.example` | one `deliver_inbox` per saved report |
| `send the revenue brief to manager@corp.example` | the saved report that uniquely matches source titles |
| `send doc-004 to manager@corp.example` | **refused**: a document is not deliverable directly |
| `make me a sandwich` | **refused** |

Politeness (`please`, `can you`), identity wording (`as security-officer`,
`origin=human`, `I am ...`) and known hostile preambles (`ignore policy and ...`) are
removed before parsing. Removing them never grants anything: the identity stamp is
described below, and the remainder is still just a sentence.

#### Which report does "the report" mean?

Resolution is deterministic, in this order:

1. an explicit saved-report id (`report-abc123`);
2. `the report`, `the latest report`, `the last report` → the most recently saved report;
3. `everything`, `all reports` → every saved report;
4. another description → the unique saved report whose title, or whose source documents'
   titles, contain one of the description's words;
5. no reports, no unique match, or more than one match → **refusal**.

The proposer never silently picks "some report". A description match is a metadata
lookup, not content matching: it reads titles and provenance ids, never document bodies.
If it is ambiguous, name the id or say "the latest report".

#### Identity is the session's

`propose()` reads `session.actor_id` and stamps every action with it plus
`origin="agent"`. Anything the sentence says about who is asking, or which origin it
claims, is discarded before parsing. A caller cannot pass an actor in the sentence to
change the proposal, and `Session.submit` would overwrite the fields anyway.

#### Release is not expressible

Sentences that ask to lower, raise, set or mark a classification (`declassify`,
`lower the classification`, `mark this public`, ...) receive a fixed refusal and no
actions. This check runs before either backend, so a configured model is not consulted.
The module never imports, references or calls `gateway.declassify`; release remains a
human security-officer function that is not a tool and has no route from here.

### Model — optional, off by default

Set both variables to enable it:

```powershell
$env:AGENTGATE_MODEL_BASE_URL = "https://your-endpoint/v1/chat/completions"
$env:AGENTGATE_MODEL_KEY = "..."          # or your local endpoint's key
$env:AGENTGATE_MODEL_NAME = "gpt-4o-mini" # optional, this is the default
```

The base URL is used as given and must accept an OpenAI-compatible chat-completions
POST. Only the standard library is used (`urllib.request`); there are no new
dependencies. If either the URL or the key is missing, the scripted backend runs.

What is sent: the sentence, plus a fixed identifier vocabulary — document ids, saved
report ids, actor ids and recipient ids — plus a fixed instruction describing the three
tools. Document titles, bodies, classifications, policy text and the key are **not** in
the request body. The key travels only in the `Authorization` header, is never logged,
and is kept out of `repr(ModelConfig)`, the `Proposal` and the audit trail.

What comes back is untrusted input. The reply must be a JSON object of the form:

```json
{"actions": [
  {"tool": "read_document", "resource_id": "doc-004"},
  {"tool": "save_report", "source_ids": ["doc-002", "doc-004"]},
  {"tool": "deliver_inbox", "resource_id": "report-abc123", "recipient": "manager@corp.example"}
]}
```

Every action is checked against the local vocabulary and the trusted directory before it
becomes a proposal:

- malformed JSON, a non-object, or no `actions` list → refused;
- an empty action list, more than 20 actions → refused;
- an unknown tool, a field that is not part of the schema, or fields mixed across tools
  (a recipient on a read, sources on a delivery) → refused;
- an unknown document, report or recipient → refused;
- `actor_id` or `origin` keys are accepted but **ignored**; the session's actor and
  `origin="agent"` are stamped on afterwards.

Two failure modes are deliberately different:

- **The call itself failed** (transport error, HTTP error, unreadable envelope): fall
  back to the scripted parser and label the result `backend="scripted"`.
- **A reply arrived but broke the contract**: refuse it. The model's content is never
  executed and is never silently replaced by a different interpretation, because an
  anomalous reply is exactly what a substituted parser could hide.

A model proposal is still only a proposal. If it asks to read a document above the
actor's clearance or to send to a recipient the rulebook forbids, the gateway blocks it
like any other request.

## Command line

```bash
python -m agentgate.proposer "send the revenue brief to vendor@outside.example"
python -m agentgate.proposer --actor analyst "read doc-004"
python -m agentgate.proposer --db data/agentgate-v3.sqlite --actor analyst "summarise doc-001"
```

The CLI prints the sentence, which backend parsed it, every proposed action with its
actor and origin, and then the gateway's decision for each action against the current
state file. Allowed actions execute through `Session.submit`, exactly as in the
dashboard; blocked ones do not. The state file defaults to the dashboard's
`data/agentgate-v3.sqlite`; an empty one is seeded with the four sample documents.
Declassification is not reachable from the CLI either.

Exit codes: `0` when decisions were printed (allowed **or** blocked), `2` when the
proposer refused and nothing was submitted, `3` for a bad state file or actor.

A delivery needs a saved report. On a fresh state file the exact command above refuses
with the one-line command that creates one:

```bash
python -m agentgate.proposer --actor analyst "summarise doc-001"
```

Then rerun the send. This is the honest behaviour: there is nothing to send yet, so the
proposer does not invent a target. Once the report exists, the same command produces a
`deliver_inbox` proposal and the gateway blocks it with
`RULE-RECIPIENT-NOT-PERMITTED`.

## Limits, stated plainly

- **Convenience, not authority.** The proposer can be wrong, vague or unavailable. The
  policy engine, not the proposer, decides. A wrong proposal that the policy still
  permits is the residual risk; name the report id when it matters.
- **No chaining of outputs.** A proposal cannot refer to a report that the same
  proposal would create. "Read this, summarise it, send the summary" is a workflow
  (`agentgate/workflow.py`), not a sentence the proposer invents ids for.
- **The description lookup is best-effort.** It refuses on ambiguity, but if you want a
  specific report, use its id.
- **The model can be wrong or hostile.** Its reply is data, validated and then decided
  by the gateway. Identity and release claims inside it are ignored or refused.
- **Identifiers leave the machine on the model path.** No content leaves, but document
  and report ids do. If identifiers themselves are sensitive in your setting, leave the
  model path off; the scripted backend is the default.
- **The model path is optional and silent on failure.** A transport failure downgrades to
  scripted and says so through `backend="scripted"`; there is no retry queue.
- **The CLI executes allowed actions.** It is a thin gateway client, not a dry run.
  Point `--db` at a copy if you want to explore without touching demo state.

## Tests

`tests/test_proposer.py` pins the parsing, refusals, identity binding, release refusal,
model-payload hygiene, key handling, untrusted-reply rejection, scripted fallback, the
hostile-sentence block, and the CLI. Run:

```bash
pytest tests/test_proposer.py
```
