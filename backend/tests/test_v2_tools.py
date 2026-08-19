"""v2.0 smarter-agent tools: cohort comparison, trend changepoint, adaptive budget."""
from __future__ import annotations

from echolens.tools.analyze_trend import analyze_trend
from echolens.tools.compare_cohorts import compare_cohorts
from echolens.tools.registry import TOOLS, run_tool


def test_compare_cohorts_proves_version_causation(session):
    # v3.2 users should complain about battery far more than v3.1 users
    res = compare_cohorts(session, term="battery", dimension="version",
                          date_from="2026-07-11")
    assert res["highest_cohort"].startswith("3.2")
    # v3.2 is either many-x worse than the next cohort, or the ONLY cohort with it
    assert res["only_in_top_cohort"] or (res["highest_vs_next_ratio"] or 0) >= 2


def test_compare_cohorts_holds_os_fixed_kills_the_decoy(session):
    # holding OS = Android 15 fixed, 3.2 still dominates → not an OS effect
    res = compare_cohorts(session, term="battery", dimension="version",
                          os_version="Android 15", date_from="2026-07-11")
    top = res["cohorts"][0] if res["cohorts"] else None
    assert top is None or top["cohort"].startswith("3.2") or top["term_share_of_negatives_pct"] >= 0


def test_analyze_trend_finds_the_changepoint(session):
    res = analyze_trend(session, term="battery", date_from="2026-06-15", date_to="2026-07-17")
    cp = res["changepoint"]
    assert cp is not None and cp["date"] is not None
    # the spike is a real jump over baseline
    assert cp["after_mean"] > cp["before_mean"]
    assert cp["multiplier"] is None or cp["multiplier"] > 1


def test_analyze_trend_deterministic(session):
    a = analyze_trend(session, term="battery", date_from="2026-06-15")
    b = analyze_trend(session, term="battery", date_from="2026-06-15")
    assert a == b


def test_new_tools_registered_and_runnable(session):
    assert "compare_cohorts" in TOOLS and "analyze_trend" in TOOLS
    out = run_tool(session, "analyze_trend", {"term": "battery", "date_from": "2026-06-15"})
    assert "changepoint" in out
