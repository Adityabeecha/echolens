"""Leftovers: one shared Ask rate limit, release fields on /fixwatch, budget
extensions in the case History, incident-aware automatic triage, and theme
merges that the detector respects. Scripted LLM only — no network, no key."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens.cases import case_history
from echolens.db.models import (
    AnomalyEvent, Base, Finding, FixWatch, Investigation, Product, TriageDecision)
from echolens.eval.harness import ScriptedLLM
from tests.test_pm_case import _insufficient

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _product(s, name="Notely"):
    p = Product(name=name)
    s.add(p)
    s.flush()
    return p


def _signal(s, pid, slug, typ, z, start_days=7, end_days=0):
    a = AnomalyEvent(slug=f"p{pid}-{slug}", type=typ, metric="m", delta=0.5, z=z,
                     window="7d", description=f"{typ} desc", status="pending",
                     product_id=pid, window_start=NOW - timedelta(days=start_days),
                     window_end=NOW - timedelta(days=end_days))
    s.add(a)
    s.flush()
    return a


@pytest.fixture()
def api(monkeypatch):
    """The real app over an in-memory DB, with Ask's work stubbed out."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    import echolens.api.app as app_mod
    monkeypatch.setattr(app_mod, "_chat_respond",
                        lambda body, user, on_step=None: {"answer": "ok", "basis": None})
    app_mod.limiter.reset()
    c = TestClient(app_mod.app)
    c.Session = Session
    yield c
    app_mod.limiter.reset()


# ── 1. one Ask budget across /chat and /chat/stream ─────────────────────

def test_chat_and_chat_stream_share_one_20_per_minute_budget(api):
    codes = []
    for i in range(20):
        route = "/chat" if i % 2 == 0 else "/chat/stream"
        codes.append(api.post(route, json={"message": f"q{i}"}).status_code)
    assert codes == [200] * 20, codes
    # Turn 21 is refused on EITHER route: the budget is shared, not per route.
    assert api.post("/chat", json={"message": "again"}).status_code == 429
    assert api.post("/chat/stream", json={"message": "again"}).status_code == 429


def test_one_route_alone_is_still_capped_at_20(api):
    codes = [api.post("/chat/stream", json={"message": f"q{i}"}).status_code for i in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429


# ── 2. release fields on /fixwatch ──────────────────────────────────────

def test_fixwatch_lists_release_version_and_first_seen(api):
    seen = datetime(2026, 7, 14, 9, 30)
    with api.Session() as s:
        p = _product(s)
        inv = Investigation(status="resolved", product_id=p.id, budget_json={})
        s.add(inv)
        s.flush()
        f = Finding(investigation_id=inv.id, summary="x", confidence=0.8, product_id=p.id,
                    json={})
        s.add(f)
        s.flush()
        s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r", issue_number=7,
                       status="watching", terms=["sync"], metric="sync", product_id=p.id,
                       fixed_in_version="3.2.1", release_seen_at=seen))
        s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r", issue_number=8,
                       status="issue_open", terms=["sync"], metric="sync", product_id=p.id))
        s.commit()
        pid = p.id
    rows = {w["issue_number"]: w for w in api.get(f"/fixwatch?product_id={pid}").json()["watches"]}
    assert rows[7]["fixed_in_version"] == "3.2.1"
    assert datetime.fromisoformat(rows[7]["release_seen_at"]) == seen.replace(tzinfo=timezone.utc)
    assert rows[8]["fixed_in_version"] is None and rows[8]["release_seen_at"] is None


# ── 3. budget extensions in the case History ────────────────────────────

def test_extension_appears_in_history_with_who_and_when(session):
    from echolens.investigator.recover import MAX_HUMAN_EXTENSIONS, grant_extension
    inv = _insufficient(session)
    grant_extension(session, inv, by="rev@team.com")
    events = [e for e in case_history(session, inv) if e["kind"] == "extended"]
    assert len(events) == 1
    e = events[0]
    assert e["text"] == f"Given +5 steps (extension 1 of {MAX_HUMAN_EXTENSIONS})."
    assert e["by"] == "rev@team.com" and e["at"]


def test_extension_record_survives_the_resumed_run(session):
    """The investigator rewrites checkpoint_json every step; the History record
    must not live there."""
    from echolens.investigator.recover import extend_investigation
    inv = _insufficient(session)
    out = extend_investigation(session, inv, llm=ScriptedLLM([
        {"thought": "still nothing", "action": "conclude",
         "conclusion": {"status": "insufficient_evidence", "reason": "x"}},
        {"summary": "s", "prose": "p.", "confidence": 0.3, "supported_hypothesis": None,
         "checked": [], "what_would_settle_it": ""}]))
    texts = [e["text"] for e in case_history(session, out) if e["kind"] == "extended"]
    assert texts == ["Given +5 steps (extension 1 of 2)."]


