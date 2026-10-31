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
    """A pinned input on disk is not the one this guard pinned.

    `kind` is "rulebook" or "documents"; the gateway turns it into the rule id, so a reviewer can
    tell a swapped policy file from a document that appeared or changed after the pin.
    """

    def __init__(self, expected: str, found: str, kind: str = "rulebook"):
        super().__init__(f"{kind} pinned as {expected} is now {found}")
        self.expected = expected
        self.found = found
        self.kind = kind


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


def documents_fingerprint(directory: str | Path) -> str:
    """One hash over the whole document set: each file's name and bytes, in sorted order.

    The store fingerprints each document on its own, which catches an edit to a registered file.
    It cannot see a file that was never registered, so a document minted after the pin is trusted
    on sight. Pinning the set closes that. Names and lengths are written first so two different
    file sets can never hash the same way by running their bytes together.
    """
    digest = hashlib.sha256()
    for file in sorted(Path(directory).glob("*.md")):
        name = file.name.encode("utf-8")
        body = file.read_bytes()
        digest.update(f"{len(name)}:".encode("utf-8") + name)
        digest.update(f"{len(body)}:".encode("utf-8") + body)
    return digest.hexdigest()[:16]


class Guard:
    """A pinned rulebook (and optionally the document set) plus the only door out of the pin."""

    def __init__(self, principals_path, policies_path, token: str | None = None,
                 documents_path: str | Path | None = None):
        self.principals_path = Path(principals_path)
        self.policies_path = Path(policies_path)
        self.documents_path = Path(documents_path) if documents_path is not None else None
        self.token = token
        self.recorded = fingerprint(self.principals_path, self.policies_path)
        self.pinned_documents = documents_fingerprint(self.documents_path) if self.documents_path else ""
        self.reloads: list[tuple[str, str]] = []

    def current(self) -> str:
        return fingerprint(self.principals_path, self.policies_path)

    def current_documents(self) -> str:
        if self.documents_path is None:
            return self.pinned_documents
        return documents_fingerprint(self.documents_path)

    def known_hashes(self) -> set[str]:
        """Every fingerprint this guard has ever stood behind, adopted or refused into."""
        return {self.recorded} | {new for _, new in self.reloads}

    def check(self) -> str:
        """Return the live fingerprint, or refuse if a pinned input moved under us."""
        try:
            found = self.current()
        except OSError:
            # A deleted or unreadable rulebook is a refusal, not a crash in the decision path.
            raise PolicyDrift(self.recorded, "unreadable") from None
        if found != self.recorded:
            raise PolicyDrift(self.recorded, found)
        if self.documents_path is not None:
            try:
                now = self.current_documents()
            except OSError:
                raise PolicyDrift(self.pinned_documents, "unreadable", kind="documents") from None
            if now != self.pinned_documents:
                raise PolicyDrift(self.pinned_documents, now, kind="documents")
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
        self.pinned_documents = self.current_documents()
        self.reloads.append((previous, new))
        return loaded
