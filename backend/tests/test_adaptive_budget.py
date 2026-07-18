"""v2.0 adaptive budgets: tier chosen by anomaly complexity, not just severity."""
from __future__ import annotations

from echolens.db.models import AnomalyEvent
from echolens.orchestrator.triage import adaptive_tier


def _anom(session, **kw):
    a = AnomalyEvent(slug=kw.get("slug", "x"), type=kw.get("type", "negative_review_spike"),
                     metric=kw.get("metric", "battery complaints"), delta=0.2,
                     z=kw.get("z", 2.0), window="7d", description="d", status="pending")
    session.add(a)
    session.flush()
    return a


def test_sharp_single_source_spike_gets_quick(session):
    # very strong z, volume type, a term that doesn't echo elsewhere → cheap
    a = _anom(session, type="negative_review_spike", z=4.0, metric="zzznomatch complaints")
    assert adaptive_tier(a, session) == "quick"


def test_multi_source_theme_gets_deep(session):
    # a fuzzy theme whose term ("battery") echoes in issues AND posts → expensive
    a = _anom(session, type="theme_volume_surge", z=2.0, metric="battery complaints")
    assert adaptive_tier(a, session) == "deep"


def test_manual_case_is_at_least_standard(session):
    a = _anom(session, type="manual", z=0.0, metric="crash on camera open")
    assert adaptive_tier(a, session) in ("standard", "deep")


def test_adaptive_tier_is_deterministic(session):
    a = _anom(session, type="theme_volume_surge", z=2.0, metric="battery complaints")
    assert adaptive_tier(a, session) == adaptive_tier(a, session)
