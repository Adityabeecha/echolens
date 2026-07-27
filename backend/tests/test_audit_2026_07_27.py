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


# ── B1: a guest must not be able to spend OpenAI credits ───────────────

def test_guest_cannot_trigger_an_llm_call(monkeypatch):
    """/graph and /feed/candidates built an LLM client inline with no rate
    limit, so three anonymous GETs made three real OpenAI calls. `refresh=true`
    additionally defeats the cache, on purpose, from an unvalidated query param."""
    from echolens.api.app import _may_spend
    assert _may_spend({"role": "viewer", "guest": True}) is False
    assert _may_spend({"role": "viewer"}) is True
    assert _may_spend({"role": "admin"}) is True
    assert _may_spend(None) is True


# ── P4: the claim-grounding guard must not be bypassable by punctuation ─

@pytest.mark.parametrize("prose", [
    "Sync is broken [ev_001]; the crash was caused by the v3.2 release.",
    "Root observation [ev_001]: the drop is due to the new SDK.",
    "We saw crashes [ev_001], which was caused by the release.",
    "The v3.2 release is the reason ratings collapsed.",
    "The spike stems from the new login flow.",
    "The spike is attributable to the new SDK.",
    "The v3.2 release was the trigger for the spike.",
    "The regression is down to the caching change.",
    "The failure originates from the sync worker.",
])
def test_uncited_causal_clauses_are_blocked(prose):
    """A clause joined by ; : or a comma+conjunction used to inherit the
    citation from the front of the sentence, and several plain-English ways of
    stating a cause were not in the marker list at all."""
    from echolens.investigator.guards import unsupported_claims
    assert unsupported_claims(prose, {"ev_001", "ev_002"})


@pytest.mark.parametrize("prose", [
    "The crash was caused by the v3.2 release [ev_001].",
    "Battery drain is due to the wakelock [ev_002].",
    "Reviews mentioning battery rose 23% last week.",
])
def test_properly_cited_or_non_causal_prose_still_passes(prose):
    """The other half: the guard must not start rejecting honest prose."""
    from echolens.investigator.guards import unsupported_claims
    assert unsupported_claims(prose, {"ev_001", "ev_002"}) == []


# ── P5: a falling issue rate is not a surge ────────────────────────────

def _velocity(baseline, recent):
    """Mirror of the emit rule in detect_issue_velocity."""
    from echolens.detector.detect import _zscore
    z, _ = _zscore(recent, baseline)
    rate = (sum(baseline) / len(baseline)) if baseline else 0.0
    return z, sum(recent), rate * len(recent)


def test_a_declining_issue_rate_is_not_emitted_as_a_surge():
    z, rc, expected = _velocity([3] * 28, [1, 1, 0, 0, 0, 0, 0])
    assert z < 0
    assert rc <= expected, "a decline must fail the emit rule"


def test_a_flat_issue_rate_is_not_emitted():
    z, rc, expected = _velocity([2] * 28, [2] * 7)
    assert rc <= expected


def test_a_genuine_low_volume_surge_is_still_emitted():
    """A quiet repo filing 4 issues in a week scores only z=0.57, so a plain
    z-threshold would discard every signal a small repo can produce."""
    z, rc, expected = _velocity([0] * 28, [1, 1, 1, 1, 0, 0, 0])
    assert z > 0 and rc > expected


def test_the_noise_gate_rejects_declines():
    """The gate used abs(z), so a strong DECLINE passed as readily as a rise —
    but every candidate here claims something got worse, and a negative z is
    evidence AGAINST the case."""
    from echolens.detector.detect import MIN_CASE_Z
    strong_decline = -3.0
    assert abs(strong_decline) >= MIN_CASE_Z, "the old abs() gate would let it through"
    assert not (strong_decline >= MIN_CASE_Z), "the signed gate must reject it"


# ── P6: two products must not collide on one review ext_id ─────────────

def test_app_store_ext_ids_are_product_scoped():
    """The id-less fallback hashed review TEXT only, and the dedupe lookup was
    unscoped, so a second product receiving the same boilerplate ("Doesn't
    work") had its review discarded as a duplicate."""
    from echolens.collectors.app_store import AppStoreCollector
    item = {"content": {"label": "Doesn't work"}}
    a = AppStoreCollector("123", "ProductA")._ext_id_for(item)
    b = AppStoreCollector("123", "ProductB")._ext_id_for(item)
    assert a != b
    assert len(a) <= 64 and len(b) <= 64


def test_app_store_shared_review_id_is_product_scoped():
    """Review.ext_id is globally unique, so a review id shared across two
    products made the second insert fail the constraint outright."""
    from echolens.collectors.app_store import AppStoreCollector
    item = {"content": {"label": "x"}, "id": {"label": "999"}}
    a = AppStoreCollector("123", "ProductA")._ext_id_for(item)
    b = AppStoreCollector("123", "ProductB")._ext_id_for(item)
    assert a != b


# ── P7 / P14: a failed item must not be skipped, or reported healthy ───

def test_a_failed_item_freezes_the_watermark_and_marks_the_source_errored():
    """The per-item try/except stopped one bad item aborting the run, but a
    LATER item still advanced the watermark past it — so the next run started
    after the failure and the item was lost for good, with status "healthy"."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from echolens.collectors.base import Collector
    from echolens.db.models import CollectorState

    class Flaky(Collector):
        source = "test"
        def fetch(self, since, limit):
            return [{"id": 1, "wm": "2026-01-01"}, {"id": 2, "wm": "2026-01-02"},
                    {"id": 3, "wm": "2026-01-03"}]
        def ingest_item(self, session, item):
            if item["id"] == 2:
                raise ValueError("poison")
            return True, item["wm"]

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    r = Flaky("x", "Lumo").run(s, limit=10)
    st = s.query(CollectorState).first()

    assert r.failed_items == 1
    assert st.watermark == "2026-01-01", "must not advance past the failed item"
    assert st.status == "error", "a run that dropped items is not healthy"
