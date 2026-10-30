"""Canary Honeytoken & Paraphrase Exfiltration Trap for AGENTGATE.

Provides CanaryRegistry and CanaryTrap to generate, register, and embed honeytokens
into documents, and detect data exfiltration (exact canary leaks and paraphrased content)
in outgoing messages and reports based on an actor's read history.
"""

from __future__ import annotations

import re
import secrets
from typing import Any, Iterable


class CanaryRegistry:
    """Registry for generating, storing, and matching document canary honeytokens."""

    def __init__(self) -> None:
        self._canaries_by_doc: dict[str, list[str]] = {}
        self._doc_by_canary: dict[str, str] = {}
        self._phrases_by_doc: dict[str, list[str]] = {}

    def register(self, doc_id: str, token: str) -> None:
        """Register a honeytoken mapped to a sensitive document ID."""
        if doc_id not in self._canaries_by_doc:
            self._canaries_by_doc[doc_id] = []
        if token not in self._canaries_by_doc[doc_id]:
            self._canaries_by_doc[doc_id].append(token)
        self._doc_by_canary[token] = doc_id

    def register_canary(self, doc_id: str, token: str) -> None:
        """Alias for register."""
        self.register(doc_id, token)

    def generate_canaries_for_doc(
        self, doc_id: str, count: int = 1, prefix: str = "CANARY"
    ) -> list[str]:
        """Generate, register, and return unique honeytokens for a document.

        Format: {prefix}-{doc_id}-{token_suffix}
        """
        if count < 1:
            return []
        tokens: list[str] = []
        for _ in range(count):
            while True:
                suffix = secrets.token_hex(4)
                candidate = f"{prefix}-{doc_id}-{suffix}"
                if candidate not in self._doc_by_canary:
                    break
            self.register(doc_id, candidate)
            tokens.append(candidate)
        return tokens

    def get_canaries_for_doc(self, doc_id: str) -> list[str]:
        """Return all canaries registered for a given document ID."""
        return list(self._canaries_by_doc.get(doc_id, []))

    def get_doc_for_canary(self, token: str) -> str | None:
        """Return the document ID mapped to the given canary token, or None."""
        return self._doc_by_canary.get(token)

    def all_canaries(self) -> dict[str, str]:
        """Return a mapping of all canary tokens to their document IDs."""
        return dict(self._doc_by_canary)

    def register_sensitive_phrase(self, doc_id: str, phrase: str) -> None:
        """Register a sensitive sentence or phrase for paraphrase exfiltration tracking."""
        phrase_clean = phrase.strip()
        if not phrase_clean:
            return
        if doc_id not in self._phrases_by_doc:
            self._phrases_by_doc[doc_id] = []
        if phrase_clean not in self._phrases_by_doc[doc_id]:
            self._phrases_by_doc[doc_id].append(phrase_clean)

    def register_sensitive_text(self, doc_id: str, text: str, min_words: int = 4) -> None:
        """Extract meaningful sentence-level phrases from text and register them."""
        sentences = re.split(r"[.\n;!?]+", text)
        for sentence in sentences:
            s = sentence.strip()
            if s.startswith("---") or (":" in s and len(s.split()) <= 2):
                continue
            words = [w for w in re.findall(r"\w+", s) if len(w) > 1]
            if len(words) >= min_words:
                self.register_sensitive_phrase(doc_id, s)

    def get_phrases_for_doc(self, doc_id: str) -> list[str]:
        """Return registered sensitive phrases for a document ID."""
        return list(self._phrases_by_doc.get(doc_id, []))

    def check_canary_leak(self, text: str, read_docs: Iterable[str]) -> list[str]:
        """Scan text for any canary token associated with any document the actor has read."""
        return check_canary_leak(text, read_docs, registry=self)

    def check_paraphrase_leak(
        self,
        text: str,
        read_docs: Iterable[str],
        threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Check outgoing text for paraphrased sensitive content from read documents."""
        return check_paraphrase_leak(text, read_docs, registry=self, threshold=threshold)

    def clear(self) -> None:
        """Clear all registered tokens and phrases."""
        self._canaries_by_doc.clear()
        self._doc_by_canary.clear()
        self._phrases_by_doc.clear()


class CanaryTrap(CanaryRegistry):
    """Canary Honeytoken & Paraphrase Exfiltration Trap.

    Extends CanaryRegistry with high-level threat auditing across both exact
    honeytoken matches and semantic paraphrase exfiltration.
    """

    def scan(
        self,
        text: str,
        read_docs: Iterable[str],
        paraphrase_threshold: float = 0.5,
    ) -> dict[str, Any]:
        """Audit text for both exact honeytoken leaks and paraphrased content."""
        canary_leaks = self.check_canary_leak(text, read_docs)
        paraphrase_leaks = self.check_paraphrase_leak(
            text, read_docs, threshold=paraphrase_threshold
        )
        leaked_docs: set[str] = set()
        for token in canary_leaks:
            doc_id = self.get_doc_for_canary(token)
            if doc_id:
                leaked_docs.add(doc_id)
        for match in paraphrase_leaks:
            leaked_docs.add(match["doc_id"])

        return {
            "has_leak": bool(canary_leaks or paraphrase_leaks),
            "exact_canaries": canary_leaks,
            "paraphrase_matches": paraphrase_leaks,
            "compromised_docs": sorted(leaked_docs),
        }


# Global default registry instance for module-level functions
_DEFAULT_REGISTRY = CanaryRegistry()


def get_default_registry() -> CanaryRegistry:
    """Return the global default CanaryRegistry instance."""
    return _DEFAULT_REGISTRY


def reset_default_registry() -> None:
    """Reset the global default registry."""
    _DEFAULT_REGISTRY.clear()


def generate_canaries_for_doc(
    doc_id: str,
    count: int = 1,
    registry: CanaryRegistry | None = None,
    prefix: str = "CANARY",
) -> list[str]:
    """Generates and registers honeytokens mapped to sensitive document IDs."""
    target_registry = registry if registry is not None else _DEFAULT_REGISTRY
    return target_registry.generate_canaries_for_doc(doc_id, count=count, prefix=prefix)


def inject_canaries_into_text(text: str, canaries: list[str]) -> str:
    """Embeds canary tokens into document content without changing front matter."""
    if not canaries:
        return text

    lines = text.splitlines(keepends=True)
    front_matter_end = None
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                front_matter_end = idx + 1
                break

    if front_matter_end is not None:
        front_matter = "".join(lines[:front_matter_end])
        body = "".join(lines[front_matter_end:])
        newline = "\r\n" if "\r\n" in front_matter else "\n"
    else:
        front_matter = ""
        body = text
        newline = "\r\n" if "\r\n" in text else "\n"

    canary_block = newline.join(canaries)

    if not body.strip():
        body_with_canaries = newline + canary_block + newline
    elif body.endswith(newline + newline):
        body_with_canaries = body + canary_block + newline
    elif body.endswith(newline):
        body_with_canaries = body + newline + canary_block + newline
    else:
        body_with_canaries = body + newline + newline + canary_block + newline

    return front_matter + body_with_canaries


def check_canary_leak(
    text: str,
    read_docs: Iterable[str],
    registry: CanaryRegistry | None = None,
) -> list[str]:
    """Scans text for any canary token associated with any document the actor has read."""
    if not text or not read_docs:
        return []

    target_registry = registry if registry is not None else _DEFAULT_REGISTRY
    leaks: list[str] = []
    seen: set[str] = set()

    for doc_id in read_docs:
        for canary in target_registry.get_canaries_for_doc(doc_id):
            if canary in text and canary not in seen:
                seen.add(canary)
                leaks.append(canary)

    return leaks


_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "in", "on", "at", "to", "for",
    "with", "about", "by", "from", "of", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "this", "that", "these", "those",
    "it", "its", "we", "our", "us", "they", "their", "them", "as", "into",
}


def _stem(word: str) -> str:
    """Lightweight English suffix normalizer for paraphrase matching."""
    w = word.lower()
    if len(w) > 4:
        if w.endswith("sses"):
            w = w[:-2]
        elif w.endswith("ies"):
            w = w[:-3] + "y"
        elif not w.endswith("ss") and w.endswith("s"):
            w = w[:-1]
    if len(w) > 5:
        if w.endswith("eed"):
            w = w[:-1]
        elif w.endswith("ed"):
            w = w[:-2]
        elif w.endswith("ing"):
            w = w[:-3]
    return w


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    return {_stem(w) for w in words if len(w) > 1 and w not in _STOPWORDS}


def _calculate_overlap_score(source_tokens: set[str], candidate_tokens: set[str]) -> float:
    if not source_tokens or not candidate_tokens:
        return 0.0
    intersection = len(source_tokens & candidate_tokens)
    jaccard = intersection / len(source_tokens | candidate_tokens)
    containment = intersection / len(source_tokens)
    return max(jaccard, containment * 0.85)


def check_paraphrase_leak(
    text: str,
    read_docs: Iterable[str],
    registry: CanaryRegistry | None = None,
    threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Scan text for paraphrased sensitive content from read documents."""
    if not text or not read_docs:
        return []

    target_registry = registry if registry is not None else _DEFAULT_REGISTRY
    candidate_sentences = [
        s.strip() for s in re.split(r"[.\n;!?]+", text) if len(s.strip()) > 8
    ]

    matches: list[dict[str, Any]] = []

    for doc_id in read_docs:
        phrases = target_registry.get_phrases_for_doc(doc_id)
        for phrase in phrases:
            phrase_tokens = _tokenize(phrase)
            if len(phrase_tokens) < 3:
                continue

            for sentence in candidate_sentences:
                cand_tokens = _tokenize(sentence)
                score = _calculate_overlap_score(phrase_tokens, cand_tokens)
                if score >= threshold:
                    matches.append({
                        "doc_id": doc_id,
                        "source_phrase": phrase,
                        "matched_text": sentence,
                        "similarity": round(score, 3),
                    })
                    break

    return matches
