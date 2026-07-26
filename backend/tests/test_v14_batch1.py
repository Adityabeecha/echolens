"""Batch 1 — data corruption. Every test here pins a defect that used to write a
FALSE FACT into the database, which the brain, patterns and backlog then mined
as ground truth. A wrong number in these paths does not stay a wrong number.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from echolens.db.models import (
    AnomalyEvent, Base, Finding, FixWatch, Investigation, Product, Review)
from echolens.fixwatch import MIN_OBSERVATION_DAYS, evaluate
from echolens.importers.csv_reviews import import_reviews_csv

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture()
def product(session):
    p = Product(name="Lumo")
    session.add(p)
    session.flush()
    return p


# ── B1.1 ────────────────────────────────────────────────────────────────

def test_csv_without_ratings_does_not_import_praise_as_complaints(session, product):
    """_int() returned 0 for a missing rating, and every negativity filter is
    `rating <= 2` — so a rating-less export became a corpus of 1-star
    complaints and the detector fired on fabricated negativity."""
    csv = ("text,date\n"
           "I love this app the battery lasts forever,2026-07-01\n"
           "Amazing battery life,2026-07-02\n")
    result = import_reviews_csv(session, csv, product=product.name)
    assert result["imported"] == 0
    assert result["unrated"] == 2, "unrated rows must be reported, not silently dropped"
    assert session.query(Review).count() == 0


def test_csv_with_ratings_still_imports(session, product):
    csv = "text,rating,date\nbattery dies fast,1,2026-07-01\ngreat app,5,2026-07-02\n"
    result = import_reviews_csv(session, csv, product=product.name)
    assert result["imported"] == 2 and result["unrated"] == 0
    assert {r.rating for r in session.query(Review).all()} == {1, 5}


# ── B1.3 / B1.4 ─────────────────────────────────────────────────────────

def _watch(session, product, *, fix_days_ago, baseline, window_days=14):
    a = AnomalyEvent(slug=f"a{fix_days_ago}", type="theme_volume_surge", metric="battery",
                     delta=0.3, z=3.0, window="7d", description="d", status="closed",
                     product_id=product.id)
    session.add(a)
    session.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                        budget_tier="standard", budget_json={}, product_id=product.id)
    session.add(inv)
    session.flush()
    f = Finding(investigation_id=inv.id, summary="battery", confidence=0.8,
                status="approved", product_id=product.id, json={})
    session.add(f)
    session.flush()
    w = FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r", issue_number=1,
                 status="watching", terms=["battery"], metric="battery",
                 window_days=window_days, baseline_rate=baseline,
                 fix_date=NOW - timedelta(days=fix_days_ago), product_id=product.id)
    session.add(w)
    session.flush()
    return w


def test_no_post_fix_data_is_not_a_confirmed_fix(session, product):
    """post == 0.0 used to mean both "we watched and saw nothing" and "we have
    not watched". The second confirmed the fix on an empty window."""
    w = _watch(session, product, fix_days_ago=1, baseline=5.0)
    out = evaluate(session, as_of=NOW)
    assert w.status == "watching", "a 1-day window cannot confirm anything"
    assert out[0]["status"] == "watching"
    assert "not enough post-fix data" in out[0]["why"]


def test_stalled_collector_cannot_confirm_a_fix(session, product):
    """If the newest review predates the fix, the observation window is empty
    or negative. That used to produce 0.0 and read as a perfect fix."""
    w = _watch(session, product, fix_days_ago=-10, baseline=5.0)  # fix is in the future
    evaluate(session, as_of=NOW)
    assert w.status == "watching"


def test_ambiguous_improvement_is_not_banked_as_verified(session, product):
    """The 40-60% band was explicitly confirmed by a comment that said so.
    A rate still at ~59% of baseline is not "the complaints stopped"."""
    w = _watch(session, product, fix_days_ago=20, baseline=10.0, window_days=14)
    # ~5.7/day post-fix: below PERSIST_KEEP (6.0) but above CONFIRM_DROP (4.0).
    for i in range(80):
        session.add(Review(source="play_store", ext_id=f"amb{i}", rating=1,
                           text="battery drains", product=product.name,
                           created_at=(NOW - timedelta(days=19 - (i % 14))).replace(tzinfo=None)))
    session.flush()
    evaluate(session, as_of=NOW)
    assert w.status == "inconclusive", f"expected inconclusive, got {w.status}"


def test_a_real_fix_still_confirms(session, product):
    """The guard must not block genuine confirmations."""
    w = _watch(session, product, fix_days_ago=20, baseline=10.0, window_days=14)
    evaluate(session, as_of=NOW)  # no post-fix complaints, full window elapsed
    assert w.status == "confirmed"


def test_min_observation_days_is_enforced(session, product):
    w = _watch(session, product, fix_days_ago=MIN_OBSERVATION_DAYS - 1, baseline=5.0)
    evaluate(session, as_of=NOW)
    assert w.status == "watching"


# ── B1.6 ────────────────────────────────────────────────────────────────

def test_ungrounded_prose_is_never_published_as_the_finding():
    """The guard used to DETECT a violation and publish it anyway: the last
    failing candidate was returned verbatim, and the only consequence was a
    status downgrade gated on status == "resolved" — so a case ending in
    needs_human published uncited causal prose with no consequence at all.
    Governing rule 2 is "no causal claim without an evidence chain"."""
    from echolens.investigator.graph import Investigator
    from echolens.llm.client import LLMClient, LLMResult

    class AlwaysUngrounded(LLMClient):
        """Returns causal prose with no citation, twice — the worst case."""
        def complete_json(self, system, user, schema, agent=""):
            return LLMResult(parsed={
                "summary": "The v3.2 rollout caused the crash wave",
                "prose": "The v3.2 rollout caused the crash wave.",
                "confidence": 0.9, "supported_hypothesis": "H1",
                "checked": ["play_store"], "what_would_settle_it": "n/a",
            }, tokens_in=10, tokens_out=10, model="test", ms=1)

    from echolens.config import BUDGET_TIERS
    from echolens.investigator.state import Budget

    inv = Investigator.__new__(Investigator)
    inv.llm = AlwaysUngrounded()
    # _draft_finding consults the budget before its optional RETRY, so a bare
    # instance needs one. Fresh budget = the retry is allowed, which is the
    # path under test (both attempts must fail grounding).
    inv.budget = Budget(tier=BUDGET_TIERS["standard"])
    state = {"status": "needs_human", "status_reason": "conflicting evidence",
             "trigger": {}, "hypotheses": [], "evidence": []}
    finding = Investigator._draft_finding(inv, state)

    assert finding["grounding_violations"], "the violation must be recorded"
    assert "caused the crash wave" not in finding["prose"], \
        "the uncited causal claim must NOT be the published prose"
    assert finding["rejected_draft"] == "The v3.2 rollout caused the crash wave.", \
        "the rejected text is kept for audit"
    assert state["status"] == "needs_human"
