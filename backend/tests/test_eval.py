"""The eval harness itself is the acceptance test for M2 (PRD §11):
all six golden scenarios pass and every honesty metric is at 100%."""
from __future__ import annotations

from echolens.eval import run_all


def test_all_golden_scenarios_pass():
    report = run_all()
    failed = [s["name"] for s in report["scenarios"] if not s["passed"]]
    assert not failed, f"failing scenarios: {failed}"
    assert report["all_passed"]


def test_honesty_metrics_are_perfect():
    report = run_all()
    assert report["claim_grounding_pct"] == 100.0
    assert report["honesty_pct"] == 100.0
    assert report["budget_compliance_pct"] == 100.0


def test_covers_the_required_scenario_shapes():
    names = {s["name"] for s in run_all()["scenarios"]}
    assert {
        "clear_cause", "decoy_rejected", "insufficient_evidence",
        "conflicting_needs_human", "duplicate_merge", "budget_exhausted",
    } <= names
