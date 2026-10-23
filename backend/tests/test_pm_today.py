"""Today overview: release markers, rating-drop breakdown, health, freshness."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens.db.models import (
    AnomalyEvent, Base, CollectorState, Finding, Investigation, Product, Release, Review)

NOW = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _product(s, name):
    p = Product(name=name)
    s.add(p); s.flush()
    return p


_seq = iter(range(10**6))


def _reviews(s, product, n, text, rating, days_ago):
    for i in range(n):
        s.add(Review(source="play_store", ext_id=f"r{next(_seq)}", rating=rating, text=text,
                     product=product, created_at=NOW - timedelta(days=days_ago, minutes=i)))
    s.flush()


def _baseline(s, product):
    """28 steady prior days and a recent week where battery complaints surge."""
    # prior: 36 happy, 4 crash complaints  → avg 4.6
    _reviews(s, product, 36, "love it, works great", 5, days_ago=20)
    _reviews(s, product, 4, "app crashes on launch", 1, days_ago=15)
    # recent: 14 happy, 1 crash, 5 battery complaints → avg 3.8
    _reviews(s, product, 14, "love it, works great", 5, days_ago=2)
    _reviews(s, product, 1, "app crashes on launch", 1, days_ago=1)
    _reviews(s, product, 5, "battery drain is terrible since update", 1, days_ago=0)


def _resolved_case(s, product, summary):
    a = AnomalyEvent(slug=f"a-{next(_seq)}", type="theme_volume_surge", metric="battery",
                     delta=0.3, z=3.0, window="7d", description=summary, status="closed",
                     product_id=product.id)
    s.add(a); s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                        budget_tier="standard", product_id=product.id)
    s.add(inv); s.flush()
    s.add(Finding(investigation_id=inv.id, summary=summary, confidence=0.9, status="approved",
                  json={"summary": summary, "prose": summary}, product_id=product.id))
    s.flush()
    return inv


# ── health ──────────────────────────────────────────────────────────────

def test_health_is_the_inverse_of_attention_and_reads_the_right_way_round():
    from echolens.portfolio import HEALTH_LABELS, _band, health
    assert health(0) == 100.0 and health(30) == 70.0 and health(140) == 0.0
    assert HEALTH_LABELS[_band(0)[0]] == "Healthy"
    assert HEALTH_LABELS[_band(10)[0]] == "Watch"
    assert HEALTH_LABELS[_band(30)[0]] == "Needs attention"
    assert HEALTH_LABELS[_band(80)[0]] == "Needs you today"


def test_portfolio_rows_carry_health_and_still_rank_by_attention(session):
    from echolens.portfolio import portfolio
    calm, busy = _product(session, "calm"), _product(session, "busy")
    session.add(AnomalyEvent(slug="sig", type="x", metric="m", delta=0, z=0, window="7d",
                             description="d", status="pending", product_id=busy.id))
    session.flush()
    rows = portfolio(session, NOW)["products"]
    assert [r["product"] for r in rows] == ["busy", "calm"]   # attention order kept
    for r in rows:
        assert r["health"] == max(0.0, round(100 - r["score"], 1))
    assert rows[1]["health"] == 100.0 and rows[1]["health_label"] == "Healthy"
    assert rows[0]["health"] < rows[1]["health"]


# ── releases ────────────────────────────────────────────────────────────

def test_releases_are_scoped_to_the_product_and_the_chart_window(session):
    from echolens.overview import releases_in_window
    session.add_all([
        Release(version="3.2.0", notes="", released_at=datetime(2026, 7, 10), product="lumo"),
        Release(version="v3.1.0", notes="", released_at=datetime(2026, 6, 1), product="lumo"),
        Release(version="1.0.0", notes="", released_at=datetime(2026, 1, 1), product="lumo"),
        Release(version="9.9.9", notes="", released_at=datetime(2026, 7, 12), product="other"),
    ])
    session.flush()
    rels = releases_in_window(session, "lumo", NOW)
    assert [r["version"] for r in rels] == ["v3.1.0", "3.2.0"]   # oldest first, in-window only
    assert rels[1]["label"] == "v3.2.0 shipped Jul 10"
    assert rels[0]["label"] == "v3.1.0 shipped Jun 1"


# ── rating-drop breakdown ───────────────────────────────────────────────

def test_breakdown_parts_sum_to_the_drop_and_name_the_surging_theme(session):
    from echolens.overview import rating_breakdown
    p = _product(session, "lumo")
    _baseline(session, "lumo")
    inv = _resolved_case(session, p, "Battery drain after 3.2 wakelock")
    b = rating_breakdown(session, p, NOW)
    assert b["dropped"] is True and b["estimate"] is True
    assert b["delta"] == pytest.approx(3.8 - 4.6, abs=0.01)
    parts = b["parts"]
    assert parts[-1]["theme_id"] == "other"
    assert round(sum(x["contribution"] for x in parts), 2) == b["delta"]
    top = parts[0]
    assert top["theme_id"] == "battery-drain" and top["contribution"] < 0
    assert top["case_id"] == inv.id
    assert f"(case #{inv.id})" in b["summary"]
    assert b["summary"].startswith("Rating −0.80★ vs prior 4 weeks:")
    # the battery surge explains most of the fall
    assert top["contribution"] <= b["delta"] / 2


def test_breakdown_is_silent_when_rating_did_not_drop_or_data_is_thin(session):
    from echolens.overview import rating_breakdown
    p = _product(session, "steady")
    _reviews(session, "steady", 3, "fine", 4, days_ago=1)
    thin = rating_breakdown(session, p, NOW)
    assert thin["dropped"] is False and thin["reason"] and thin["parts"] == []

    _reviews(session, "steady", 20, "fine", 4, days_ago=10)
    _reviews(session, "steady", 5, "great", 5, days_ago=0)
    up = rating_breakdown(session, p, NOW)
    assert up["dropped"] is False and up["delta"] > 0 and up["parts"] == []


def test_breakdown_ignores_other_products_reviews(session):
    from echolens.overview import rating_breakdown
    p = _product(session, "quiet")
    _reviews(session, "quiet", 10, "fine", 4, days_ago=10)
    _reviews(session, "quiet", 10, "fine", 4, days_ago=1)
    _baseline(session, "noisy")
    assert rating_breakdown(session, p, NOW)["dropped"] is False


# ── freshness ───────────────────────────────────────────────────────────

def test_freshness_reports_the_latest_pull_across_the_products_sources(session):
    from echolens.overview import freshness
    p, q = _product(session, "lumo"), _product(session, "other")
    session.add_all([
        CollectorState(source="play_store", identifier="a", product="lumo", product_id=p.id,
                       last_run_at=NOW - timedelta(hours=3)),
        # an older row with no product_id still belongs to lumo by name
        CollectorState(source="github", identifier="o/r", product="lumo", product_id=None,
                       last_run_at=NOW - timedelta(minutes=12)),
        CollectorState(source="play_store", identifier="b", product="other", product_id=q.id,
                       last_run_at=NOW - timedelta(minutes=1)),
    ])
    session.flush()
    f = freshness(session, p, NOW)
    assert f["age_minutes"] == 12 and f["stale"] is False and f["sources"] == 2
    old = freshness(session, p, NOW + timedelta(hours=7))
    assert old["stale"] is True
    empty = freshness(session, _product(session, "none"), NOW)
    assert empty["last_synced_at"] is None and empty["stale"] is False


# ── API ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        p = _product(s, "lumo")
        _baseline(s, "lumo")
        s.add(Release(version="3.2.0", notes="", released_at=NOW - timedelta(days=1),
                      product="lumo"))
        s.add(CollectorState(source="play_store", identifier="a", product="lumo",
                             product_id=p.id, last_run_at=datetime.now(timezone.utc)
                             - timedelta(minutes=5)))
        s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from echolens.api.app import app
    return TestClient(app)


def test_overview_endpoint_and_sources_freshness(client):
    o = client.get("/today/overview?product_id=1")
    assert o.status_code == 200
    body = o.json()
    assert [r["version"] for r in body["releases"]] == ["3.2.0"]
    assert body["rating_breakdown"]["dropped"] is True
    assert body["freshness"]["stale"] is False and body["freshness"]["age_minutes"] <= 6
    assert client.get("/today/overview?product_id=999").status_code == 404

    src = client.get("/sources?product_id=1").json()
    assert src["last_synced"]["sources"] == 1

    row = client.get("/portfolio").json()["products"][0]
    assert {"health", "health_label", "score", "band"} <= set(row)
