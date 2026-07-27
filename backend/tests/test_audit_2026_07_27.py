"""Regressions for the 27 Jul 2026 audit.

One test per finding, named for what would break if the fix were reverted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from echolens.db.models import Base, CollectorState, Review

NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)()


def _collector(db, *, status="healthy", last_run=NOW, product="Lumo", enabled=True):
    db.add(CollectorState(source="play_store", identifier="com.lumo", product=product,
                          status=status, last_run_at=last_run, enabled=enabled))
    db.flush()


# ── P1: a dead collector must not read as a verified fix ───────────────

def test_a_window_with_no_collector_is_unobservable(db):
    """The bug: complaint_series pre-fills every day with 0, so `if not series`
    could never fire and _rate always returned 0.0 — which reads as "complaints
    stopped", i.e. a confirmed fix, when in truth nothing was watching."""
    from echolens.fixwatch import _rate
    assert _rate(db, ["battery"], NOW - timedelta(days=14), NOW, "Lumo") is None


def test_an_errored_collector_is_unobservable(db):
    from echolens.fixwatch import _rate
    _collector(db, status="error")
    assert _rate(db, ["battery"], NOW - timedelta(days=14), NOW, "Lumo") is None


def test_a_collector_that_never_ran_in_the_window_is_unobservable(db):
    """Healthy, but its last run predates the window — it saw none of it."""
    from echolens.fixwatch import _rate
    _collector(db, last_run=NOW - timedelta(days=90))
    assert _rate(db, ["battery"], NOW - timedelta(days=14), NOW, "Lumo") is None


def test_a_live_collector_seeing_nothing_really_is_zero(db):
    """The other half: silence from a WORKING collector is real evidence and
    must stay 0.0, not become None."""
    from echolens.fixwatch import _rate
    _collector(db)
    assert _rate(db, ["battery"], NOW - timedelta(days=14), NOW, "Lumo") == 0.0


def test_a_live_collector_with_complaints_measures_them(db):
    from echolens.fixwatch import _rate
    _collector(db)
    for i in range(14):
        db.add(Review(source="play_store", ext_id=f"r{i}", product="Lumo",
                      text="battery drains fast", rating=1,
                      created_at=NOW - timedelta(days=i)))
    db.flush()
    assert _rate(db, ["battery"], NOW - timedelta(days=14), NOW, "Lumo") > 0.9


# ── P2: a long repo must not collapse every issue onto one ext_id ──────

def test_issue_ext_id_keeps_the_number_on_a_long_repo():
    """`f"{repo}#{number}"[:64]` truncated from the RIGHT, cutting the issue
    number off. A 74-char repo gave one id for every issue, so every issue
    after the first was dropped as a duplicate."""
    from echolens.collectors.github import _issue_ext_id
    repo = "my-org-with-a-really-long-organisation-name/some-very-long-repository"
    ids = {_issue_ext_id(repo, n) for n in (1, 1234, 5678, 999999)}
    assert len(ids) == 4
    assert all(len(i) <= 64 for i in ids)


def test_issue_ext_id_is_unchanged_for_normal_repos():
    """Short repos must keep the readable form, or every existing row's id
    changes and the whole corpus re-imports as new."""
    from echolens.collectors.github import _issue_ext_id
    assert _issue_ext_id("Adityabeecha/Issues", 42) == "Adityabeecha/Issues#42"


def test_two_long_repos_sharing_a_prefix_stay_distinct():
    from echolens.collectors.github import _issue_ext_id
    a, b = "x" * 60 + "/alpha-repository", "x" * 60 + "/beta-repository"
    assert _issue_ext_id(a, 7) != _issue_ext_id(b, 7)
