"""Regression coverage for the 2 Aug 2026 backend audit."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.collectors.base import Collector
from echolens.collectors.github import GitHubCollector
from echolens.config import settings
from echolens.db import session as db_session
from echolens.db.models import (
    AnomalyEvent, Base, FeedbackEntry, Finding, Investigation, Post, Product,
    Release, Review,
)


@pytest.fixture()
def api_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from echolens.api.app import app
    return TestClient(app), Session


def test_guest_without_a_demo_cannot_fall_through_to_workspace_scope(
        api_db, monkeypatch):
    client, Session = api_db
    with Session() as session:
        product = Product(name="Private", is_demo=False)
        session.add(product)
        session.flush()
        session.add(AnomalyEvent(
            slug="private", type="manual", metric="secret", delta=0, z=0,
            window="n/a", description="private", status="pending",
            product_id=product.id))
        session.commit()
    monkeypatch.setattr(settings, "echolens_env", "staging")
    monkeypatch.setattr(settings, "allow_guest", True)
    monkeypatch.setattr(settings, "guest_demo_only", True)
    response = client.get("/anomalies")
    assert response.status_code == 404


def test_anomaly_slug_is_resolved_inside_the_requested_product(api_db):
    client, Session = api_db
    with Session() as session:
        a = Product(name="A")
        b = Product(name="B")
        session.add_all([a, b])
        session.flush()
        session.add(AnomalyEvent(
            slug="only-b", type="manual", metric="m", delta=0, z=0,
            window="n/a", description="b", status="pending", product_id=b.id))
        session.commit()
        aid = a.id
    response = client.post("/investigations", json={
        "anomaly_slug": "only-b", "product_id": aid,
    })
    assert response.status_code == 404


def test_request_bounds_reject_pathological_batches(api_db):
    client, _ = api_db
    assert client.get("/investigations/1/trace?after=-999999999999").status_code == 422
    assert client.post("/queue/themes", json={"slugs": ["x"] * 101}).status_code == 422
    assert client.put("/settings/limits", json={"daily_investigations": 1_000_000}).status_code == 422
    assert client.post("/mentions/read", json=list(range(201))).status_code == 422


def test_external_ids_are_unique_per_product(session):
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    session.add_all([
        Review(source="x", ext_id="same", rating=1, text="a", created_at=now, product="A"),
        Review(source="x", ext_id="same", rating=1, text="b", created_at=now, product="B"),
        Post(source="x", ext_id="same", text_snippet="a", created_at=now, product="A"),
        Post(source="x", ext_id="same", text_snippet="b", created_at=now, product="B"),
        FeedbackEntry(channel="support", ext_id="same", text="a", created_at=now, product="A"),
        FeedbackEntry(channel="support", ext_id="same", text="b", created_at=now, product="B"),
    ])
    session.flush()
    assert session.scalar(select(func.count(Review.id)).where(Review.ext_id == "same")) == 2
    assert session.scalar(select(func.count(Post.id)).where(Post.ext_id == "same")) == 2
    assert session.scalar(select(func.count(FeedbackEntry.id)).where(
        FeedbackEntry.ext_id == "same")) == 2


def test_challenge_keeps_the_original_product(session):
    from echolens.review import record_challenge
    product = Product(name="A")
    session.add(product)
    session.flush()
    anomaly = AnomalyEvent(slug="a", type="manual", metric="m", delta=0, z=0,
                           window="n/a", description="a", status="pending",
                           product_id=product.id)
    session.add(anomaly)
    session.flush()
    inv = Investigation(anomaly_id=anomaly.id, status="needs_review", product_id=product.id)
    session.add(inv)
    session.flush()
    finding = Finding(investigation_id=inv.id, product_id=product.id, status="pending",
                      summary="cause", confidence=0.8, json={})
    session.add(finding)
    session.flush()
    reopened = record_challenge(session, finding, "check another cause")
    assert reopened.product_id == product.id


def test_github_honors_limit_and_skips_undated_releases(session):
    issues = [{
        "number": n, "title": str(n), "body": "", "state": "open",
        "created_at": f"2026-08-0{n}T00:00:00Z",
        "updated_at": f"2026-08-0{n}T00:00:00Z",
    } for n in (1, 2, 3)]
    collector = GitHubCollector("org/repo", product="A",
                                fetch_fn=lambda: {"issues": issues, "releases": []})
    result = collector.run(session, limit=2)
    assert result.fetched == 2
    inserted, _ = collector._ingest_release(session, {
        "kind": "release", "tag_name": "v-no-date", "body": "notes",
    })
    assert inserted is False
    assert session.scalars(select(Release).where(Release.version == "v-no-date")).first() is None


class _DuplicateCollector(Collector):
    source = "duplicate-test"

    def fetch(self, since, limit):
        return [{"n": 1}, {"n": 2}]

    def ingest_item(self, session, item):
        session.add(Review(source="x", ext_id="duplicate", rating=1,
                           text=str(item["n"]), product=self.product,
                           created_at=datetime(2026, 8, 2, tzinfo=timezone.utc)))
        return True, str(item["n"])


def test_constraint_failure_does_not_poison_shared_collector_session(session):
    result = _DuplicateCollector("same", product="A").run(session)
    assert result.failed_items == 1
    assert session.scalar(select(func.count(Review.id)).where(
        Review.ext_id == "duplicate", Review.product == "A")) == 1
    # A later write on the same scheduler session still succeeds.
    session.add(Product(name="still-usable"))
    session.flush()
