"""Policy integrity: the rulebook is trusted at load time, then watched.

`data/principals.json` and `data/policies.json` are the only things the gateway trusts
completely, so whoever can edit them can grant anything — and the audit trail would
record that abuse as an authorised decision. This module pins both files at load time
and refuses to evaluate against a rulebook that no longer matches the pin.

The fingerprint is built exactly as `policy.load_policy_set` builds
`PolicySet.fingerprint`, so a recorded pin and a loaded rulebook are directly comparable.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from .policy import load_policy_set


class PolicyDrift(Exception):
    """The rulebook on disk is not the one this guard pinned."""

    def __init__(self, expected: str, found: str):
        super().__init__(f"rulebook pinned as {expected} is now {found}")
        self.expected = expected
        self.found = found


def fingerprint(principals_path, policies_path) -> str:
    """One hash over both files, bytes exactly as they are loaded."""
    principals = Path(principals_path).read_bytes()
    rules = Path(policies_path).read_bytes()
    return hashlib.sha256(principals + b"\n" + rules).hexdigest()[:16]


def unadopted_rows(state, guard: "Guard", limit: int = 500) -> list[dict]:
    """Audit rows decided with a rulebook this guard never adopted.

    A session built without a guard, or a code path that re-reads disk on its own, still
    stamps the hash it decided with on every row. That makes an unadopted rulebook
    *findable* even where nothing refused it — which is the honest mitigation for the
    resume path until every entry point takes a guard.
    """
    known = guard.known_hashes()
    return [row for row in state.list_audit(limit=limit) if row["policy_hash"] not in known]


class Guard:
    """A pinned rulebook plus the only door out of that pin: an explicit operator reload."""

    def __init__(self, principals_path, policies_path, token: str | None = None):
        self.principals_path = Path(principals_path)
        self.policies_path = Path(policies_path)
        self.token = token
        self.recorded = fingerprint(self.principals_path, self.policies_path)
        self.reloads: list[tuple[str, str]] = []

    def current(self) -> str:
        return fingerprint(self.principals_path, self.policies_path)

    def known_hashes(self) -> set[str]:
        """Every fingerprint this guard has ever stood behind, adopted or refused into."""
        return {self.recorded} | {new for _, new in self.reloads}

    def check(self) -> str:
        """Return the live fingerprint, or refuse if the rulebook moved under us."""
        try:
            found = self.current()
        except OSError:
            # A deleted or unreadable rulebook is a refusal, not a crash in the decision path.
            raise PolicyDrift(self.recorded, "unreadable") from None
        if found != self.recorded:
            raise PolicyDrift(self.recorded, found)
        return found

    def drift_status(self) -> PolicyDrift | None:
        """Non-raising form, for a dashboard that wants to show the hole it is refusing."""
        try:
            self.check()
        except PolicyDrift as drift:
            return drift
        return None

    def reload(self, token: str | None) -> object:
        """Accept a new rulebook only on the operator's explicit token. Records old and new."""
        if not self.token or not hmac.compare_digest(str(token), str(self.token)):
            raise PermissionError(
                "reload refused: the operator reload token is required and was not supplied")
        try:
            new = self.current()
            loaded = load_policy_set(self.principals_path, self.policies_path)
        except (OSError, ValueError) as exc:
            raise PermissionError(f"reload refused: the rulebook on disk is not usable ({exc})") \
                from exc
        previous = self.recorded
        self.recorded = new
        self.reloads.append((previous, new))
        return loaded
