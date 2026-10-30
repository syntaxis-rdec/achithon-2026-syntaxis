"""One session per actor, reused across dashboard clicks.

Without this, every click builds a fresh session and the read history that stops
source-hiding is silently reset.

With a Guard attached, adopting a different rulebook stops being an accident: `refresh`
only accepts the rulebook the guard has just re-pinned, and the only way to re-pin it is
`reload_rulebook(token)`.
"""

from __future__ import annotations

from .gateway import Session
from .policy_guard import Guard


class SessionRegistry:
    def __init__(self, state, policies, guard: Guard | None = None):
        self.state = state
        self.policies = policies
        self.guard = guard
        self._sessions: dict[tuple[str, str], Session] = {}

    def get(self, actor_id: str, origin: str = "human") -> Session:
        key = (actor_id, origin)
        if key not in self._sessions:
            self._sessions[key] = Session(self.state, self.policies, actor_id, origin, self.guard)
        return self._sessions[key]

    def refresh(self, policies) -> None:
        """Keep a reused session honest: it must evaluate against the policy on disk now."""
        if self.guard is not None and policies.fingerprint != self.guard.recorded:
            raise PermissionError(
                "a guarded registry adopts a rulebook only through reload_rulebook(token)")
        self.policies = policies
        for session in self._sessions.values():
            session.policies = policies

    def reload_rulebook(self, token: str | None):
        """The explicit door. Operator token in, new rulebook live for every session."""
        if self.guard is None:
            raise PermissionError("this registry has no policy guard to reload through")
        previous = self.guard.recorded
        try:
            policies = self.guard.reload(token)
        except PermissionError as exc:
            self.state.record_audit(
                actor="operator", origin="human", tool="reload_policy", resource=None,
                recipient=None, allowed=False, rule_id="RULE-POLICY-RELOAD-REFUSED",
                reason=f"Blocked: {exc} The pinned rulebook {previous} is still in force.",
                label=None, policy_hash=previous)
            raise
        self.refresh(policies)
        self.state.record_audit(
            actor="operator", origin="human", tool="reload_policy", resource=None,
            recipient=None, allowed=True, rule_id="POLICY-RELOAD",
            reason=(f"Allowed: the operator adopted the rulebook on disk. "
                    f"Pin moved {previous} to {policies.fingerprint}."),
            label=None, policy_hash=policies.fingerprint)
        return policies

    def clear(self) -> None:
        self._sessions.clear()
