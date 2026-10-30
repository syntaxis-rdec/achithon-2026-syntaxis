"""One session per actor, reused across dashboard clicks.

Without this, every click builds a fresh session and the read history that stops
source-hiding is silently reset.
"""

from __future__ import annotations

from .gateway import Session


class SessionRegistry:
    def __init__(self, state, policies):
        self.state = state
        self.policies = policies
        self._sessions: dict[tuple[str, str], Session] = {}

    def get(self, actor_id: str, origin: str = "human") -> Session:
        key = (actor_id, origin)
        if key not in self._sessions:
            self._sessions[key] = Session(self.state, self.policies, actor_id, origin)
        return self._sessions[key]

    def refresh(self, policies) -> None:
        """Keep a reused session honest: it must evaluate against the policy on disk now."""
        self.policies = policies
        for session in self._sessions.values():
            session.policies = policies

    def clear(self) -> None:
        self._sessions.clear()
