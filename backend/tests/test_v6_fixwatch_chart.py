"""GET /fixwatch must serve the before/after chart it already stores.

`before_after()` computes the chart and _confirm/_inconclusive/_reopen persist
it to FixWatch.chart_json, but the list route never serialized it — so the data
sat in the database with no way to reach it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens import fixwatch
from echolens.db import session as db_session
from echolens.db.models import (AnomalyEvent, Base, CollectorState, Finding,
                                Investigation, Product, Review)

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


def _seed(s, label, before_per_day, after_per_day, days_since_fix, n):
    """A watch that has run its course, with a real complaint history."""
    p = Product(name=label)
    s.add(p)
    s.flush()
    s.add(CollectorState(source="play_store", identifier=label, product=label,
                         status="healthy", enabled=True, last_run_at=NOW,
                         product_id=p.id))
    a = AnomalyEvent(slug=f"fw{n}", type="volume_spike", metric="battery drain",
                     delta=1.0, z=3.0, window="7d", description="d",
                     status="investigating", product_id=p.id)
    s.add(a)
    s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", budget_tier="standard",
                        product_id=p.id)
    s.add(inv)
    s.flush()
    f = Finding(investigation_id=inv.id, product_id=p.id, confidence=0.9,
                status="approved", summary="battery drain from a wakelock")
    s.add(f)
    s.flush()
    fixed = NOW - timedelta(days=days_since_fix)
    for tag, start, per in (("b", fixed - timedelta(days=20), before_per_day),
                            ("a", fixed, after_per_day)):
        for d in range(20):
            for i in range(per):
                s.add(Review(source="play_store", ext_id=f"{n}{tag}{d}{i}", rating=1,
                             text="battery drain is terrible",
                             created_at=start + timedelta(days=d), product=label))
    s.flush()
    w = fixwatch.link_issue(s, f, "acme/x", 200 + n)
    w.product_id = p.id
    s.flush()
    fixwatch.on_issue_closed(s, "acme/x", 200 + n, closed_at=fixed)
    fixwatch.evaluate(s, as_of=NOW)
    return p, w


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session_)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from fastapi.testclient import TestClient
    from echolens.api.app import app
    return TestClient(app), Session_


def test_a_confirmed_watch_serves_its_before_after_chart(client):
    c, Session_ = client
    with Session_() as s:
        p, w = _seed(s, "FIXED", 5, 0, 40, 1)
        s.commit()
        pid, status = p.id, w.status
    assert status == "confirmed"

    row = c.get(f"/fixwatch?product_id={pid}").json()["watches"][0]
    chart = row["chart"]
    assert chart is not None, "the chart is stored but was never serialized"
    assert chart["before"] and chart["after"]
    assert chart["before_rate"] > 0
    assert chart["after_rate"] == 0.0
    assert all({"date", "count"} <= set(p) for p in chart["before"])


def test_a_watch_still_watching_carries_no_chart(client):
    """chart_json is only written at a terminal transition, so sending the key
    for an in-flight watch would ship a day-by-day series of nulls per row."""
    c, Session_ = client
    with Session_() as s:
        p, w = _seed(s, "EARLY", 5, 5, 6, 2)
        s.commit()
        pid, status = p.id, w.status
    assert status == "watching"
    assert c.get(f"/fixwatch?product_id={pid}").json()["watches"][0]["chart"] is None


def test_the_chart_matches_what_the_case_detail_already_showed(client):
    """The case-detail route has served this same object as fix.chart all along;
    the two must not drift into different shapes."""
    c, Session_ = client
    with Session_() as s:
        p, w = _seed(s, "SAME", 6, 1, 40, 3)
        s.commit()
        pid, inv_id = p.id, w.investigation_id

    from_list = c.get(f"/fixwatch?product_id={pid}").json()["watches"][0]["chart"]
    detail = c.get(f"/investigations/{inv_id}?product_id={pid}").json()
    from_detail = (detail.get("finding") or {}).get("fix", {}).get("chart")
    assert from_detail is not None
    assert from_list == from_detail
