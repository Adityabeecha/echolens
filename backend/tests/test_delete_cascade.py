"""Deleting a product must remove everything that points at it.

The purge list is hand-maintained, so every table added since it was written is
a table it silently forgets. On SQLite (no FK enforcement) that leaves orphans;
on Postgres — production — it is an IntegrityError and the delete just fails,
which is what a user sees as "delete is not working".
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens import collab
from echolens.config import settings
from echolens.db import session as db_session
from echolens.db.models import (AnomalyEvent, Base, Comment, FeedbackEntry,
                                Investigation, Mention, Product, Review,
                                ReviewRequest, User)


@pytest.fixture()
def client(monkeypatch):
    """FK enforcement ON, so this fixture behaves like production Postgres."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session_)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    monkeypatch.setattr(settings, "echolens_env", "dev", raising=False)
    from fastapi.testclient import TestClient
    from echolens.api.app import app
    return TestClient(app), Session_


def _product_with_everything(Session_) -> int:
    """A product carrying a row in every table the purge list must cover."""
    with Session_() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        a = AnomalyEvent(slug="x", type="volume_spike", metric="battery drain", delta=1.0,
                         z=3.0, window="7d", description="d", status="investigating",
                         product_id=p.id)
        s.add(a)
        s.flush()
        inv = Investigation(anomaly_id=a.id, status="resolved", budget_tier="standard",
                            product_id=p.id)
        s.add(inv)
        s.flush()
        ana = User(email="ana@acme.com", password_hash="x", role="reviewer")
        bo = User(email="bo@acme.com", password_hash="x", role="reviewer")
        s.add_all([ana, bo])
        s.flush()
        # v5 collaboration
        collab.add_comment(s, inv.id, "the wakelock again @bo", ana.id)
        collab.request_review(s, inv.id, ana.id, requested_of_id=bo.id)
        # v2 sources all land in FeedbackEntry, keyed by product NAME
        s.add(FeedbackEntry(channel="hacker_news", ext_id="hacker_news:1",
                            text="battery dies overnight", product="Lumo",
                            created_at=a.created_at))
        s.add(Review(source="play_store", ext_id="r1", rating=1, text="bad",
                     created_at=a.created_at, product="Lumo"))
        s.commit()
        return p.id


def test_deleting_a_product_with_comments_actually_deletes_it(client):
    """The reported bug: on Postgres this raised FOREIGN KEY constraint failed
    and the product survived."""
    c, Session_ = client
    pid = _product_with_everything(Session_)

    r = c.delete(f"/products/{pid}?confirm=Lumo")
    assert r.status_code == 200, r.text

    with Session_() as s:
        assert s.get(Product, pid) is None


def test_no_collaboration_rows_are_left_orphaned(client):
    """A comment pointing at a deleted product is invisible in every UI but
    still counted by the team dashboard."""
    c, Session_ = client
    pid = _product_with_everything(Session_)
    c.delete(f"/products/{pid}?confirm=Lumo")

    with Session_() as s:
        assert s.scalars(select(Comment)).all() == []
        assert s.scalars(select(Mention)).all() == []
        assert s.scalars(select(ReviewRequest)).all() == []


def test_the_v2_source_corpus_is_deleted_too(client):
    """FeedbackEntry is keyed by product NAME, so a product recreated with the
    same name would silently inherit the old one's Hacker News / Stack Overflow
    / Discussions corpus."""
    c, Session_ = client
    pid = _product_with_everything(Session_)
    c.delete(f"/products/{pid}?confirm=Lumo")

    with Session_() as s:
        assert s.scalars(select(FeedbackEntry)).all() == []
        assert s.scalars(select(Review)).all() == []


def test_deletion_still_requires_the_exact_name(client):
    c, Session_ = client
    pid = _product_with_everything(Session_)
    assert c.delete(f"/products/{pid}?confirm=wrong").status_code == 422
    with Session_() as s:
        assert s.get(Product, pid) is not None
