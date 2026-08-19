"""Regressions for the 27 Jul 2026 audit.

One test per finding, named for what would break if the fix were reverted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from echolens.config import settings
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


# ── F1: a per-product limit must save to the product, not the workspace ─

def test_limits_save_to_the_product_the_screen_is_showing(monkeypatch):
    """Settings READ through /costs/summary, which is product-scoped and layers
    the per-product override on top, but WROTE unscoped — so on any product
    carrying an override the save landed in a row the read ignores. The admin
    got a green "Limit saved." toast and the number silently reverted."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import echolens.db.session as db_session
    from echolens.db.models import Product
    from echolens.auth import create_token, create_user

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng, expire_on_commit=False)
    with S() as s:
        p = Product(name="Lumo", limits_json={"daily_investigations": 5})
        s.add(p); s.flush()
        pid = p.id
        tok = create_token(create_user(s, "a@b.c", "pw", "admin"))
        s.commit()
    monkeypatch.setattr(db_session, "_engine", eng)
    monkeypatch.setattr(db_session, "_SessionLocal", S)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: eng)
    monkeypatch.setattr(settings, "echolens_env", "staging")

    from echolens.api.app import app, _limits
    tc = TestClient(app)
    h = {"Authorization": f"Bearer {tok}"}

    with S() as s:
        assert _limits(s, pid)["daily_investigations"] == 5

    assert tc.put(f"/settings/limits?product_id={pid}",
                  json={"daily_investigations": 6}, headers=h).status_code == 200

    with S() as s:
        assert _limits(s, pid)["daily_investigations"] == 6, "the save must stick"


# ── B2/B3: window params must be bounded ───────────────────────────────

def _client(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import echolens.db.session as db_session
    from echolens.db.models import Product

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng, expire_on_commit=False)
    with S() as s:
        s.add(Product(name="Lumo", is_demo=True)); s.commit()
    monkeypatch.setattr(db_session, "_engine", eng)
    monkeypatch.setattr(db_session, "_SessionLocal", S)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: eng)
    monkeypatch.setattr(settings, "echolens_env", "dev")
    from echolens.api.app import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("path", [
    "/graph?days=1000000000",
    "/snapshot?days=1000000000000",
    "/snapshot?days=-100",
    "/portfolio/themes?days=-1&limit=-1",
    "/backlog/plan?capacity_days=-50",
])
def test_out_of_range_windows_are_422_not_500_or_a_wrong_200(monkeypatch, path):
    """Unbounded, a large int overflowed timedelta() and escaped as a 500; a
    negative one produced date_from AFTER date_to and a confident 200."""
    assert _client(monkeypatch).get(path).status_code == 422


def test_valid_windows_still_work(monkeypatch):
    tc = _client(monkeypatch)
    for path in ("/graph?days=90", "/snapshot?days=30", "/portfolio/themes?days=30&limit=8"):
        assert tc.get(path).status_code == 200, path


# ── P9: the daily-count range must be start-EXCLUSIVE ──────────────────

def test_a_row_on_the_boundary_day_does_not_add_a_bucket():
    """The pre-fill starts at start+1 but the filter used `start <= day`, so a
    row landing exactly on the boundary created a 36th bucket and a 29-day
    "trailing 28d baseline" — silently varying with the data."""
    from echolens.detector.detect import _daily_counts
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=35)

    class Row:
        def __init__(self, d): self.d = d

    empty = _daily_counts([], lambda r: r.d, start, end)
    on_boundary = _daily_counts([Row(start.date())], lambda r: r.d, start, end)
    assert len(empty) == len(on_boundary) == 35


# ── P10: an almost-flat baseline is not strong evidence ────────────────

def test_a_near_flat_baseline_does_not_produce_a_false_sev1():
    """27 days at 5 and one at 6 gives stdev 0.19, so a recent mean of 6 — one
    extra review per day — scored z=5.1 (SEV1). The perfectly-flat branch was
    already capped for exactly this reason."""
    from echolens.detector.detect import _zscore, SEV1_Z
    z, _ = _zscore([6] * 7, [5] * 27 + [6])
    assert z < SEV1_Z, f"one extra review/day must not be SEV1 (got z={z})"


def test_a_real_spike_on_a_noisy_baseline_still_scores():
    from echolens.detector.detect import _zscore, SEV1_Z
    z, _ = _zscore([15] * 7, [3, 5, 2, 6, 4, 3, 5] * 4)
    assert z >= SEV1_Z


# ── P11: a paused case must survive a restart ──────────────────────────