def test_api_extend_records_the_reviewer(monkeypatch):
    import echolens.api.app as app_mod
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    from echolens.synthetic.generate import generate
    with Session() as s:
        generate(s)
        s.commit()
        inv_id = _insufficient(s).id
        s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    monkeypatch.setattr(app_mod, "_extend_investigation_bg", lambda *a, **k: None)
    app_mod.limiter.reset()
    c = TestClient(app_mod.app)
    assert c.post(f"/investigations/{inv_id}/extend").status_code == 200
    history = c.get(f"/investigations/{inv_id}").json()["history"]
    ext = [e for e in history if e["kind"] == "extended"]
    assert len(ext) == 1 and ext[0]["by"] == "dev@localhost"  # dev mode's principal


# ── 4. automatic triage treats an incident as one unit ──────────────────

def _triage(s, pid, decisions, daily_limit=5, persist=True):
    from echolens.orchestrator.triage import Orchestrator
    orch = Orchestrator(s, llm=ScriptedLLM([{"decisions": decisions}]),
                        daily_limit=daily_limit, product_id=pid)
    return {d.anomaly.slug: d for d in orch.triage(as_of=NOW, persist=persist)}


def test_triage_investigates_only_the_strongest_member_of_an_incident():
    s = _session()
    p = _product(s)
    spike = _signal(s, p.id, "auto-neg-review-spike", "negative_review_spike", 4.0)
    drop = _signal(s, p.id, "auto-rating-drop", "rating_drop", 3.2)
    other = _signal(s, p.id, "auto-theme-battery", "theme_volume_surge", 3.0)
    # The model picks BOTH product-wide signals of one bad release.
    out = _triage(s, p.id, [
        {"anomaly": drop.slug, "decision": "investigate", "reason": "r", "budget_tier": "deep"},
        {"anomaly": spike.slug, "decision": "investigate", "reason": "r",
         "budget_tier": "quick"},
        {"anomaly": other.slug, "decision": "investigate", "reason": "r",
         "budget_tier": "standard"},
    ])
    assert out[spike.slug].decision == "investigate"
    assert out[drop.slug].decision == "merge" and out[drop.slug].merge_into is spike
    assert out[other.slug].decision == "investigate", "an unrelated signal is untouched"
    assert spike.status == "triaged" and drop.status == "merged"
    td = s.scalars(select(TriageDecision).where(TriageDecision.anomaly_id == drop.id)).one()
    assert td.decision == "merge" and td.merge_into_anomaly_id == spike.id
    assert "Related signals in the same window" in spike.description
    # Two cases, not three: the incident spent one slot of the daily cap.
    assert sum(d.decision == "investigate" for d in out.values()) == 2


def test_incident_lead_is_investigated_even_if_the_model_picked_a_weaker_member():
    s = _session()
    p = _product(s)
    spike = _signal(s, p.id, "auto-neg-review-spike", "negative_review_spike", 4.0)
    drop = _signal(s, p.id, "auto-rating-drop", "rating_drop", 3.2)
    out = _triage(s, p.id, [
        {"anomaly": spike.slug, "decision": "ignore", "reason": "noise?"},
        {"anomaly": drop.slug, "decision": "investigate", "reason": "r", "budget_tier": "deep"},
    ])
    assert out[spike.slug].decision == "investigate"
    assert out[spike.slug].budget_tier in ("standard", "deep")   # deepest proposed, then nudged
    assert out[drop.slug].decision == "merge" and out[drop.slug].merge_into is spike


def test_an_incident_nobody_picked_is_left_as_the_model_decided():
    s = _session()
    p = _product(s)
    spike = _signal(s, p.id, "auto-neg-review-spike", "negative_review_spike", 4.0)
    drop = _signal(s, p.id, "auto-rating-drop", "rating_drop", 3.2)
    out = _triage(s, p.id, [
        {"anomaly": spike.slug, "decision": "ignore", "reason": "known outage"},
        {"anomaly": drop.slug, "decision": "ignore", "reason": "known outage"},
    ])
    assert {d.decision for d in out.values()} == {"ignore"}


def test_incident_folding_in_a_preview_does_not_write():
    s = _session()
    p = _product(s)
    spike = _signal(s, p.id, "auto-neg-review-spike", "negative_review_spike", 4.0)
    drop = _signal(s, p.id, "auto-rating-drop", "rating_drop", 3.2)
    out = _triage(s, p.id, [
        {"anomaly": spike.slug, "decision": "investigate", "reason": "r"},
        {"anomaly": drop.slug, "decision": "investigate", "reason": "r"},
    ], persist=False)
    assert out[drop.slug].decision == "merge"
    assert spike.status == drop.status == "pending"
    assert "Related signals" not in spike.description
    assert s.scalars(select(TriageDecision)).first() is None


