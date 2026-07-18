"""Tool contracts: deterministic, truncated, segmentable (PRD §5.4)."""
from __future__ import annotations

from echolens.config import TOOL_RESULT_MAX_ITEMS, TOOL_SNIPPET_MAX_CHARS
from echolens.tools.compare_periods import compare_periods
from echolens.tools.get_release_notes import get_release_notes
from echolens.tools.registry import TOOLS, run_tool
from echolens.tools.review_stats import review_stats
from echolens.tools.search_github_issues import search_github_issues
from echolens.tools.search_reviews import search_reviews


def test_search_reviews_finds_battery_spike(session):
    res = search_reviews(session, "battery drain background",
                         date_from="2026-07-11", rating_max=2)
    assert res["total_matches"] > 20
    assert res["returned"] <= TOOL_RESULT_MAX_ITEMS
    assert all(r["rating"] <= 2 for r in res["reviews"])
    assert all(len(r["snippet"]) <= TOOL_SNIPPET_MAX_CHARS for r in res["reviews"])
    assert all(r["ref"].startswith("ps_") for r in res["reviews"])


def test_search_reviews_is_deterministic(session):
    a = search_reviews(session, "battery", date_from="2026-07-08")
    b = search_reviews(session, "battery", date_from="2026-07-08")
    assert a == b


def test_version_segmentation_kills_the_decoy(session):
    """The decoy-killer: v3.1 users on Android 15 show NO battery spike,
    while 3.2 users do. This is what settles H_os vs H_sync."""
    v31 = review_stats(session, "battery", date_from="2026-07-11",
                       version_prefix="3.1", os_version="Android 15")
    v32 = review_stats(session, "battery", date_from="2026-07-11",
                       version_prefix="3.2")
    assert v31["term_share_of_negatives_pct"] < 20
    assert v32["term_share_of_negatives_pct"] > 50
    assert v32["term_share_of_negatives_pct"] > 3 * max(v31["term_share_of_negatives_pct"], 1)


def test_baseline_battery_rate_is_low(session):
    base = review_stats(session, "battery", date_from="2026-05-01", date_to="2026-07-01")
    assert base["term_share_of_negatives_pct"] < 15


def test_compare_periods_detects_one_star_spike(session):
    res = compare_periods(session, "one_star_volume",
                          before_from="2026-06-01", before_to="2026-07-07",
                          after_from="2026-07-11", after_to="2026-07-16")
    assert res["delta_pct"] > 20
    assert res["z_score"] is not None and res["z_score"] > 2


def test_github_search_finds_wakelock_issue(session):
    res = search_github_issues(session, "background sync battery wakelock")
    assert res["total_matches"] >= 3
    assert any("wakelock" in i["title"].lower() for i in res["issues"])
    assert all(i["ref"].startswith("issue #") for i in res["issues"])


def test_release_notes_v32_mentions_sync(session):
    res = get_release_notes(session, version="3.2")
    assert res["returned"] == 1
    assert "background photo sync" in res["releases"][0]["notes"]


def test_registry_runs_and_validates(session):
    out = run_tool(session, "search_reddit", {"query": "battery sync"})
    assert out["total_matches"] >= 1
    try:
        run_tool(session, "search_reviews", {})  # missing required 'query'
        raised = False
    except ValueError:
        raised = True
    assert raised
    assert set(TOOLS) == {
        "search_reviews", "review_stats", "compare_periods",
        "search_github_issues", "get_release_notes", "search_reddit",
        "compare_cohorts", "analyze_trend",  # v2.0
    }
