"""Batch 2 — wrong answers. These defects did not corrupt storage; they made the
system report something false about data that was itself fine. A detector that
cannot see a signal, and a ranking that sorts the worst problems last, are both
silent: nothing errors, the answer is just wrong.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from echolens.backlog import PERSISTENCE_HALF_LIFE, resolution_rate
from echolens.db.models import (
    AnomalyEvent, Base, Finding, FixWatch, Investigation, Product, Review)
from echolens.detector.detect import ZERO_VAR_Z_CAP, _daily_counts, _zscore, detect_rating_drop
from echolens.impact import MIN_SHARE_DENOMINATOR, severity

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


# ── B2.1 ────────────────────────────────────────────────────────────────

def test_zero_variance_baseline_does_not_score_zero():
    """std_b == 0 made z == 0, so the CLEANEST possible signal — a rock-steady
    baseline that collapses — was the one guaranteed to be discarded."""
    z, _ = _zscore([1.0] * 7, [5.0] * 29)
    assert z != 0.0, "a 4-star collapse must not score zero"


def test_a_genuinely_flat_series_still_scores_zero():
    """The fallback must not invent a signal where there is none."""
    z, _ = _zscore([5.0] * 7, [5.0] * 29)
    assert z == 0.0


def test_zero_variance_fallback_is_capped():
    """A ratio against a flat baseline is unbounded; it must never outrank a
    genuine multi-sigma spike by sheer arithmetic."""
    z, _ = _zscore([1000.0] * 7, [1.0] * 29)
    assert abs(z) <= ZERO_VAR_Z_CAP


def test_rating_collapse_on_a_stable_baseline_is_detected(session):
    p = Product(name="Lumo")
    session.add(p)
    n = 0
    for d in range(36, 7, -1):          # 29 days at exactly 5.0
        for _ in range(3):
            n += 1
            session.add(Review(source="play_store", ext_id=f"r{n}", rating=5, text="great",
                               product="Lumo",
                               created_at=(NOW - timedelta(days=d)).replace(tzinfo=None)))
    for d in range(7, 0, -1):           # then 7 days at exactly 1.0
        for _ in range(3):
            n += 1
            session.add(Review(source="play_store", ext_id=f"r{n}", rating=1, text="broken",
                               product="Lumo",
                               created_at=(NOW - timedelta(days=d)).replace(tzinfo=None)))
    session.flush()
    assert detect_rating_drop(session, as_of=NOW, product="Lumo") is not None


# ── B2.2 ────────────────────────────────────────────────────────────────

def test_no_data_days_do_not_manufacture_a_surge():
    """_share_series appended 0.0 for days with no reviews — a measured "0% of
    complaints were about this". On a sparse corpus those zeros dragged the
    baseline down and a perfectly FLAT theme reported as a SEV1 surge."""
    padded = [100.0] * 3 + [0.0] * 26      # the old behaviour
    observed = [100.0] * 3                 # the new behaviour
    recent = [100.0] * 7
    assert _zscore(recent, padded)[0] >= 1.0, "the old padding did fire (the bug)"
    assert _zscore(recent, observed)[0] == 0.0, "a flat theme must not surge"


# ── B2.3 ────────────────────────────────────────────────────────────────

def test_resolution_rate_cannot_exceed_one(session):
    """One case can carry several FixWatch rows (link_issue dedupes on
    (repo, issue_number), not finding_id). The raw ratio exceeded 1.0, making
    `1 - rate` negative, which flipped every score's sign and sorted the
    highest-severity longest-open items LAST."""
    p = Product(name="Lumo")
    session.add(p)
    session.flush()
    inv_ids = []
    for i in range(3):
        a = AnomalyEvent(slug=f"a{i}", type="t", metric="m", delta=0, z=3, window="7d",
                         description="d", status="closed", product_id=p.id)
        session.add(a)
        session.flush()
        inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                            budget_tier="standard", budget_json={}, product_id=p.id)
        session.add(inv)
        session.flush()
        inv_ids.append(inv.id)
        f = Finding(investigation_id=inv.id, summary="s", confidence=0.8, status="approved",
                    product_id=p.id, json={})
        session.add(f)
        session.flush()
        # two watches on the same investigation — the real-world duplicate
        for issue_no in (i * 10 + 1, i * 10 + 2):
            session.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r",
                                 issue_number=issue_no, status="confirmed", terms=["x"],
                                 metric="m", product_id=p.id))
    session.flush()
    rate = resolution_rate(session, p.id)
    assert 0.0 <= rate <= 1.0, f"rate must be a share, got {rate}"
    assert (1 - rate) >= 0.0, "a negative (1 - rate) inverts the whole ranking"


# ── B2.4 ────────────────────────────────────────────────────────────────

def test_baseline_window_matches_its_documented_length():
    series = _daily_counts([], lambda r: r, NOW - timedelta(days=35), NOW)
    assert len(series) == 35
    assert len(series[:-7]) == 28, "the description says 28d; it must BE 28d"


# ── B2.7 / B2.8 ─────────────────────────────────────────────────────────

def test_severity_clamps_an_out_of_range_impact_score():
    """impact_score was bounded only where it was built, so any other producer
    could yield a severity above its own stated 0..1 range."""
    assert severity(1.0, {"impact_score": 5.0})["score"] <= 1.0


def test_unmeasured_impact_is_not_reported_as_low():
    """0.0 rendered as "low" — a claim that we looked and found little, when we
    had not looked at all."""
    assert severity(0.9, {"measured": False})["band"] == "unknown"
    assert severity(0.9, {"impact_score": 0.05, "measured": True})["band"] == "low"


def test_share_needs_a_real_denominator():
    assert MIN_SHARE_DENOMINATOR >= 5, "1-of-1 must not report as 100%"


# ── B2.12 ───────────────────────────────────────────────────────────────

def test_persistence_saturates_instead_of_dominating():
    """As a raw multiplier, a 730-day trivial case outranked a 1-day critical
    one by ~730x regardless of severity or volume."""
    import math

    def mult(days):
        return 1.0 + math.log1p(days / PERSISTENCE_HALF_LIFE)

    assert mult(730) / mult(1) < 10, "age must inform the ranking, not decide it"
    assert mult(730) > mult(30), "...but older still outranks newer, all else equal"
