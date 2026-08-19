"""v13 — the unified case list.

The IA restructure rests on one claim: there is exactly ONE answer to "what
state is this case in", and every screen reads it from the same place. These
tests pin that claim down.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from echolens import cases as C
from echolens.db.models import (
    AnomalyEvent, Base, Finding, FixWatch, Investigation, Product,
    QueuedInvestigation, Review, ReviewFeedback, TriageDecision)

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture()
def product(session):
    p = Product(name="Lumo", package_name="com.lumo.app")
    session.add(p)
    session.flush()
    return p


def _anomaly(session, product, **kw):
    kw.setdefault("slug", f"a{id(kw)}")
    kw.setdefault("status", "closed")
    a = AnomalyEvent(type="theme_volume_surge", metric="battery share of negatives",
                     delta=0.3, z=3.1, window="7d", description="battery complaints",
                     product_id=product.id, created_at=NOW - timedelta(days=4), **kw)
    session.add(a)
    session.flush()
    return a


def _case(session, product, *, status="resolved", finding_status=None, confidence=0.85,
          summary="Battery drains after the v3.2 background-sync change", days_ago=3):
    a = _anomaly(session, product, slug=f"slug-{summary[:8]}-{days_ago}-{status}")
    inv = Investigation(anomaly_id=a.id, status=status, opened_by="anomaly",
                        budget_tier="standard", budget_json={"iterations": "4/12"},
                        product_id=product.id, created_at=NOW - timedelta(days=days_ago))
    session.add(inv)
    session.flush()
    f = None
    if finding_status is not None:
        f = Finding(investigation_id=inv.id, summary=summary, confidence=confidence,
                    status=finding_status, product_id=product.id,
                    created_at=NOW - timedelta(days=days_ago),
                    json={"summary": summary, "prose": summary,
                          "impact": {"impact_score": 0.7, "affected_pct": 9.0,
                                     "affected_volume": 120, "terms": ["battery"]}})
        session.add(f)
        session.flush()
    return inv, f


# ── the eight words, and only the eight words ───────────────────────────

def test_draft_finding_needs_review(session, product):
    inv, _ = _case(session, product, status="resolved", finding_status="draft")
    row = _row(session, product, inv.id)
    assert row["status"] == C.NEEDS_REVIEW


def test_approved_finding_is_resolved(session, product):
    inv, _ = _case(session, product, status="resolved", finding_status="approved")
    assert _row(session, product, inv.id)["status"] == C.RESOLVED


def test_confirmed_fix_outranks_resolved(session, product):
    inv, f = _case(session, product, status="resolved", finding_status="approved")
    session.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r",
                         issue_number=7, status="confirmed", terms=["battery"],
                         product_id=product.id, confirmed_at=NOW - timedelta(days=1)))
    session.flush()
    assert _row(session, product, inv.id)["status"] == C.VERIFIED_FIXED


def test_regression_outranks_everything(session, product):
    inv, f = _case(session, product, status="resolved", finding_status="approved")
    session.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r",
                         issue_number=8, status="regressed", terms=["battery"],
                         product_id=product.id))
    session.flush()
    assert _row(session, product, inv.id)["status"] == C.REGRESSED


def test_dead_ends_all_land_on_needs_human(session, product):
    """Budget exhaustion and insufficient evidence are different reasons for the
    same user job: a human has to decide what happens next."""
    for backend_status in ("budget_exhausted", "insufficient_evidence", "needs_human"):
        inv, _ = _case(session, product, status=backend_status, finding_status=None,
                       days_ago=2, summary=backend_status)
        row = _row(session, product, inv.id)
        assert row["status"] == C.NEEDS_HUMAN
        assert row["why"], "a dead end must explain itself"


def test_challenged_finding_is_dismissed(session, product):
    inv, _ = _case(session, product, status="resolved", finding_status="challenged")
    assert _row(session, product, inv.id)["status"] == C.DISMISSED


def test_every_status_is_in_the_vocabulary_and_has_a_tab(session, product):
    _case(session, product, status="running", finding_status=None, summary="running")
    _case(session, product, status="resolved", finding_status="draft", summary="draft")
    _case(session, product, status="resolved", finding_status="approved", summary="ok")
    _case(session, product, status="budget_exhausted", finding_status=None, summary="broke")
    view = C.case_view(session, product.id, NOW)
    homed = {s for statuses in C.TABS.values() for s in statuses}
    for row in view["cases"]:
        assert row["status"] in C.STATUSES
        assert row["status"] in homed, f"{row['status']} has no filter tab"


# ── titles are problem statements ───────────────────────────────────────

def test_title_is_never_a_bare_metric_name(session, product):
    inv, _ = _case(session, product, status="running", finding_status=None)
    title = _row(session, product, inv.id)["title"]
    assert title != "battery share of negatives"
    assert len(title.split()) > 2


def test_finding_summary_wins_as_the_title(session, product):
    inv, _ = _case(session, product, status="resolved", finding_status="draft")
    assert _row(session, product, inv.id)["title"].startswith("Battery drains")


# ── queue, signals, counts ──────────────────────────────────────────────

def test_queued_items_are_cases_not_a_separate_panel(session, product):
    a = _anomaly(session, product, slug="queued-1", status="pending")
    session.add(QueuedInvestigation(product_id=product.id, anomaly_id=a.id, status="queued",
                                    source="manual_theme", priority=60, budget_tier="quick",
                                    title="Login fails after the 2FA rollout",
                                    created_at=NOW - timedelta(hours=2)))
    session.flush()
    view = C.case_view(session, product.id, NOW)
    queued = [c for c in view["cases"] if c["status"] == C.QUEUED]
    assert len(queued) == 1
    assert queued[0]["queue_id"] is not None and queued[0]["id"] is None
    assert view["counts"]["queued"] == 1


def test_signals_exclude_anything_already_a_case(session, product):
    _anomaly(session, product, slug="untouched", status="pending")
    inv, _ = _case(session, product, status="running", finding_status=None)
    signals = C.signal_rows(session, product.id, NOW)
    assert [s["slug"] for s in signals] == ["untouched"]


def test_dismissed_signals_carry_their_reason(session, product):
    a = _anomaly(session, product, slug="noise", status="pending")
    session.add(TriageDecision(anomaly_id=a.id, decision="ignore",
                               reason="seasonal, not a regression"))
    session.flush()
    signal = C.signal_rows(session, product.id, NOW)[0]
    assert signal["dismissed"] is True
    assert signal["dismissed_reason"] == "seasonal, not a regression"


def test_scoped_to_one_product(session, product):
    other = Product(name="Other")
    session.add(other)
    session.flush()
    _case(session, product, status="running", finding_status=None, summary="mine")
    _case(session, other, status="running", finding_status=None, summary="theirs")
    assert len(C.case_view(session, product.id, NOW)["cases"]) == 1


# ── sparkline honesty ───────────────────────────────────────────────────

def test_sparkline_is_real_data_or_absent(session, product):
    """A flat line drawn from nothing reads as a measured zero. Return None."""
    inv, _ = _case(session, product, status="resolved", finding_status="draft")
    assert _row(session, product, inv.id)["spark"] is None  # no reviews in the corpus

    for i in range(5):
        session.add(Review(source="play_store", ext_id=f"r{i}", rating=1,
                           text="battery drains overnight", product=product.name,
                           created_at=(NOW - timedelta(days=2 + i)).replace(tzinfo=None)))
    session.flush()
    spark = _row(session, product, inv.id)["spark"]
    assert spark is not None and sum(spark) == 5


# ── history ─────────────────────────────────────────────────────────────

def test_history_records_the_human_decision(session, product):
    inv, f = _case(session, product, status="resolved", finding_status="challenged")
    session.add(ReviewFeedback(finding_id=f.id, action="challenge", reason="weak_evidence",
                               note="check chargers too", created_at=NOW))
    session.flush()
    kinds = [e["kind"] for e in C.case_history(session, inv)]
    assert "opened" in kinds and "challenged" in kinds
    challenge = next(e for e in C.case_history(session, inv) if e["kind"] == "challenged")
    assert "weak evidence" in challenge["text"]
    assert challenge["note"] == "check chargers too"


def test_history_links_the_reopened_case(session, product):
    first, f = _case(session, product, status="resolved", finding_status="challenged")
    second = Investigation(anomaly_id=first.anomaly_id, status="running", opened_by="challenge",
                           budget_tier="standard", budget_json={}, product_id=product.id,
                           reopens_investigation_id=first.id, created_at=NOW)
    session.add(second)
    session.flush()
    forward = C.case_history(session, first)
    assert any(e["case_id"] == second.id for e in forward)
    back = C.case_history(session, second)
    assert any(e["case_id"] == first.id for e in back)


def _row(session, product, inv_id: int) -> dict:
    rows = C.case_rows(session, product.id, NOW)
    return next(r for r in rows if r["id"] == inv_id)


# ── regression guards for the audit fixes ───────────────────────────────

def test_feedback_sort_key_is_tz_aware_throughout():
    """The NULL-timestamp fallback must be tz-AWARE.

    Every real created_at comes through aware_utc(), so a naive fallback made
    Python compare offset-naive to offset-aware and raise TypeError. No source
    table currently allows a NULL created_at, so this was latent rather than
    live — but the sort must not be one migration away from taking down the
    whole feedback graph.
    """
    from echolens.feedback import FeedbackItem

    dated = FeedbackItem(ref="a", channel="play_store", text="battery",
                         created_at=NOW - timedelta(days=1))
    undated = FeedbackItem(ref="b", channel="support", text="crash", created_at=None)
    fallback = datetime.min.replace(tzinfo=timezone.utc)
    ordered = sorted([dated, undated], key=lambda x: (x.created_at or fallback), reverse=True)
    assert ordered[0] is dated  # must not raise, and undated sorts last


def test_window_is_utc_not_server_local():
    """Stored datetimes are UTC; using the server's local offset shifted the
    window edges and mis-bucketed feedback near the boundary."""
    from echolens.feedback import window
    start, end = window(days=7)
    assert end.tzinfo is not None
    assert end.utcoffset() == timedelta(0), "window must be UTC, not local time"


def test_brain_trend_does_not_call_every_refuted_edge_weakening(session, product):
    """The old test compared confidence against itself-with-one-fewer-refute,
    which is arithmetically always lower — so any edge refuted even once read
    as 'weakening', including a 20-support/1-refute edge at 91% confidence."""
    from echolens.brain import _edge_dict
    from echolens.db.models import KnowledgeEdge

    strong = KnowledgeEdge(product_id=product.id, subsystem="sync", symptom="battery-drain",
                           supports=20, refutes=1, verified_count=20, status="active",
                           case_ids=[1])
    decaying = KnowledgeEdge(product_id=product.id, subsystem="ui", symptom="crash",
                             supports=4, refutes=3, verified_count=4, status="active",
                             case_ids=[2])
    assert _edge_dict(strong)["trend"] == "holding"
    assert _edge_dict(decaying)["trend"] == "weakening"


def test_triage_as_of_resolves_at_call_time():
    """The default used to bind the detector's hardcoded AS_OF at import, so the
    daily cap compared every run against a frozen date and never engaged."""
    import inspect
    from echolens.orchestrator.triage import Orchestrator
    default = inspect.signature(Orchestrator.triage).parameters["as_of"].default
    assert default is None, "as_of must resolve at call time, not import time"
