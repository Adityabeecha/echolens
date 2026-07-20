"""Regressions for the 7 issues found in the full-codebase review.

Each test fails on the pre-fix code — they encode the actual defect, not the
shape of the patch.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens.db.models import (
    AnomalyEvent, Base, Finding, FixWatch, Investigation, Product, Review)

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


# ── #1 fix verification must not see other products ─────────────────────

def test_another_products_complaints_cannot_block_my_fix_confirmation():
    """Proven bug: Lumo's complaints stopped, but AppB complaining about the same
    theme kept Lumo's post-fix rate high — so a fix that worked never confirmed,
    and could even be flagged as a regression."""
    from echolens.fixwatch import _rate
    s = _session()
    s.add(Product(name="Lumo")); s.add(Product(name="AppB")); s.flush()
    for i in range(5):   # Lumo: pre-fix only, silent after
        s.add(Review(source="p", ext_id=f"lumo{i}", rating=1, text="battery drain awful",
                     product="Lumo", created_at=NOW - timedelta(days=30 + i)))
    for i in range(60):  # AppB: loud right now, same theme
        s.add(Review(source="p", ext_id=f"appb{i}", rating=1, text="battery drain awful",
                     product="AppB", created_at=NOW - timedelta(days=i % 6)))
    s.commit()

    scoped = _rate(s, ["battery", "drain"], NOW - timedelta(days=7), NOW, "Lumo")
    assert scoped == 0.0, f"Lumo's post-fix rate must ignore AppB, got {scoped}"
    # and AppB's own rate is genuinely non-zero, so this isn't just an empty query
    assert _rate(s, ["battery", "drain"], NOW - timedelta(days=7), NOW, "AppB") > 0


def test_regression_check_is_scoped_to_the_watchs_product():
    """A confirmed fix must not be flipped to 'regressed' by another product."""
    from echolens.fixwatch import check_regressions
    s = _session()
    lumo = Product(name="Lumo"); appb = Product(name="AppB")
    s.add(lumo); s.add(appb); s.flush()
    for i in range(80):  # only AppB is complaining, loudly, right now
        s.add(Review(source="p", ext_id=f"appb{i}", rating=1, text="battery drain awful",
                     product="AppB", created_at=NOW - timedelta(days=i % 5)))
    s.add(Review(source="p", ext_id="lumo_old", rating=1, text="battery drain awful",
                 product="Lumo", created_at=NOW - timedelta(days=40)))
    a = AnomalyEvent(slug="l1", type="theme_volume_surge", metric="m", delta=.2, z=3.,
                     window="7d", description="battery", status="closed", product_id=lumo.id)
    s.add(a); s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                        budget_tier="quick", budget_json={}, product_id=lumo.id)
    s.add(inv); s.flush()
    f = Finding(investigation_id=inv.id, summary="battery", confidence=.9, status="approved",
                json={"summary": "battery"}, product_id=lumo.id)
    s.add(f); s.flush()
    s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r", issue_number=1,
                   status="confirmed", terms=["battery", "drain"], metric="m",
                   baseline_rate=5.0, confirmed_at=NOW - timedelta(days=20),
                   product_id=lumo.id))
    s.commit()
    assert check_regressions(s, NOW) == [], \
        "AppB's noise must not regress Lumo's confirmed fix"


# ── #4 'now' must come from the product's own corpus ────────────────────

def test_a_stalled_product_is_not_measured_against_another_products_clock():
    from echolens.detector.detect import reference_now
    from echolens.vocab import canonical_theme, theme_rate
    s = _session()
    for i in range(3):   # A is live today
        s.add(Review(source="p", ext_id=f"a{i}", rating=1, text="checkout broken",
                     product="A", created_at=NOW - timedelta(days=i)))
    for i in range(3):   # B's collector stalled 180 days ago
        s.add(Review(source="p", ext_id=f"b{i}", rating=1, text="battery drain awful",
                     product="B", created_at=NOW - timedelta(days=180 + i)))
    s.commit()
    assert reference_now(s, "B").date() < reference_now(s, "A").date()
    rate = theme_rate(s, canonical_theme(["battery", "drain"]), "B", days=30)
    assert rate["rate_pct"] == 100.0, \
        "B complains about battery in 100% of its negatives; a global clock read it as 0"


def test_a_product_with_no_corpus_falls_back_instead_of_crashing():
    from echolens.detector.detect import reference_now
    s = _session()
    s.add(Review(source="p", ext_id="a1", rating=1, text="x", product="A", created_at=NOW))
    s.commit()
    assert reference_now(s, "NoSuchProduct") == reference_now(s, "A")


# ── #2/#3 auth on the read surface and the LLM route ────────────────────

@pytest.fixture()
def secured(monkeypatch):
    """A client with auth ACTUALLY required (dev mode disables it, which is why
    the existing suite never noticed these routes were open)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        s.add(Product(name="Alpha")); s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from echolens.config import settings
    monkeypatch.setattr(settings, "echolens_env", "staging")  # auth_required = True
    import echolens.api.app as app_mod
    return TestClient(app_mod.app)


READ_ROUTES = ["/portfolio", "/portfolio/brief", "/portfolio/themes", "/portfolio/transfers",
               "/costs", "/costs/summary", "/archive", "/sources", "/overview", "/brief",
               "/patterns", "/themes", "/calibration", "/anomalies", "/investigations",
               "/feed/summary", "/feed/candidates", "/snapshot", "/fixwatch", "/collectors"]


@pytest.mark.parametrize("route", READ_ROUTES)
def test_read_routes_require_a_signed_in_user(secured, route):
    """These leaked findings, spend and connected sources to anyone with the URL."""
    assert secured.get(route).status_code == 401, f"{route} is readable without a token"


def test_health_stays_open_for_the_platform_probe(secured):
    assert secured.get("/health").status_code == 200


def test_llm_spending_route_is_not_anonymous(secured):
    """POST /findings/{id}/recommend calls OpenAI — it was unauthenticated AND
    unrate-limited, so anyone could burn the API budget in a loop."""
    assert secured.post("/findings/1/recommend").status_code == 401


def test_work_triggering_routes_are_not_anonymous(secured):
    assert secured.post("/anomalies/scan").status_code == 401
    assert secured.post("/collect/run").status_code == 401
