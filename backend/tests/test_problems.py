"""The Problems screen: the performance category, spike strength and grouping,
plain-word dismissal reasons, and the batch merge / dismiss endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db.models import (
    AnomalyEvent, Base, Finding, FixWatch, Investigation, Product, QueuedInvestigation,
    TriageDecision)
from echolens.intent import (
    BUG, FEATURE_REQUEST, INTENTS, PERFORMANCE, UX_CONFUSION, classify, classify_detail,
    count_intents, is_performance, spike_category)
from echolens.problems import annotate_spikes, dismissal_reason, strength

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


# ── the performance category ────────────────────────────────────────────

@pytest.mark.parametrize("text,rating", [
    ("The app is so slow since the update", 2),
    ("Laggy scrolling in the gallery", 3),
    ("Drains my battery overnight", 1),
    ("Phone gets really hot when syncing", 2),
    ("Uses way too much memory", 2),
    ("Freezes for ten seconds when I open it", 2),
])
def test_slow_or_draining_reviews_are_performance(text, rating):
    assert is_performance(text)
    assert classify_detail(text, rating) == PERFORMANCE


@pytest.mark.parametrize("text,rating,expected", [
    ("It crashes and it's slow", 1, BUG),                 # something broke: still a bug
    ("App crashes every time I open a note", 1, BUG),
    ("Please add a battery saver mode", 5, FEATURE_REQUEST),
    ("Can't find where the export is", 3, UX_CONFUSION),
    ("Love it, fast and smooth", 5, "praise"),
])
def test_everything_else_keeps_its_intent(text, rating, expected):
    assert classify_detail(text, rating) == expected


def test_classify_and_counts_are_unchanged_by_the_new_category():
    # The guards and the detector read `classify`: a slow app is still a bug
    # complaint there, and every count keeps its five keys.
    assert classify("The app is so slow since the update", 2) == BUG
    assert PERFORMANCE not in INTENTS
    assert set(count_intents([("so slow", 1)])) == set(INTENTS)


def test_spike_category_groups_by_lead_intent_then_wording():
    reqs = {BUG: 1, FEATURE_REQUEST: 4, UX_CONFUSION: 0, "praise": 0, "other": 0}
    confused = {BUG: 1, FEATURE_REQUEST: 0, UX_CONFUSION: 3, "praise": 0, "other": 0}
    bugs = {BUG: 5, FEATURE_REQUEST: 0, UX_CONFUSION: 0, "praise": 0, "other": 0}
    assert spike_category(["Dark mode"], reqs) == FEATURE_REQUEST
    assert spike_category(["Export"], confused) == UX_CONFUSION
    assert spike_category(["Battery drain since 3.2"], bugs) == PERFORMANCE
    assert spike_category(["Sync crashes after upload"], bugs) == BUG
    # A GitHub burst has no reviews behind it: a bug report by default.
    assert spike_category(["Issue burst on GitHub"], None) == BUG
    # Mostly about speed: the quotes count too.
    assert spike_category(["Gallery", "so laggy", "slow to open", "crashes"], bugs) == PERFORMANCE


def test_strength_uses_the_detector_bands():
    assert strength(3.4) == "strong"
    assert strength(2.0) == "medium"
    assert strength(0.6) == "weak"
    assert strength(None) == "weak"


# ── dismissal reasons in plain words ────────────────────────────────────

def test_every_dismissal_says_why():
    base = {"dismissed": True, "z": 2.5, "type": "negative_review_spike", "category": BUG}
    assert dismissal_reason({**base, "muted": True}, {}, {}) == "You muted this topic"
    merged = {**base, "dismissed_decision": "merge", "merge_into_anomaly_id": 7}
    assert dismissal_reason(merged, {7: 12}, {}) == "Merged into problem #12"
    assert dismissal_reason(merged, {}, {7: "Battery drain"}) == "Merged into “Battery drain”"
    assert dismissal_reason({**base, "dismissed_reason": "Dismissed by ana@x.co: duplicate"}, {}, {}) \
        == "Dismissed by ana@x.co: duplicate"
    assert dismissal_reason({**base, "category": FEATURE_REQUEST}, {}, {}) == "A feature request"
    assert dismissal_reason({**base, "z": 0.6}, {}, {}) == "Too weak to matter (strength 0.6)"
    assert dismissal_reason({**base, "dismissed_reason": "Duplicate of a fixed bug"}, {}, {}) \
        == "Ruled out when triaged: duplicate of a fixed bug."


def test_a_generic_headline_is_categorised_by_its_metric():
    rows = annotate_spikes(None, [{"id": 1, "slug": "s", "title": "1-star reviews are spiking",
                                   "metric": "battery share of negative reviews", "z": 2.2}], [])
    assert rows[0]["category"] == PERFORMANCE and rows[0]["strength"] == "medium"


def test_muted_spikes_come_back_dismissed_with_their_reason():
    rows = annotate_spikes(None, [], [], muted=[{"id": 1, "slug": "s", "title": "Sync slow", "z": 3.0}])
    assert rows[0]["dismissed"] and rows[0]["dismissed_why"] == "You muted this topic"
    assert rows[0]["category"] == PERFORMANCE and rows[0]["strength"] == "strong"


# ── API ─────────────────────────────────────────────────────────────────

def _signal(s, pid, slug, typ, z, title=None):
    a = AnomalyEvent(slug=f"p{pid}-{slug}", type=typ, metric="m", delta=0.5, z=z, window="7d",
                     description=title or f"{typ} desc", status="pending", product_id=pid,
                     window_start=NOW - timedelta(days=7 + int(z * 10)),
                     window_end=NOW - timedelta(days=int(z * 10)))
    s.add(a)
    s.flush()
    return a


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        p, other = Product(name="Notely"), Product(name="Other")
        s.add_all([p, other])
        s.flush()
        _signal(s, p.id, "a", "negative_review_spike", 3.5)
        _signal(s, p.id, "b", "rating_drop", 2.2)
        _signal(s, p.id, "c", "issue_velocity_surge", 1.2)
        _signal(s, other.id, "x", "negative_review_spike", 3.0)
        # A request case, with a confirmed fix being watched.
        req = _signal(s, p.id, "request-dark-mode", "manual_theme", 0.0)
        req.slug = "request-p1-dark-mode"
        inv = Investigation(status="resolved", product_id=p.id, anomaly_id=req.id, budget_json={})
        s.add(inv)
        s.flush()
        f = Finding(investigation_id=inv.id, summary="Dark mode", confidence=0.7,
                    json={"support_level": "single_channel"}, product_id=p.id)
        s.add(f)
        s.flush()
        s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="o/r", issue_number=3,
                       status="watching", product_id=p.id))
        s.commit()
        pid, oid = p.id, other.id

    import echolens.api.app as app_module
    import echolens.db.session as dbs
    monkeypatch.setattr(dbs, "_engine", engine, raising=False)
    monkeypatch.setattr(dbs, "_SessionLocal", Session, raising=False)
    monkeypatch.setattr(app_module, "_daily_limit", lambda session, product_id=None: 0)
    monkeypatch.setattr(app_module, "_drain_queue_bg", lambda *a: None)
    c = TestClient(app_module.app)
    c.pid, c.oid, c.Session, c.app = pid, oid, Session, app_module.app
    return c


def _view(client):
    return client.get(f"/cases?product_id={client.pid}").json()


def test_cases_rows_carry_what_the_stamp_needs(client):
    row = next(r for r in _view(client)["cases"] if r["id"] is not None)
    assert row["intent"] == FEATURE_REQUEST
    assert row["support_level"] == "single_channel" and row["fix_status"] == "watching"
    assert row["needs_review"] is False


def test_signals_carry_category_and_strength(client):
    signals = {s["slug"]: s for s in _view(client)["signals"]}
    a = signals[f"p{client.pid}-a"]
    assert a["strength"] == "strong" and a["category"] in (BUG, PERFORMANCE)
    assert signals[f"p{client.pid}-c"]["strength"] == "weak"


def test_merge_folds_spikes_into_one_queued_problem(client):
    pid = client.pid
    r = client.post("/spikes/merge", json={"slugs": [f"p{pid}-b", f"p{pid}-a"], "product_id": pid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lead"] == f"p{pid}-a" and body["merged"] == [f"p{pid}-b"]
    assert body["deferred"] is True and "tomorrow" in body["summary"]   # daily limit 0
    with client.Session() as s:
        assert s.scalars(select(QueuedInvestigation).where(
            QueuedInvestigation.status == "queued")).all()
        lead = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == f"p{pid}-a")).one()
        assert "investigated together" in lead.description
    merged = {s["slug"]: s for s in _view(client)["signals"]}[f"p{pid}-b"]
    assert merged["dismissed"] and merged["dismissed_why"].startswith("Merged into “")

    # Once the lead is a problem, the merged spike points at it by number.
    with client.Session() as s:
        lead = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == f"p{pid}-a")).one()
        inv = Investigation(status="running", product_id=pid, anomaly_id=lead.id, budget_json={})
        s.add(inv)
        s.commit()
        inv_id = inv.id
    merged = {s["slug"]: s for s in _view(client)["signals"]}[f"p{pid}-b"]
    assert merged["dismissed_why"] == f"Merged into problem #{inv_id}"


def test_merge_needs_two_open_spikes_of_this_product(client):
    pid = client.pid
    r = client.post("/spikes/merge", json={"slugs": [f"p{pid}-a", f"p{client.oid}-x"], "product_id": pid})
    assert r.status_code == 422 and "at least two" in r.json()["detail"]


def test_dismiss_records_who_and_why_and_stays_in_scope(client):
    pid = client.pid
    assert client.post("/spikes/dismiss", json={"slugs": [f"p{pid}-c"], "reason": "  ",
                                                "product_id": pid}).status_code == 422
    r = client.post("/spikes/dismiss", json={"slugs": [f"p{pid}-c", f"p{client.oid}-x"],
                                             "reason": "Known GitHub noise", "product_id": pid})
    assert r.status_code == 200, r.text
    assert r.json()["dismissed"] == [f"p{pid}-c"] and r.json()["skipped"] == [f"p{client.oid}-x"]
    row = {s["slug"]: s for s in _view(client)["signals"]}[f"p{pid}-c"]
    assert row["dismissed_why"] == "Dismissed by dev@localhost: Known GitHub noise"
    with client.Session() as s:
        other = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == f"p{client.oid}-x")).one()
        assert other.status == "pending"
        assert not s.scalars(select(TriageDecision).where(TriageDecision.anomaly_id == other.id)).all()


def test_batch_actions_need_a_reviewer(client):
    from echolens.auth import current_user
    client.app.dependency_overrides[current_user] = lambda: {"id": 9, "email": "v@x", "role": "viewer"}
    try:
        pid = client.pid
        assert client.post("/spikes/dismiss", json={"slugs": [f"p{pid}-a"], "reason": "no",
                                                    "product_id": pid}).status_code == 403
        assert client.post("/spikes/merge", json={"slugs": [f"p{pid}-a", f"p{pid}-b"],
                                                  "product_id": pid}).status_code == 403
    finally:
        client.app.dependency_overrides.clear()


def test_saved_views_keep_the_sort(client):
    with client.Session() as s:
        from echolens import auth
        auth.create_user(s, "rev@x.co", "correct-horse-battery", "reviewer")
        s.commit()
    from echolens.auth import current_user
    with client.Session() as s:
        from echolens.db.models import User
        uid = s.scalars(select(User)).first().id
    client.app.dependency_overrides[current_user] = lambda: {"id": uid, "email": "rev@x.co", "role": "reviewer"}
    try:
        r = client.post(f"/views?product_id={client.pid}",
                        json={"name": "Newest hunches", "params": {"tab": "hunches", "sort": "newest"}})
        assert r.status_code in (200, 201), r.text
        assert r.json()["params"]["sort"] == "newest"
    finally:
        client.app.dependency_overrides.clear()
