"""Regression coverage for the 2 Aug 2026 backend audit."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
import time

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
    AnomalyEvent, Base, CollectorState, FeedbackEntry, Finding, Investigation, Post, Product,
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


def test_onboard_connects_selected_github_and_optional_sources(api_db, monkeypatch):
    client, Session = api_db
    import importlib
    api_module = importlib.import_module("echolens.api.app")
    monkeypatch.setattr(api_module, "_onboard_bg", lambda product, product_id: None)
    with Session() as session:
        existing = Product(name="Acme", package_name="com.acme.product")
        session.add(existing)
        session.flush()
        session.add(CollectorState(
            source="hacker_news", identifier="Old Acme", product="Acme",
            product_id=existing.id, status="healthy",
            last_run_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        session.commit()

    response = client.post("/onboard", json={
        "play_store": "com.acme.product",
        "github": "acme/product",
        "github_sources": ["github", "github_discussions", "github_activity"],
        "product": "Acme",
        "app_store": "123456789",
        "chrome_web_store": "aapbdbdomjkkjkaonfhkkikfgjllcleb",
        "hacker_news": "Acme",
        "stack_overflow": "acme-product",
    })

    assert response.status_code == 200
    assert response.json()["additional_sources"] == [
        "app_store", "chrome_web_store", "hacker_news", "stack_overflow"]
    with Session() as session:
        rows = session.scalars(select(CollectorState)).all()
        sources = {row.source for row in rows}
    assert sources == {
        "play_store", "github", "github_discussions", "github_activity",
        "app_store", "chrome_web_store", "hacker_news", "stack_overflow",
    }
    assert all(row.status == "running" for row in rows)
    assert all(row.last_run_at is not None for row in rows)


def test_onboarding_watchdog_expires_an_interrupted_backfill(api_db):
    client, Session = api_db
    import importlib
    api_module = importlib.import_module("echolens.api.app")
    with Session() as session:
        product = Product(name="Interrupted", package_name="com.acme.interrupted")
        session.add(product)
        session.flush()
        session.add(CollectorState(
            source="play_store",
            identifier="com.acme.interrupted",
            product=product.name,
            product_id=product.id,
            status="running",
            last_run_at=datetime.now(timezone.utc) - timedelta(minutes=4),
        ))
        session.commit()

    with Session() as session:
        changed = api_module._expire_stuck_onboarding_sources(
            session, now=datetime.now(timezone.utc))
        session.commit()

    assert changed == 1

    response = client.get("/onboard/status?product=Interrupted")

    assert response.status_code == 200
    body = response.json()
    assert body["backfilling"] is False
    assert body["progress"] == {
        "checked_sources": 1,
        "failed_sources": 1,
        "timed_out_sources": 1,
        "total_sources": 1,
        "expected_seconds": 120,
        "timeout_seconds": 180,
        "started_at": body["progress"]["started_at"],
    }
    assert body["sources"][0]["status"] == "error"
    assert "stopped responding" in body["sources"][0]["last_error"].lower()
    with Session() as session:
        persisted = session.scalars(select(CollectorState)).one()
        assert persisted.status == "error"


def test_startup_recovery_expires_a_recent_interrupted_backfill(api_db):
    client, Session = api_db
    import importlib
    api_module = importlib.import_module("echolens.api.app")
    with Session() as session:
        product = Product(name="Restarted Product")
        session.add(product)
        session.flush()
        session.add(CollectorState(
            source="github",
            identifier="owner/repo",
            product=product.name,
            product_id=product.id,
            status="running",
            last_run_at=datetime.now(timezone.utc) - timedelta(seconds=30),
        ))
        session.commit()

    with Session() as session:
        changed = api_module._expire_stuck_onboarding_sources(
            session, expire_all=True)
        session.commit()

    assert changed == 1
    with Session() as session:
        persisted = session.scalars(select(CollectorState)).one()
        assert persisted.status == "error"
        assert persisted.last_error == api_module.ONBOARD_INTERRUPTED_ERROR
    status = client.get("/onboard/status?product=Restarted%20Product").json()
    assert status["progress"]["failed_sources"] == 1
    assert status["progress"]["timed_out_sources"] == 0


def test_collector_deadline_is_reported_as_an_onboarding_timeout(api_db):
    client, Session = api_db
    with Session() as session:
        product = Product(name="Collector Timeout")
        session.add(product)
        session.flush()
        session.add(CollectorState(
            source="github", identifier="owner/repo", product=product.name,
            product_id=product.id, status="error", items_last_run=0,
            last_error="timed out after 180s", last_run_at=datetime.now(timezone.utc),
        ))
        session.commit()

    status = client.get("/onboard/status?product=Collector%20Timeout").json()
    assert status["progress"]["timed_out_sources"] == 1


def test_onboarding_watchdog_keeps_retrying_after_temporary_lock(
        api_db, monkeypatch):
    _client, _Session = api_db
    import importlib
    from contextlib import contextmanager
    api_module = importlib.import_module("echolens.api.app")
    attempts = 0

    @contextmanager
    def flaky_session_scope():
        nonlocal attempts
        attempts += 1
        if attempts <= 3:
            raise RuntimeError("database is locked")
        yield object()

    monkeypatch.setattr(api_module, "session_scope", flaky_session_scope)
    monkeypatch.setattr(api_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        api_module, "_expire_stuck_onboarding_sources",
        lambda _session, _product_id: 1,
    )

    api_module._onboard_watchdog(42)

    assert attempts == 4


def test_unknown_onboard_status_does_not_expire_unscoped_collectors(api_db):
    client, Session = api_db
    with Session() as session:
        session.add(CollectorState(
            source="play_store",
            identifier="com.legacy.unscoped",
            product="Legacy",
            product_id=None,
            status="running",
            last_run_at=datetime.now(timezone.utc) - timedelta(minutes=4),
        ))
        session.commit()

    client.get("/onboard/status?product=Missing")

    with Session() as session:
        state = session.scalars(select(CollectorState)).one()
        assert state.status == "running"


def test_onboard_rejects_unknown_or_empty_github_selection(api_db):
    client, _ = api_db
    unknown = client.post("/onboard", json={
        "play_store": "com.acme.product", "github": "acme/product",
        "github_sources": ["github_magic"],
    })
    assert unknown.status_code == 422
    empty = client.post("/onboard", json={
        "play_store": "com.acme.product", "github": "acme/product",
        "github_sources": [],
    })
    assert empty.status_code == 422


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


def test_collector_network_fetches_overlap_but_ingestion_stays_safe(
        session, monkeypatch):
    from echolens.collectors import registry

    class Slow(Collector):
        def fetch(self, since, limit):
            time.sleep(0.35)
            return []

        def ingest_item(self, db, item):
            return False, None

    class SlowA(Slow):
        source = "slow-a"

    class SlowB(Slow):
        source = "slow-b"

    monkeypatch.setitem(registry._BUILDERS, "slow-a", lambda i, p: SlowA(i, p))
    monkeypatch.setitem(registry._BUILDERS, "slow-b", lambda i, p: SlowB(i, p))
    registry.add_source(session, "slow-a", "a", "Speed")
    registry.add_source(session, "slow-b", "b", "Speed")

    started = time.monotonic()
    results = registry.run_all(session, timeout_s=2)
    elapsed = time.monotonic() - started

    assert elapsed < 0.65, "two 350ms fetches should overlap, not take 700ms"
    assert all(result.error is None for result in results)


def test_finished_source_is_visible_while_another_source_is_still_fetching(
        tmp_path, monkeypatch):
    """A missing intermediate commit makes onboarding look frozen."""
    from echolens.collectors import registry

    fast_fetched = threading.Event()
    slow_started = threading.Event()
    release_slow = threading.Event()

    class Fast(Collector):
        source = "live-fast"

        def fetch(self, since, limit):
            fast_fetched.set()
            return []

        def ingest_item(self, db, item):
            return False, None

    class Slow(Collector):
        source = "live-slow"

        def fetch(self, since, limit):
            slow_started.set()
            release_slow.wait(timeout=2)
            return []

        def ingest_item(self, db, item):
            return False, None

    monkeypatch.setitem(registry._BUILDERS, "live-fast", lambda i, p: Fast(i, p))
    monkeypatch.setitem(registry._BUILDERS, "live-slow", lambda i, p: Slow(i, p))
    engine = create_engine(f"sqlite:///{tmp_path / 'live-progress.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as setup:
        registry.add_source(setup, "live-fast", "fast", "Live")
        registry.add_source(setup, "live-slow", "slow", "Live")
        setup.commit()

    worker_done = threading.Event()

    def collect() -> None:
        with Session() as worker:
            registry.run_all(worker, timeout_s=2)
        worker_done.set()

    thread = threading.Thread(target=collect, daemon=True)
    thread.start()
    assert fast_fetched.wait(timeout=1)
    assert slow_started.wait(timeout=1)
    try:
        deadline = time.monotonic() + 0.75
        fast_status = "idle"
        slow_status = "idle"
        while time.monotonic() < deadline:
            with Session() as observer:
                states = {row.source: row.status for row in
                          observer.scalars(select(CollectorState)).all()}
            fast_status = states["live-fast"]
            slow_status = states["live-slow"]
            if fast_status == "healthy":
                break
            time.sleep(0.02)
        assert fast_status == "healthy"
        assert slow_status == "running"
        assert not worker_done.is_set()
    finally:
        release_slow.set()
        thread.join(timeout=3)


def test_fetch_completed_before_deadline_is_not_timed_out_during_slow_ingestion(
        session, monkeypatch):
    """A queued fetch stays valid even if another source consumes the deadline ingesting."""
    from echolens.collectors import registry

    slow_ingesting = threading.Event()

    class SlowIngest(Collector):
        source = "slow-ingest"

        def fetch(self, since, limit):
            return [{"id": "slow"}]

        def ingest_item(self, db, item):
            slow_ingesting.set()
            time.sleep(0.2)
            return False, None

    class AlreadyFetched(Collector):
        source = "already-fetched"

        def fetch(self, since, limit):
            slow_ingesting.wait(timeout=1)
            return []

        def ingest_item(self, db, item):
            return False, None

    monkeypatch.setitem(registry._BUILDERS, "slow-ingest", lambda i, p: SlowIngest(i, p))
    monkeypatch.setitem(registry._BUILDERS, "already-fetched", lambda i, p: AlreadyFetched(i, p))
    registry.add_source(session, "slow-ingest", "a", "Deadline")
    registry.add_source(session, "already-fetched", "b", "Deadline")

    results = registry.run_all(session, timeout_s=0.1)

    assert all(result.error is None for result in results)


def test_product_scoped_collection_does_not_refetch_other_products(
        session, monkeypatch):
    from echolens.collectors import registry

    fetched: list[str] = []

    class Seen(Collector):
        source = "seen"

        def fetch(self, since, limit):
            fetched.append(self.product)
            return []

        def ingest_item(self, db, item):
            return False, None

    monkeypatch.setitem(registry._BUILDERS, "seen", lambda i, p: Seen(i, p))
    a = Product(name="Scoped A")
    b = Product(name="Scoped B")
    session.add_all([a, b])
    session.flush()
    registry.add_source(session, "seen", "same", a.name, a.id)
    registry.add_source(session, "seen", "same", b.name, b.id)

    results = registry.run_all(session, product_id=a.id, timeout_s=2)

    assert len(results) == 1
    assert fetched == [a.name]
