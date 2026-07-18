"""Collectors: incremental watermark, dedup, keyword filter — offline via
injected fetchers (v1.0)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from echolens.collectors.github import GitHubCollector
from echolens.collectors.play_store import PlayStoreCollector
from echolens.collectors.registry import add_source
from echolens.db.models import Base, CollectorState, Issue, Release, Review


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)()


def _dt(d):
    return datetime(2026, 7, d, tzinfo=timezone.utc)


def test_play_store_ingest_and_dedup(db):
    payload = [
        {"reviewId": "r1", "score": 1, "content": "battery dies", "reviewCreatedVersion": "3.2.0", "at": _dt(12)},
        {"reviewId": "r2", "score": 5, "content": "great", "reviewCreatedVersion": "3.2.0", "at": _dt(13)},
    ]
    c = PlayStoreCollector("com.lumo.photos", fetch_fn=lambda: payload)
    r = c.run(db)
    assert (r.fetched, r.inserted) == (2, 2)
    # re-run same payload → all duplicates, nothing inserted
    r2 = c.run(db)
    assert r2.inserted == 0
    assert db.query(Review).count() == 2
    assert db.query(Review).first().product == "com.lumo.photos"


def test_play_store_incremental_watermark(db):
    c = PlayStoreCollector("app", fetch_fn=lambda: [
        {"reviewId": "r1", "score": 1, "content": "x", "at": _dt(12)}])
    c.run(db)
    # a newer payload including the old one → only the newer review is ingested
    c2 = PlayStoreCollector("app", fetch_fn=lambda: [
        {"reviewId": "r1", "score": 1, "content": "x", "at": _dt(12)},
        {"reviewId": "r2", "score": 2, "content": "y", "at": _dt(14)}])
    r = c2.run(db)
    assert r.fetched == 1 and r.inserted == 1  # r1 filtered by watermark


def test_github_issues_labels_reactions_and_releases(db):
    payload = {
        "issues": [{"number": 42, "title": "wakelock", "body": "leak", "state": "open",
                    "labels": [{"name": "bug"}, {"name": "battery"}],
                    "reactions": {"total_count": 9},
                    "created_at": "2026-07-11T00:00:00Z", "updated_at": "2026-07-11T00:00:00Z"}],
        "releases": [{"tag_name": "3.2.0", "name": "v3.2", "body": "sync",
                      "published_at": "2026-07-08T00:00:00Z"}],
    }
    r = GitHubCollector("lumo/app", fetch_fn=lambda: payload).run(db)
    assert r.inserted == 2
    issue = db.query(Issue).one()
    assert issue.reactions == 9 and issue.labels == ["bug", "battery"]
    assert db.query(Release).one().version == "3.2.0"


def test_collector_records_error_without_crashing(db):
    def boom():
        raise RuntimeError("network down")
    r = PlayStoreCollector("app", fetch_fn=boom).run(db)
    assert not r.ok and "network down" in r.error
    st = db.query(CollectorState).one()
    assert st.status == "error" and st.last_error


def test_registry_add_source(db):
    add_source(db, "play_store", "com.a", "ProductA")
    add_source(db, "github", "org/repo", "ProductA")
    assert db.query(CollectorState).count() == 2


def test_reddit_source_is_rejected(db):
    # Reddit was dropped as a live source (free API ended 2026).
    import pytest as _pytest
    with _pytest.raises(ValueError):
        add_source(db, "reddit", "LumoApp")
