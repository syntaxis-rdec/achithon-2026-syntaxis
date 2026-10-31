"""Classification lattice. Derived work inherits, never downgrades."""

from __future__ import annotations

from .models import Classification, SecurityLabel

ORDER: list[Classification] = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]


def rank(classification: Classification) -> int:
    return ORDER.index(classification)


def at_least(candidate: Classification, needed: Classification) -> bool:
    """True when `candidate` clearance covers `needed` sensitivity."""
    return rank(candidate) >= rank(needed)


def combine(labels: list[SecurityLabel]) -> SecurityLabel:
    """Highest classification, union of provenance and tags."""
    if not labels:
        return SecurityLabel(classification="PUBLIC", provenance=[], tags=[])
    highest = max(labels, key=lambda label: rank(label.classification))
    provenance: list[str] = []
    tags: list[str] = []
    for label in labels:
        for item in label.provenance:
            if item not in provenance:
                provenance.append(item)
        for tag in label.tags:
            if tag not in tags:
                tags.append(tag)
    return SecurityLabel(
        classification=highest.classification,
        provenance=provenance,
        tags=tags,
    )
