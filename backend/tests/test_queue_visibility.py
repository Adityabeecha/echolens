"""Queued work must be visible to the thing that polls for it.

The frontend's work-watcher polls GET /investigations and refreshes the lists
when the busy count changes. A queued item has no Investigation row until it is
claimed, so returning only Investigation rows made the watcher see an idle
workspace: it stopped polling, and the queue only appeared to advance when the
user reloaded the page.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.config import settings
from echolens.db import session as db_session
from echolens.db.models import (AnomalyEvent, Base, Investigation, Product,
                                QueuedInvestigation)


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session_)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    monkeypatch.setattr(settings, "echolens_env", "dev", raising=False)
    from fastapi.testclient import TestClient
    from echolens.api.app import app
    return TestClient(app), Session_


def _anomaly(s, product, slug):
    a = AnomalyEvent(slug=slug, type="volume_spike", metric="map inaccurate", delta=1.0,
                     z=3.0, window="7d", description="d", status="pending",
                     product_id=product.id)
    s.add(a)
    s.flush()
    return a


def _busy(payload):
    return [i for i in payload["investigations"]
            if i["status"] in ("running", "queued")]


def test_a_queued_item_is_visible_to_the_work_watcher(client):
    """The reported bug: two queued cases, and the watcher saw zero busy work."""
    c, Session_ = client
    with Session_() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        for i in (1, 2):
            a = _anomaly(s, p, f"q{i}")
            s.add(QueuedInvestigation(anomaly_id=a.id, status="queued",
                                      selection_order=i, product_id=p.id,
                                      title=f"queued {i}"))
        s.commit()
        pid = p.id

    payload = c.get(f"/investigations?product_id={pid}").json()
    assert len(_busy(payload)) == 2


def test_a_claimed_queue_row_is_not_counted_twice(client):
    """Once claimed, the queue row points at a real Investigation. Counting both
    would make the busy count jump, and the watcher reads a rise as new work."""
    c, Session_ = client
    with Session_() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        a = _anomaly(s, p, "q1")
        inv = Investigation(anomaly_id=a.id, status="running", budget_tier="standard",
                            product_id=p.id)
        s.add(inv)
        s.flush()
        s.add(QueuedInvestigation(anomaly_id=a.id, status="running", selection_order=1,
                                  product_id=p.id, investigation_id=inv.id))
        s.commit()
        pid = p.id

    assert len(_busy(c.get(f"/investigations?product_id={pid}").json())) == 1


def test_the_queue_advancing_is_observable(client):
    """queued -> running keeps the busy COUNT identical, so the watcher has to
    see the composition change or the row stays 'Queued' on screen forever."""
    c, Session_ = client
    with Session_() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        a = _anomaly(s, p, "q1")
        q = QueuedInvestigation(anomaly_id=a.id, status="queued", selection_order=1,
                                product_id=p.id, title="queued 1")
        s.add(q)
        s.commit()
        pid, qid = p.id, q.id

    before = _busy(c.get(f"/investigations?product_id={pid}").json())
    assert [i["status"] for i in before] == ["queued"]

    with Session_() as s:                       # the drain claims it
        row = s.get(QueuedInvestigation, qid)
        a = s.get(AnomalyEvent, row.anomaly_id)
        inv = Investigation(anomaly_id=a.id, status="running", budget_tier="standard",
                            product_id=pid)
        s.add(inv)
        s.flush()
        row.status, row.investigation_id = "running", inv.id
        s.commit()

    after = _busy(c.get(f"/investigations?product_id={pid}").json())
    assert len(after) == len(before), "the count is unchanged — that is the trap"
    assert [i["status"] for i in after] == ["running"]


def test_queued_rows_stay_product_scoped(client):
    c, Session_ = client
    with Session_() as s:
        lumo, other = Product(name="Lumo"), Product(name="Other")
        s.add_all([lumo, other])
        s.flush()
        a = _anomaly(s, other, "o1")
        s.add(QueuedInvestigation(anomaly_id=a.id, status="queued", selection_order=1,
                                  product_id=other.id, title="not yours"))
        s.commit()
        lumo_id = lumo.id

    assert _busy(c.get(f"/investigations?product_id={lumo_id}").json()) == []
