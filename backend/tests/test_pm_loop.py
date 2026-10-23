"""Closing the loop: version-aware fix verification, reply drafts for affected
reviewers (draft only), and follow-up questions when evidence is thin."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens import fixwatch
from echolens.db import session as db_session
from echolens.db.models import (
    AnomalyEvent, Base, CollectorState, Finding, FixWatch, HypothesisRow, Investigation,
    Product, Review)
from echolens.replies import (
    REPLY_MAX_CHARS, draft_reply, followup_questions, looks_non_english, reply_drafts)

TZ = timezone.utc
CLOSE = datetime(2026, 6, 1, tzinfo=TZ)


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    s.add(CollectorState(source="play_store", identifier="com.test", product=None,
                         status="healthy", enabled=True, last_run_at=datetime(2030, 1, 1, tzinfo=TZ)))
    s.flush()
    return s


def _finding(s, summary="battery drain from background sync", inv_status="resolved",
             fjson=None):
    a = AnomalyEvent(slug=f"a-{id(s) % 999}-{summary[:6]}", type="volume_spike", metric=summary,
                     delta=1.0, z=3.0, window="7d", description=summary, status="closed")
    s.add(a)
    s.flush()
    inv = Investigation(anomaly_id=a.id, status=inv_status, budget_tier="quick", budget_json={},
                        created_at=CLOSE - timedelta(days=3))
    s.add(inv)
    s.flush()
    f = Finding(investigation_id=inv.id, summary=summary, confidence=0.85, status="approved",
                json={"summary": summary, **(fjson or {})})
    s.add(f)
    s.flush()
    return inv, f


def _rev(s, key, when, text="battery drain is terrible", version=None, rating=1):
    s.add(Review(source="play_store", ext_id=key, rating=rating, text=text, version=version,
                 created_at=when))


def _watch_closed(s, f, version=None, payload=""):
    fixwatch.link_issue(s, f, "acme/app", 7)
    if version:
        w = s.scalars(select(FixWatch)).first()
        fixwatch.set_fixed_version(s, w, version)
    return fixwatch.on_issue_closed(s, "acme/app", 7, CLOSE, payload_text=payload)


# ── item 15: version-aware verification ──────────────────────────────

def test_parse_fixed_version_from_closing_text():
    assert fixwatch.parse_fixed_version("Closing: fixed in v3.2.1") == "3.2.1"
    assert fixwatch.parse_fixed_version("Released in 4.0, thanks") == "4.0"
    assert fixwatch.parse_fixed_version("fixed in version 2.9.0") == "2.9.0"
    assert fixwatch.parse_fixed_version("fixed the typo", "no version here") is None


def test_close_without_version_keeps_todays_behaviour():
    s = _session()
    _, f = _finding(s)
    w = _watch_closed(s, f)
    assert w.status == "watching" and w.fix_date is not None
    assert w.fixed_in_version is None


def test_close_with_version_waits_until_the_version_reaches_users():
    s = _session()
    _, f = _finding(s)
    for d in range(-14, 0):                       # old-version complaints
        _rev(s, f"o{d}", CLOSE + timedelta(days=d), version="3.1.0")
    _rev(s, "nobody-on-new", CLOSE + timedelta(days=1), "love it", version="3.1.0", rating=5)
    w = _watch_closed(s, f, payload="fixed in v3.2.1")
    assert w.status == "waiting_for_release" and w.fixed_in_version == "3.2.1"

    out = fixwatch.evaluate(s, as_of=CLOSE + timedelta(days=30))
    assert out[0]["status"] == "waiting_for_release"
    assert w.status == "waiting_for_release"       # 30 days passed, but the fix never shipped


def test_window_opens_at_first_review_on_fixed_version_and_enough_reviews():
    s = _session()
    _, f = _finding(s)
    for d in range(-14, 0):
        _rev(s, f"o{d}", CLOSE + timedelta(days=d), version="3.1.0")
    w = _watch_closed(s, f, version="3.2.1")
    assert w.status == "waiting_for_release"
    release = CLOSE + timedelta(days=4)
    for i in range(3):                             # a few early adopters: not enough yet
        _rev(s, f"n{i}", release + timedelta(hours=i), "all good", version="3.2.1", rating=5)
    s.flush()
    fixwatch.evaluate(s, as_of=release + timedelta(days=2))
    assert w.status == "waiting_for_release"

    for i in range(3, 10):                         # 10 reviews on the version -> live
        _rev(s, f"n{i}", release + timedelta(hours=i), "all good", version="3.2.1", rating=5)
    s.flush()
    fixwatch.evaluate(s, as_of=release + timedelta(days=2))
    assert w.status == "watching"
    assert fixwatch.aware_utc(w.fix_date) == release     # not the issue-close date
    assert fixwatch.aware_utc(w.release_seen_at) == release
    assert w.baseline_rate and w.baseline_rate > 0


def test_window_opens_after_seven_days_even_with_few_reviews_and_newer_version_counts():
    s = _session()
    _, f = _finding(s)
    w = _watch_closed(s, f, version="3.2.1")
    _rev(s, "n0", CLOSE + timedelta(days=2), "fine", version="3.3.0", rating=5)   # >= 3.2.1
    s.flush()
    assert fixwatch.release_state(s, w, CLOSE + timedelta(days=5))["state"] == "rolling_out"
    fixwatch.evaluate(s, as_of=CLOSE + timedelta(days=9))
    assert w.status == "watching"


def test_fix_not_judged_persists_before_the_version_is_live():
    """The motivating bug: complaints continue on OLD versions after issue close."""
    s = _session()
    _, f = _finding(s)
    for d in range(-14, 21):
        _rev(s, f"c{d}", CLOSE + timedelta(days=d), version="3.1.0")
        _rev(s, f"d{d}", CLOSE + timedelta(days=d), version="3.1.0")
    w = _watch_closed(s, f, version="3.2.1")
    fixwatch.evaluate(s, as_of=CLOSE + timedelta(days=20))
    assert w.status == "waiting_for_release"
    assert not s.scalars(select(AnomalyEvent).where(AnomalyEvent.type == "fix_regression")).all()


def test_set_version_on_a_watching_fix_restarts_the_window_and_clear_restores_it():
    s = _session()
    _, f = _finding(s)
    w = _watch_closed(s, f)
    assert w.status == "watching"
    fixwatch.set_fixed_version(s, w, "v3.2.1")
    assert w.status == "waiting_for_release" and w.fixed_in_version == "3.2.1"
    fixwatch.set_fixed_version(s, w, "")
    assert w.status == "watching" and w.fixed_in_version is None
    with pytest.raises(ValueError):
        fixwatch.set_fixed_version(s, w, "soon")


def test_before_after_chart_records_the_release_window_start():
    s = _session()
    _, f = _finding(s)
    for d in range(-14, 0):
        _rev(s, f"o{d}", CLOSE + timedelta(days=d), version="3.1.0")
    w = _watch_closed(s, f, version="3.2.1")
    for i in range(10):
        _rev(s, f"n{i}", CLOSE + timedelta(days=3, hours=i), "ok", version="3.2.1", rating=5)
    s.flush()
    fixwatch.evaluate(s, as_of=CLOSE + timedelta(days=4))
    chart = fixwatch.before_after(s, w)
    assert chart["fixed_in_version"] == "3.2.1"
    assert chart["window_start"] == "first_review_on_fixed_version"
    assert chart["fix_date"] == (CLOSE + timedelta(days=3)).date().isoformat()


# ── item 16: reply drafts ────────────────────────────────────────────

def test_draft_text_is_short_polite_and_non_promissory():
    d = draft_reply("battery drain", "3.2.1", True)
    assert "v3.2.1" in d and "reply here" in d
    assert len(d) <= REPLY_MAX_CHARS
    pending = draft_reply("battery drain", None, False)
    assert "fixes" not in pending and "fixed" not in pending     # nothing claimed we haven't verified
    assert len(draft_reply("x " * 400, "1.0", True)) <= REPLY_MAX_CHARS


def test_non_english_detection():
    assert looks_non_english("La batería se agota muy rápido desde la actualización")
    assert looks_non_english("バッテリーの消耗が激しい")
    assert not looks_non_english("battery drain is terrible since the update")
    assert not looks_non_english("battery drain")


def test_reply_drafts_target_matching_negative_reviews_in_the_window():
    s = _session()
    _, f = _finding(s)
    for d in range(-5, 0):
        _rev(s, f"hit{d}", CLOSE + timedelta(days=d), "battery drain is terrible", version="3.1.0")
    _rev(s, "other", CLOSE - timedelta(days=2), "the app crashes on launch", version="3.1.0")
    _rev(s, "happy", CLOSE - timedelta(days=2), "battery drain fixed, love it", rating=5)
    _rev(s, "old", CLOSE - timedelta(days=200), "battery drain is terrible")
    _rev(s, "es", CLOSE - timedelta(days=1), "La batería se agota, battery drain horrible siempre", version="3.1.0")
    _rev(s, "onfix", CLOSE + timedelta(days=1), "battery drain still", version="3.2.1")
    w = _watch_closed(s, f, version="3.2.1")
    w.status = "confirmed"
    s.flush()

    out = reply_drafts(s, f)
    ids = {d["ext_id"] for d in out["drafts"]}
    assert {f"hit{d}" for d in range(-5, 0)} <= ids
    assert not ids & {"other", "happy", "old"}
    assert "onfix" not in ids and out["skipped_on_fixed_version"] == 1
    assert out["draft_only"] is True and out["mode"] == "fixed"
    plain = [d for d in out["drafts"] if d["ext_id"] == "hit-1"][0]
    assert "v3.2.1" in plain["draft"] and plain["language"] == "en"
    assert "English" in out["translation_note"]


def test_non_english_reviews_are_flagged_not_translated():
    s = _session()
    _, f = _finding(s)
    _rev(s, "es", CLOSE - timedelta(days=1), "La batería se agota muy rápido, battery drain horrible")
    _watch_closed(s, f)
    out = reply_drafts(s, f)
    row = out["drafts"][0]
    assert row["language"] == "non_english" and row["draft"] is None and row["note"]


def test_llm_reword_is_optional_injectable_and_guarded():
    class Parsed:
        def __init__(self, reply): self.parsed = {"reply": reply}

    class LLM:
        def __init__(self, reply): self.reply, self.calls = reply, 0
        def complete_json(self, system, user, schema, agent):
            self.calls += 1
            return Parsed(self.reply)

    s = _session()
    _, f = _finding(s)
    _rev(s, "a", CLOSE - timedelta(days=1), "battery drain is terrible")
    _watch_closed(s, f)
    default = reply_drafts(s, f)["drafts"][0]["draft"]

    good = LLM("Sorry about the battery drain, and thanks for telling us.")
    assert reply_drafts(s, f, llm=good)["drafts"][0]["draft"].startswith("Sorry about")
    assert good.calls == 1
    # A reply that promises, or is too long, falls back to the template.
    assert reply_drafts(s, f, llm=LLM("We guarantee this is fixed."))["drafts"][0]["draft"] == default
    assert reply_drafts(s, f, llm=LLM("x" * 500))["drafts"][0]["draft"] == default


def test_reply_module_has_no_posting_capability():
    import echolens.replies as m
    src = open(m.__file__, encoding="utf-8").read()
    assert "requests" not in src and "httpx" not in src and "urllib" not in src


# ── item 17: follow-up questions ─────────────────────────────────────

def test_followups_use_settle_it_and_open_hypotheses():
    s = _session()
    inv, f = _finding(s, inv_status="insufficient_evidence", fjson={
        "what_would_settle_it": "device model breakdown and sync logs"})
    s.add(HypothesisRow(investigation_id=inv.id, hid="H1", confidence=0.4, status="active",
                        statement="Background sync wakes the radio and drains the battery",
                        json={"next_test": "compare with sync disabled"}))
    s.add(HypothesisRow(investigation_id=inv.id, hid="H2", confidence=0.2, status="rejected",
                        statement="A pricing experiment caused it", json={}))
    s.flush()
    out = followup_questions(s, f, inv)
    qs = [q["question"] for q in out["questions"]]
    assert 1 <= len(qs) <= 3
    assert any("device" in q.lower() for q in qs)
    assert any("background sync" in q.lower() for q in qs)
    assert not any("price" in q.lower() for q in qs)       # rejected hypothesis is not asked about
    assert followup_questions(s, f, inv) == out             # deterministic


def test_followups_fall_back_to_generic_questions():
    s = _session()
    inv, f = _finding(s, inv_status="needs_human")
    out = followup_questions(s, f, inv)
    assert len(out["questions"]) == 3
    assert all(q["source"] == "default" for q in out["questions"])


# ── API ──────────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session_)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from fastapi.testclient import TestClient
    from echolens.api.app import app
    return TestClient(app), Session_


def _api_seed(Session_, status="resolved", package="com.acme.app"):
    with Session_() as s:
        p = Product(name="Acme", package_name=package)
        s.add(p)
        s.flush()
        a = AnomalyEvent(slug="api-a", type="volume_spike", metric="battery drain", delta=1.0,
                         z=3.0, window="7d", description="battery drain", status="closed",
                         product_id=p.id)
        s.add(a)
        s.flush()
        inv = Investigation(anomaly_id=a.id, status=status, budget_tier="quick", product_id=p.id,
                            created_at=CLOSE - timedelta(days=3))
        s.add(inv)
        s.flush()
        f = Finding(investigation_id=inv.id, product_id=p.id, summary="battery drain from sync",
                    confidence=0.85, status="approved",
                    json={"summary": "battery drain from sync",
                          "what_would_settle_it": "sync logs and device model"})
        s.add(f)
        s.flush()
        s.add(CollectorState(source="play_store", identifier=package, product="Acme",
                             status="healthy", enabled=True, product_id=p.id,
                             last_run_at=datetime(2030, 1, 1, tzinfo=TZ)))
        for i in range(3):
            s.add(Review(source="play_store", ext_id=f"x{i}", rating=1, product="Acme",
                         text="battery drain is terrible", version="3.1.0",
                         created_at=CLOSE - timedelta(days=i + 1)))
        s.commit()
        return p.id, f.id, inv.id


def test_api_fixed_version_endpoint_and_waiting_status(client):
    c, Session_ = client
    pid, fid, _ = _api_seed(Session_)
    with Session_() as s:
        f = s.get(Finding, fid)
        fixwatch.link_issue(s, f, "acme/app", 9)
        s.commit()
    assert c.put(f"/findings/{fid}/fixed-version?product_id={pid}",
                 json={"version": "oops"}).status_code == 422
    r = c.put(f"/findings/{fid}/fixed-version?product_id={pid}", json={"version": "3.2.1"})
    assert r.status_code == 200 and r.json()["fixed_in_version"] == "3.2.1"

    with Session_() as s:
        fixwatch.on_issue_closed(s, "acme/app", 9, CLOSE)
        s.commit()
    fix = c.get(f"/investigations/{_inv_of(Session_, fid)}?product_id={pid}").json()["finding"]["fix"]
    assert fix["status"] == "waiting_for_release"
    assert fix["fixed_in_version"] == "3.2.1" and fix["release"]["state"] == "not_seen"
    assert not fix.get("version_hint")


def _inv_of(Session_, fid):
    with Session_() as s:
        return s.get(Finding, fid).investigation_id


def test_api_fixed_version_requires_a_linked_issue(client):
    c, Session_ = client
    pid, fid, _ = _api_seed(Session_)
    assert c.put(f"/findings/{fid}/fixed-version?product_id={pid}",
                 json={"version": "3.2.1"}).status_code == 409


def test_api_version_hint_without_a_version(client):
    c, Session_ = client
    pid, fid, inv_id = _api_seed(Session_)
    with Session_() as s:
        w = fixwatch.link_issue(s, s.get(Finding, fid), "acme/app", 9)
        w.status = "watching"
        s.commit()
    fix = c.get(f"/investigations/{inv_id}?product_id={pid}").json()["finding"]["fix"]
    assert fix["version_hint"] is True


def test_api_reply_drafts_and_console_link(client):
    c, Session_ = client
    pid, fid, _ = _api_seed(Session_)
    r = c.get(f"/findings/{fid}/reply-drafts?product_id={pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3 and body["draft_only"] is True
    assert body["console_name"] == "Play Console"
    assert body["console_url"].startswith("https://play.google.com/console")
    assert body["listing_url"].endswith("id=com.acme.app")


def test_api_reply_drafts_app_store_link_and_unresolved_refusal(client):
    c, Session_ = client
    pid, fid, _ = _api_seed(Session_, package="1234567890")
    body = c.get(f"/findings/{fid}/reply-drafts?product_id={pid}").json()
    assert body["console_url"] == "https://appstoreconnect.apple.com/apps/1234567890/distribution/reviews"

    c2, S2 = client
    with S2() as s:
        inv = s.scalars(select(Investigation)).first()
        inv.status = "insufficient_evidence"
        s.commit()
    assert c2.get(f"/findings/{fid}/reply-drafts?product_id={pid}").status_code == 409
    q = c2.get(f"/findings/{fid}/followup-questions?product_id={pid}").json()
    assert 1 <= len(q["questions"]) <= 3


def test_api_followups_empty_for_resolved_case(client):
    c, Session_ = client
    pid, fid, _ = _api_seed(Session_)
    assert c.get(f"/findings/{fid}/followup-questions?product_id={pid}").json()["questions"] == []