def test_a_paused_case_is_not_auto_resumed(db):
    """The cooperative pause sets paused=True but leaves status="running" — that
    is what makes it resumable — so selecting on status alone swept up every
    case a reviewer had deliberately held."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from echolens.db.models import AnomalyEvent, Investigation
    from echolens.investigator.recover import find_interrupted

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    a = AnomalyEvent(slug="a", type="t", metric="m", delta=0, z=0, window="7d",
                     description="d", status="pending")
    s.add(a); s.flush()

    def mk(paused):
        i = Investigation(anomaly_id=a.id, status="running", opened_by="anomaly",
                          budget_tier="quick", budget_json={}, paused=paused)
        s.add(i); s.flush()
        return i.id

    held, interrupted, legacy = mk(True), mk(False), mk(None)
    found = {i.id for i in find_interrupted(s)}
    assert held not in found, "a reviewer's pause outranks a restart"
    assert interrupted in found and legacy in found


# ── P12: one source spelled two ways is still one source ───────────────

def test_case_differing_source_names_are_one_source():
    """Exact string equality counted "github" and "GitHub" as two independent
    sources, satisfying the two-source rule on a single channel."""
    from echolens.investigator.guards import two_source_rule
    ev = [{"id": "ev_001", "source": "github", "snippet": "battery dies"},
          {"id": "ev_002", "source": "GitHub", "snippet": "battery dies"}]
    assert two_source_rule({"evidence_for": ["ev_001", "ev_002"]}, ev) is False


def test_short_identical_snippets_from_two_real_sources_still_count():
    """Deliberately NOT collapsed. Short complaints are supposed to collide:
    "battery dies" on two channels is the most likely way two different people
    describe one fault, and merging them discards the corroboration the rule
    exists to measure."""
    from echolens.investigator.guards import two_source_rule
    ev = [{"id": "ev_001", "source": "github", "snippet": "battery dies"},
          {"id": "ev_002", "source": "play_store", "snippet": "battery dies"}]
    assert two_source_rule({"evidence_for": ["ev_001", "ev_002"]}, ev) is True


# ── P13: a hung collector must not block the rest ──────────────────────

def test_a_hung_collector_times_out_and_the_others_still_run(monkeypatch):
    """COLLECTOR_TIMEOUT_S was declared and documented but never applied — grep
    found exactly one reference, the definition."""
    import time
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from echolens.collectors import registry
    from echolens.collectors.base import Collector

    class Hang(Collector):
        source = "hang"
        def fetch(self, since, limit):
            time.sleep(30)
            return []
        def ingest_item(self, session, item):
            return False, None

    class Fast(Collector):
        source = "fast"
        def fetch(self, since, limit):
            return [{"id": 1}]
        def ingest_item(self, session, item):
            return True, "2026-01-01"

    # monkeypatch, not direct assignment: both of these are module-level state,
    # and leaving the fakes in _BUILDERS made them visible to every later test
    # in the session as if they were real sources.
    monkeypatch.setattr(registry, "COLLECTOR_TIMEOUT_S", 2)
    monkeypatch.setitem(registry._BUILDERS, "hang", lambda i, p: Hang(i, p))
    monkeypatch.setitem(registry._BUILDERS, "fast", lambda i, p: Fast(i, p))

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    registry.add_source(s, "hang", "stuck", "Lumo")
    registry.add_source(s, "fast", "ok", "Lumo")
    s.flush()

    t0 = time.monotonic()
    res = registry.run_all(s, limit=10)
    elapsed = time.monotonic() - t0

    assert elapsed < 20, "the hang must not block for its full 30s"
    by_source = {r.source: r for r in res}
    assert "timed out" in (by_source["hang"].error or "")
    assert by_source["fast"].error is None and by_source["fast"].inserted == 1


# ── P15: one challenge must not steer every future prompt ──────────────

def test_a_single_challenge_does_not_become_agent_guidance(db):
    """weak_spots has no evidence gate — correctly, the Calibration SCREEN
    should show every reason given. But guidance_text injects the top one into
    every future investigator prompt, and n=1 was enough. The same argument this
    module makes against acting on n=8 applies with more force to n=1."""
    from echolens.calibration import MIN_WEAK_SPOT_COUNT, SUFFICIENT_N
    assert MIN_WEAK_SPOT_COUNT > 1
    assert MIN_WEAK_SPOT_COUNT <= SUFFICIENT_N


# ── P16: an unparseable date must not become "now" ─────────────────────

def test_an_undated_review_is_skipped_not_stamped_with_collection_time():
    """reference_now() reads max(Review.created_at) as "today", so stamping a
    bad-dated row with collection time moved the agent's notion of the present
    and every detector window with it."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from echolens.collectors.app_store import AppStoreCollector

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    item = {"content": {"label": "battery dies"}, "im:rating": {"label": "1"},
            "updated": {"label": "not-a-date"}}
    inserted, wm = AppStoreCollector("123", "Lumo").ingest_item(s, item)
    assert inserted is False and wm is None
    assert s.query(Review).count() == 0


# ── P17: a claimed-but-abandoned queue row must be reclaimable ─────────

def test_an_abandoned_queue_row_is_requeued_but_a_live_one_is_not():
    """claim_next flips a row to 'running' and only finish() clears it, so a
    crash between the two left it 'running' forever: excluded from pending() so
    it never ran again, and shown in queue_view's running list indefinitely."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from echolens.db.models import AnomalyEvent, QueuedInvestigation
    from echolens.orchestrator.queue import claim_next

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    now = datetime.now(timezone.utc)
    a = AnomalyEvent(slug="a", type="manual_theme", metric="m", delta=0, z=0,
                     window="7d", description="d", status="pending", product_id=1)
    s.add(a); s.flush()
    for title, age in (("abandoned", timedelta(hours=3)), ("in flight", timedelta(minutes=1))):
        s.add(QueuedInvestigation(product_id=1, anomaly_id=a.id, status="running",
                                  source="manual_theme", priority=60,
                                  selection_order=0 if title == "abandoned" else 1,
                                  budget_tier="quick", title=title,
                                  started_at=now - age))
    s.flush()

    claimed = claim_next(s, 1, daily_limit=10, as_of=now)
    assert claimed is not None and claimed.title == "abandoned"
    live = s.scalars(select(QueuedInvestigation)
                     .where(QueuedInvestigation.title == "in flight")).first()
    assert live.status == "running", "a live worker's claim must not be stolen"
