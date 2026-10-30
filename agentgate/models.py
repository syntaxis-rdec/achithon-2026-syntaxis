"""Trusted data shapes for AGENTGATE.

Nothing here reads document content. Untrusted text only ever travels inside
`Document.body` and `Artifact.body`; the policy engine never inspects it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Classification = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
ToolName = Literal["read_document", "save_report", "deliver_inbox"]


class SecurityLabel(BaseModel):
    """Sensitivity plus provenance. Travels with derived artifacts."""

    classification: Classification
    provenance: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class Principal(BaseModel):
    """Anything that can act, or be a delivery recipient."""

    id: str
    kind: Literal["actor", "recipient", "actor_and_recipient"] = "actor_and_recipient"
    role: str = "none"
    clearance: Classification = "PUBLIC"
    allowed_recipients: list[str] = Field(default_factory=list)


class PolicyRule(BaseModel):
    id: str
    role: str
    tool: ToolName
    max_classification: Classification
    description: str = ""


class PolicySet(BaseModel):
    """The trusted policy store. Loaded from disk; no agent can write it."""

    principals: list[Principal]
    rules: list[PolicyRule]

    def principal(self, principal_id: str) -> Principal | None:
        for p in self.principals:
            if p.id == principal_id:
                return p
        return None

    def rules_for(self, role: str, tool: str) -> list[PolicyRule]:
        return [r for r in self.rules if r.role == role and r.tool == tool]


class ActionRequest(BaseModel):
    """One proposed tool call. Produced by a human click or by the agent."""

    actor_id: str
    tool: ToolName
    resource_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    title: str | None = None
    recipient: str | None = None
    note: str = ""
    origin: Literal["human", "agent"] = "human"


class Decision(BaseModel):
    allowed: bool
    rule_id: str
    reason: str
    label: SecurityLabel | None = None


class Document(BaseModel):
    id: str
    title: str
    classification: Classification
    owner: str
    body: str


class Artifact(BaseModel):
    id: str
    title: str
    label: SecurityLabel
    body: str
