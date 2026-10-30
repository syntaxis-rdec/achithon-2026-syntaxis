"""Mutation check: break the gateway six ways and prove the suite notices.

A test suite that cannot fail is not evidence. Each mutation removes exactly one
control and must degrade a specific metric.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from agentgate import labels
from agentgate.models import SecurityLabel
from agentgate.store import Store

from .runner import run_suite


def _public(*_args, **_kwargs) -> SecurityLabel:
    return SecurityLabel(classification="PUBLIC", provenance=[], tags=[])


def _always(*_args, **_kwargs) -> bool:
    return True


MUTATIONS = {
    "clearance_checks_disabled": {
        "patch": lambda: patch.object(labels, "at_least", _always),
        "expect": lambda m: m["false_allows"] > 0,
        "means": "clearance checks removed",
    },
    "label_inheritance_disabled": {
        "patch": lambda: patch.object(labels, "combine", _public),
        "expect": lambda m: m["scenario_matches"] < 32,
        "means": "derived reports stop inheriting labels",
    },
    "recipient_allowlist_disabled": {
        "patch": lambda: patch("agentgate.policy._recipient_allowed", _always),
        "expect": lambda m: m["false_allows"] > 0,
        "means": "approved-recipient list ignored",
    },
    "tamper_detection_disabled": {
        "patch": lambda: patch.object(Store, "integrity_of", lambda self, doc_id: "ok"),
        "expect": lambda m: m["false_allows"] > 0,
        "means": "document tampering ignored",
    },
    "read_history_disabled": {
        "patch": lambda: patch.object(Store, "reads_for", lambda self, actor_id: []),
        "expect": lambda m: m["scenario_matches"] < 32,
        "means": "hidden sources no longer recovered",
    },
    "audit_disabled": {
        "patch": lambda: patch.object(Store, "record_audit", lambda self, **kwargs: None),
        "expect": lambda m: m["audit_complete"] < 32,
        "means": "decisions stop being recorded",
    },
}


def run_mutations() -> dict:
    baseline = run_suite(results_path=None)["metrics"]
    results = {"baseline": baseline, "mutations": []}
    for name, spec in MUTATIONS.items():
        with spec["patch"]():
            mutated = run_suite(results_path=None)["metrics"]
        detected = spec["expect"](mutated)
        results["mutations"].append({
            "name": name,
            "means": spec["means"],
            "detected": detected,
            "metrics": mutated,
        })
    results["all_detected"] = all(m["detected"] for m in results["mutations"])
    return results


if __name__ == "__main__":
    print(json.dumps(run_mutations(), indent=2))
