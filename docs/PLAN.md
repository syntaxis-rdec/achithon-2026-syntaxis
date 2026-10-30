# AGENTGATE — Build Plan (PS08)

## Demo sentence

A judge watches an AI agent try to send a confidential report to an outside address, sees it blocked before
execution, and reads the exact reason — in under 20 seconds.

## What the specification requires (non-negotiable)

- Three protected tools: document reading, report saving, mock inbox delivery.
- Policy evaluated **before** execution. Blocked actions must never reach the tool.
- Security labels and provenance survive summarising, saving, reloading.
- Restrictions survive workflow resumption (a fresh process).
- Audit trail explaining every decision.
- pytest suite covering authorization, information flow, injection resistance, persistence, audit completeness.
- Optional LLM may propose actions; it must have zero authorization authority.
- Any replay must be clearly labelled as replay, never presented as live execution.

## Architecture in one line

Untrusted content and AI proposals both enter the same deterministic gateway; only the gateway can call tools.

```
actor (human | agent)  ->  ActionRequest  ->  POLICY GATEWAY  ->  tool executes
                              |                   |
                          labels + provenance   Decision(allow|block, rule, reason)
                              |                   |
                          SQLite state <------ audit log
```

## File layout

```
agentgate/
  models.py      ActionRequest, SecurityLabel, Decision, Policy, Principal
  policy.py      evaluate() — the only authorization authority, pure and deterministic
  tools.py       read_document, save_report, deliver_inbox — unreachable except via gateway
  store.py       SQLite: documents, artifacts, workflows, audit, outbox
  labels.py      classification lattice and derived-label rules
  gateway.py     run_action(): evaluate, then execute or block, then audit
  proposer.py    OPTIONAL: turns a sentence into an ActionRequest. No authority.
app.py           Streamlit demo
data/documents/  sample documents, including hostile ones
tests/           pytest
```

## Frozen interface — everyone builds against this, nobody edits someone else's file

```python
# models.py
Classification = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]

class SecurityLabel(BaseModel):
    classification: Classification
    provenance: list[str]          # document ids that fed this artifact
    tags: list[str]

class ActionRequest(BaseModel):
    actor_id: str
    tool: Literal["read_document", "save_report", "deliver_inbox"]
    resource_id: str | None
    recipient: str | None
    note: str = ""

class Decision(BaseModel):
    allowed: bool
    rule_id: str
    reason: str                    # plain English, shown to the judge
    label: SecurityLabel | None

# policy.py
def evaluate(request: ActionRequest, state: Store, policies: list[Policy]) -> Decision: ...

# gateway.py
def run_action(request: ActionRequest, state: Store, policies: list[Policy]) -> tuple[Decision, object | None]:
    """Returns (decision, result). result is None whenever decision.allowed is False."""

# tools.py — never called by app.py or proposer.py directly
def read_document(actor_id: str, doc_id: str, state: Store) -> str: ...
def save_report(actor_id: str, source_doc_ids: list[str], title: str, state: Store) -> str: ...
def deliver_inbox(actor_id: str, artifact_id: str, recipient: str, state: Store) -> str: ...

# labels.py
def combine(labels: list[SecurityLabel]) -> SecurityLabel: ...   # max classification, union of provenance
```

Rules baked into the design:
- A derived report inherits the **highest** classification of its sources and keeps every provenance id.
- Delivery needs both: recipient listed for the actor, and recipient clearance at or above the artifact label.
- Document bodies are never parsed for policy. Text inside a document cannot grant anything.
- Reclassification only through an explicit authorized call, recorded in the audit log.

## Build order and gates

1. **T+0:45 — first meaningful commit.** Contract above, log file, one sample document, gateway returning a
   hardcoded ALLOW for read and BLOCK for delivery. Dashboard renders it.
2. **T+2:00 — real policy evaluation** with three rules, tests green.
3. **T+6:00 — labels, provenance, resumption** demonstrated across a process restart.
4. **T+9:00 — injection suite** with hostile documents; blocked actions proven never to reach tools.
5. **T+15:00 — feature freeze.** Optional LLM proposer only if everything above is done and green.
6. **T+19:00 — backup demo video recorded.**

## Cut list

No login, no user management, no real email, no internet lookups, no decorative charts, no multi-user, no Docker.

## Teammate lanes

- **A — Core:** `agentgate/models.py`, `labels.py`, `policy.py`, `gateway.py`, `tests/test_policy.py`
- **B — Interface:** `app.py`, `agentgate/store.py`, `tests/test_store.py`
- **C — Evidence:** `data/documents/*`, `tests/test_injection.py`, `tests/test_resumption.py`, `docs/DEMO_SCRIPT.md`, `agentgate/proposer.py`

Blocked fallback: if a lane needs a decision from lane A and gets no answer in 10 minutes, code against the
frozen interface above and leave a `# INTERFACE-QUESTION` marker. Do not wait.
