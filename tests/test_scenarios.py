"""The frozen suite must hold its contract, and must notice a broken gateway."""

from __future__ import annotations

from benchmark.mutations import run_mutations
from benchmark.runner import run_suite


def test_frozen_suite_meets_its_contract():
    report = run_suite(results_path=None)
    metrics = report["metrics"]
    assert metrics["scenarios"] == 32
    assert metrics["expected_allow"] == 10
    assert metrics["expected_deny"] == 22
    assert metrics["scenario_matches"] == 32
    assert metrics["false_allows"] == 0
    assert metrics["false_denies"] == 0
    assert metrics["unauthorized_executions"] == 0
    assert metrics["allowed_without_effect"] == 0
    assert metrics["audit_complete"] == 32


def test_every_mutation_is_detected():
    results = run_mutations()
    assert results["all_detected"], [
        m["name"] for m in results["mutations"] if not m["detected"]
    ]
