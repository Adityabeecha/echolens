"""Offline regressions reproduced while triaging the TypeSafe report."""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from echolens.collectors.chrome_web_store import _parse_batch
from echolens.collectors.github import GitHubCollector
from echolens.collectors.github_extra import GitHubActivityCollector
from echolens.collectors.play_store import PlayStoreCollector
from echolens.db.models import Base, FeedbackEntry, Review
from echolens.importers.csv_reviews import import_reviews_csv


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_failed_older_play_review_is_retried_after_newer_success(db):
    rows = [
        {"reviewId": "new", "score": 1, "at": datetime(2026, 1, 3, tzinfo=timezone.utc)},
        {"reviewId": "old", "score": "invalid", "at": datetime(2026, 1, 2, tzinfo=timezone.utc)},
    ]
    collector = PlayStoreCollector("app", fetch_fn=lambda: rows)
    first = collector.run(db)
    assert first.failed_items == 1
    rows[1]["score"] = 2
    collector.run(db)
    assert set(db.scalars(select(Review.ext_id))) == {"gp_new", "gp_old"}


def test_partial_collector_failure_is_not_ok(db):
    collector = PlayStoreCollector("app", fetch_fn=lambda: [
        {"reviewId": "bad", "score": "invalid", "at": datetime(2026, 1, 2)}])
    assert not collector.run(db).ok


@pytest.mark.parametrize("prefetched", [False, True])
def test_failed_review_retains_prior_cursor_for_safe_replay(db, prefetched):
    rows = [{"reviewId": "seed", "score": 1, "at": datetime(2026, 1, 1)}]
    collector = PlayStoreCollector("app", fetch_fn=lambda: rows)
    previous = collector.run(db).watermark
    rows[:] = [
        {"reviewId": "good", "score": 1,
         "at": datetime(2026, 1, 3 if prefetched else 2)},
        {"reviewId": "bad", "score": "invalid", "at": datetime(2026, 1, 2)},
    ]
    # Normal fetch preserves equal-timestamp order; prefetched input bypasses
    # fetch sorting and deliberately supplies newest-first rows.
    result = collector.run(db, prefetched=rows if prefetched else None)
    assert result.failed_items == 1
    assert result.watermark == previous
    assert collector._state(db).watermark == previous
    assert collector._state(db).status == "error"
    rows[1]["score"] = 2
    repaired = collector.run(db)
    assert repaired.ok
    assert repaired.inserted == 1
    assert set(db.scalars(select(Review.ext_id))) == {"gp_seed", "gp_good", "gp_bad"}


def test_github_full_issue_page_does_not_discard_releases(db):
    collector = GitHubCollector("org/repo", fetch_fn=lambda: {
        "issues": [{"number": 1, "created_at": "2026-01-01", "updated_at": "2026-01-02"}],
        "releases": [{"tag_name": "v1", "published_at": "2026-01-03"}],
    })
    assert {row["kind"] for row in collector.fetch(None, 1)} == {"issue", "release"}


def test_github_release_does_not_advance_issue_watermark(db):
    collector = GitHubCollector("org/repo", fetch_fn=lambda: {
        "issues": [{"number": 1, "created_at": "2026-01-01", "updated_at": "2026-01-02"}],
        "releases": [{"tag_name": "v1", "published_at": "2026-01-03"}],
    })
    assert collector.run(db).watermark == "2026-01-02T00:00:00+00:00"


def test_github_descending_issue_failure_preserves_retry_watermark(db):
    collector = GitHubCollector("org/repo", fetch_fn=lambda: {
        "issues": [
            {"number": 2, "created_at": "2026-01-01", "updated_at": "2026-01-03"},
            {"number": 1, "created_at": "2026-01-01", "updated_at": "2026-01-02",
             "reactions": "invalid"},
        ],
        "releases": [],
    })
    result = collector.run(db)
    assert result.failed_items == 1
    assert result.watermark is None


def test_activity_pr_ids_do_not_collide_between_repos_for_same_product(db):
    for repo in ("org/frontend", "org/backend"):
        collector = GitHubActivityCollector(repo, product="Product", fetch_fn=lambda: {
            "pulls": [{"number": 1, "title": "Fix", "merged_at": "2026-01-01"}],
            "commits": [],
        })
        collector.run(db)
    assert len(db.scalars(select(FeedbackEntry)).all()) == 2


@pytest.mark.parametrize("inner", [{"error": "changed"}, ["changed"], [[{"text": "changed"}]]])
def test_chrome_changed_inner_envelope_fails_loudly(inner):
    payload = json.dumps([["wrb.fr", "ugvhpe", json.dumps(inner)]])
    with pytest.raises(RuntimeError, match="unrecognised response shape"):
        _parse_batch(payload)


@pytest.mark.parametrize("rating", ["-1", "0", "6", "1.5", "inf", "nan"])
def test_invalid_csv_stars_are_reported_unrated(db, rating):
    result = import_reviews_csv(db, f"text,rating,date\nFeedback,{rating},2026-01-01\n")
    assert result["unrated"] == 1
    assert result["imported"] == 0