# ── 5. theme merges reach the detector ──────────────────────────────────

def _scan(monkeypatch, s, pid, surges):
    from echolens.detector import detect
    mk = lambda slug, typ, z: detect.Candidate(slug=slug, type=typ, metric=f"{slug} metric",
                                               delta=1.0, z=z, window="7d",
                                               description=f"{slug} desc", severity="SEV1")
    monkeypatch.setattr(detect, "detect_volume_spike",
                        lambda *a, **k: mk("auto-neg-review-spike", "negative_review_spike", 3.5))
    monkeypatch.setattr(detect, "detect_rating_drop", lambda *a, **k: None)
    monkeypatch.setattr(detect, "detect_theme_surges",
                        lambda *a, **k: [mk(sl, "theme_volume_surge", z) for sl, z in surges])
    monkeypatch.setattr(detect, "detect_issue_velocity", lambda *a, **k: [])
    return {e.slug: e for e in detect.scan(s, as_of=NOW, product="Notely", product_id=pid)}


def test_a_merged_themes_surge_counts_toward_its_target(monkeypatch):
    from echolens.themes.overrides import set_override
    s = _session()
    p = _product(s)
    set_override(s, p.id, "theme-p1-dropbox-upload", "merge", into="theme-p1-sync-fails")
    events = _scan(monkeypatch, s, p.id, [("auto-theme-dropbox", 4.2),
                                          ("auto-theme-sync-fails", 3.1),
                                          ("auto-theme-battery", 3.3)])
    assert sorted(events) == [f"p{p.id}-auto-neg-review-spike", f"p{p.id}-auto-theme-battery",
                              f"p{p.id}-auto-theme-sync-fails"]
    target = events[f"p{p.id}-auto-theme-sync-fails"]
    assert target.z == 4.2, "the stronger surge, now counted as the target's"
    assert target.metric == "auto-theme-sync-fails metric", "still the target's own signal"
    assert "merged theme terms: dropbox" in target.description


def test_a_merged_theme_surging_alone_raises_the_targets_signal_not_its_own(monkeypatch):
    from echolens.themes.overrides import set_override
    s = _session()
    p = _product(s)
    set_override(s, p.id, "theme-p1-dropbox-upload", "merge", into="theme-p1-sync-fails")
    events = _scan(monkeypatch, s, p.id, [("auto-theme-dropbox", 4.2)])
    assert f"p{p.id}-auto-theme-dropbox" not in events
    assert events[f"p{p.id}-auto-theme-sync-fails"].z == 4.2
    # A second scan upserts that one row rather than adding another.
    _scan(monkeypatch, s, p.id, [("auto-theme-dropbox", 4.0), ("auto-theme-sync-fails", 3.0)])
    rows = s.scalars(select(AnomalyEvent).where(
        AnomalyEvent.type == "theme_volume_surge")).all()
    assert [r.slug for r in rows] == [f"p{p.id}-auto-theme-sync-fails"]


def test_merge_into_a_muted_theme_stays_silent_and_mute_is_unchanged(monkeypatch):
    from echolens.themes.overrides import set_override
    s = _session()
    p = _product(s)
    set_override(s, p.id, "theme-p1-dropbox-upload", "merge", into="theme-p1-sync-fails")
    set_override(s, p.id, "theme-p1-sync-fails", "mute")
    events = _scan(monkeypatch, s, p.id, [("auto-theme-dropbox", 4.2),
                                          ("auto-theme-sync-fails", 3.1),
                                          ("auto-theme-battery", 3.3)])
    # Muting still never silences the product-wide spike.
    assert sorted(events) == [f"p{p.id}-auto-neg-review-spike", f"p{p.id}-auto-theme-battery"]


def test_terms_shared_with_the_target_are_not_rekeyed():
    from echolens.detector.detect import Candidate, fold_merged_themes
    c = Candidate(slug="auto-theme-sync", type="theme_volume_surge", metric="m", delta=1.0,
                  z=3.0, window="7d", description="d")
    issue = Candidate(slug="auto-issues-dropbox", type="issue_velocity_surge", metric="m",
                      delta=1.0, z=3.0, window="7d", description="d")
    merges = [({"sync", "dropbox"}, "sync-fails")]
    out = fold_merged_themes([c, issue], merges)
    assert [x.slug for x in out] == ["auto-theme-sync", "auto-issues-dropbox"]
