"""You must be able to reach a case while it is still thinking.

The trace streams live over SSE and always has. The problem was access: a
queued case has no Investigation row, so its card carries id=None, is not
clickable, and by the time an id exists the run is usually over. That is why
the reasoning only ever appeared after the fact.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.config import settings
from echolens.db import session as db_session
from echolens.db.models import (AnomalyEvent, Base, Investigation, Product,
                                QueuedInvestigation, TraceStep)


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session_)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    monkeypatch.setattr(settings, "echolens_env", "dev", raising=False)
    return Session_


def _running_case(Session_):
    with Session_() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        a = AnomalyEvent(slug="r1", type="volume_spike", metric="m", delta=1.0, z=3.0,
                         window="7d", description="d", status="investigating",
                         product_id=p.id)
        s.add(a)
        s.flush()
        inv = Investigation(anomaly_id=a.id, status="running", budget_tier="standard",
                            product_id=p.id)
        s.add(inv)
        s.commit()
        return p.id, inv.id


def test_steps_stream_while_the_case_is_still_running(env):
    """The decisive one: steps must arrive AS they are written, not in one
    batch at the end. Timed against the generator directly, because a buffering
    HTTP client would hide the difference."""
    Session_ = env
    _pid, iid = _running_case(Session_)

    def emit():
        for i in range(1, 4):
            time.sleep(0.4)
            with Session_() as s:
                s.add(TraceStep(investigation_id=iid, seq=i, kind="THINK",
                                content_json={"text": f"step {i}"}))
                s.commit()
        time.sleep(0.3)
        with Session_() as s:
            s.get(Investigation, iid).status = "resolved"
            s.commit()

    from echolens.api.app import stream_trace

    class FakeReq:
        headers: dict = {}

        async def is_disconnected(self):
            return False

    async def collect():
        threading.Thread(target=emit, daemon=True).start()
        resp = await stream_trace(iid, FakeReq(), product_id=None, token=None)
        t0 = time.time()
        arrivals = []
        async for chunk in resp.body_iterator:
            txt = chunk if isinstance(chunk, str) else chunk.decode()
            if "event: step" in txt:
                arrivals.append(time.time() - t0)
            if "event: done" in txt:
                break
        return arrivals

    arrivals = asyncio.run(collect())
    assert len(arrivals) == 3
    # Spread out, not delivered together at the end.
    assert arrivals[0] < arrivals[-1] - 0.3, f"steps arrived batched: {arrivals}"


def test_a_queued_case_has_no_id_to_open(env):
    """Pins WHY live viewing was unreachable, so the reason stays documented."""
    Session_ = env
    with Session_() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        a = AnomalyEvent(slug="q1", type="volume_spike", metric="m", delta=1.0, z=3.0,
                         window="7d", description="d", status="pending", product_id=p.id)
        s.add(a)
        s.flush()
        s.add(QueuedInvestigation(anomaly_id=a.id, status="queued", selection_order=1,
                                  product_id=p.id, title="waiting"))
        s.commit()
        pid = p.id

    from fastapi.testclient import TestClient
    from echolens.api.app import app
    c = TestClient(app)
    row = [r for r in c.get(f"/cases?product_id={pid}").json()["cases"]
           if r["status"] == "queued"][0]
    assert row["id"] is None
    # The card is unclickable, so the copy has to say when it becomes openable.
    assert "live" in row["why"].lower()


def test_the_id_appears_the_moment_it_starts(env):
    """What the work-watcher now announces: the case became watchable."""
    Session_ = env
    with Session_() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        a = AnomalyEvent(slug="q1", type="volume_spike", metric="m", delta=1.0, z=3.0,
                         window="7d", description="d", status="pending", product_id=p.id)
        s.add(a)
        s.flush()
        q = QueuedInvestigation(anomaly_id=a.id, status="queued", selection_order=1,
                                product_id=p.id, title="waiting")
        s.add(q)
        s.commit()
        pid, qid, aid = p.id, q.id, a.id

    from fastapi.testclient import TestClient
    from echolens.api.app import app
    c = TestClient(app)
    running = [i for i in c.get(f"/investigations?product_id={pid}").json()["investigations"]
               if i["status"] == "running" and i["id"] is not None]
    assert running == []

    with Session_() as s:                       # the drain claims it
        inv = Investigation(anomaly_id=aid, status="running", budget_tier="standard",
                            product_id=pid)
        s.add(inv)
        s.flush()
        row = s.get(QueuedInvestigation, qid)
        row.status, row.investigation_id = "running", inv.id
        s.commit()

    running = [i for i in c.get(f"/investigations?product_id={pid}").json()["investigations"]
               if i["status"] == "running" and i["id"] is not None]
    assert len(running) == 1, "the watcher needs a concrete id to offer 'Watch live'"
