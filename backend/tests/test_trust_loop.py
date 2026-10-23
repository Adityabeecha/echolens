"""Trust badge on every finding, and the "Fix confirmed" card on Today."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db import session as db_session
from echolens.db.models import (
    AnomalyEvent, Base, EvidenceRow, Finding, FixWatch, HypothesisRow, Investigation,
    Product, Review)
from echolens.evidence_summary import (
    confidence_band, dismiss_fix, finding_trust, recent_confirmed_fixes, trust_for_cases)

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)

EVIDENCE = [
    ("ev_001", "play_store", "Battery drains overnight since the 3.2 update, phone is dead by morning"),
    ("ev_002", "play_store", "Sync keeps the phone awake and the battery is gone in hours"),
    ("ev_003", "release_notes", "3.2.0: new background sync scheduler for faster note syncing"),
]


def _case(s, name="Lumo", *, sources=EVIDENCE, cited=("ev_001", "ev_003"), status="draft",
          confidence=0.86, watch_status=None, confirmed_days_ago=3, needs_review=False):
    p = s.query(Product).filter_by(name=name).first()
    if p is None:
        p = Product(name=name)
        s.add(p)
        s.flush()
    a = AnomalyEvent(slug=f"a-{name}-{s.query(AnomalyEvent).count()}", type="volume_spike",
                     metric="battery drain", delta=1.0, z=3.0, window="7d", description="d",
                     status="investigating", product_id=p.id)
    s.add(a)
    s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", product_id=p.id)
    s.add(inv)
    s.flush()
    for eid, src, text in sources:
        s.add(EvidenceRow(investigation_id=inv.id, eid=eid, source=src, ref=f"{src}:{eid}",
                          snippet=text, retrieved_by="t", json={"supports": ["H1"]}))
    s.add(HypothesisRow(investigation_id=inv.id, hid="H1", statement="3.2 sync holds a wakelock",
                        confidence=confidence, status="supported",
                        json={"evidence_for": list(cited)}))
    fj = {"summary": "Battery drains overnight", "supported_hypothesis": "H1",
          "confidence": confidence}
    if needs_review:
        fj["needs_review"] = {"reason": "struck"}
    f = Finding(investigation_id=inv.id, product_id=p.id, confidence=confidence,
                status=status, summary="Battery drains overnight", json=fj)
    s.add(f)
    s.flush()
    w = None
    if watch_status:
        w = FixWatch(finding_id=f.id, investigation_id=inv.id, repo="acme/lumo", issue_number=1,
                     status=watch_status, terms=["battery", "drain"], metric="battery drain",
                     window_days=14, fix_date=NOW - timedelta(days=20),
                     baseline_rate=0.21, post_rate=0.08, fixed_in_version="3.2.1",
                     confirmed_at=(NOW - timedelta(days=confirmed_days_ago)
                                   if watch_status == "confirmed" else None),
                     chart_json={"days": []}, product_id=p.id)
        s.add(w)
        s.flush()
    return p, inv, f, w


@pytest.fixture()
def Session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def s(Session):
    sess = Session()
    yield sess
    sess.close()


# ── item 1: trust ───────────────────────────────────────────────────────

def test_multi_source_trust_counts_and_passes_two_source_rule(s):
    _, inv, f, _ = _case(s)
    t = finding_trust(s, f)
    assert t["sources"] == [{"source": "play_store", "count": 2},
                            {"source": "release_notes", "count": 1}]
    assert t["distinct_sources"] == 2 and t["two_source_ok"] and t["confidence"] == "high"
    assert t["label"] == "High confidence · 2 Play Store reviews + 1 release note · 2 sources"
    assert trust_for_cases(s, [inv.id])[inv.id] == t


def test_single_source_needs_corroboration(s):
    one = [e for e in EVIDENCE if e[1] == "play_store"]
    _, _, f, _ = _case(s, sources=one, cited=("ev_001", "ev_002"), confidence=0.7)
    t = finding_trust(s, f)
    assert t["distinct_sources"] == 1 and not t["two_source_ok"]
    assert t["confidence"] == "medium"
    assert t["label"] == "Single source — needs corroboration"


def test_two_sources_present_but_not_behind_the_cause(s):
    # Both channels are in the record, but the hypothesis cites only one.
    _, _, f, _ = _case(s, cited=("ev_001", "ev_002"))
    t = finding_trust(s, f)
    assert t["distinct_sources"] == 2 and not t["two_source_ok"]
    assert "needs corroboration" in t["label"] and "confidence" not in t["label"]


def test_struck_evidence_does_not_count(s):
    _, _, f, _ = _case(s)
    f.json = {**f.json, "rejected_evidence": [{"eid": "ev_003"}]}
    s.flush()
    t = finding_trust(s, f)
    assert t["distinct_sources"] == 1 and not t["two_source_ok"]


@pytest.mark.parametrize("status,watch,needs_review,verified", [
    ("draft", None, False, False),
    ("approved", None, False, False),          # approved, no fix
    ("approved", "watching", False, False),    # fix not confirmed yet
    ("draft", "confirmed", False, False),      # confirmed fix, finding not approved
    ("approved", "confirmed", True, False),    # flagged for review again
    ("approved", "confirmed", False, True),
])
def test_badge_says_verified_only_after_approval_and_confirmed_fix(s, status, watch,
                                                                   needs_review, verified):
    _, _, f, _ = _case(s, status=status, watch_status=watch, needs_review=needs_review)
    t = finding_trust(s, f)
    assert t["verified"] is verified
    words = t["label"].lower()
    assert ("verified" in words) is verified and "proven" not in words


def test_confidence_bands():
    assert [confidence_band(x) for x in (0.95, 0.8, 0.79, 0.6, 0.2, None)] == [
        "high", "high", "medium", "medium", "low", "low"]


# ── item 2: confirmed fixes ─────────────────────────────────────────────

def _reviews(s, product="Lumo", n=3, version="3.2.0"):
    for i in range(n):
        s.add(Review(source="play_store", ext_id=f"{product}{i}", rating=1,
                     text=f"Battery drain is terrible {i}", version=version, product=product,
                     created_at=(NOW - timedelta(days=25 + i)).replace(tzinfo=None)))
    s.add(Review(source="play_store", ext_id=f"{product}-ok", rating=1, text="Login broken",
                 product=product, created_at=(NOW - timedelta(days=24)).replace(tzinfo=None)))
    s.flush()


def test_only_recent_confirmed_watches_show(s):
    p, _, _, recent = _case(s, status="approved", watch_status="confirmed", confirmed_days_ago=2)
    _case(s, status="approved", watch_status="confirmed", confirmed_days_ago=30)  # too old
    _case(s, status="approved", watch_status="watching")                          # not confirmed
    _reviews(s)
    cards = recent_confirmed_fixes(s, p.id, user_id=1, as_of=NOW)
    assert [c["watch_id"] for c in cards] == [recent.id]
    c = cards[0]
    assert c["headline"] == "Fix confirmed — battery drain complaints down 62% since v3.2.1"
    assert c["chart"] == {"days": []}
    # The reply panel's own matching: three battery reviews, not the login one.
    assert c["reply_count"] == 3


def test_at_most_three_newest_first(s):
    p = None
    ids = []
    for d in (1, 5, 3, 9):
        p, _, _, w = _case(s, status="approved", watch_status="confirmed", confirmed_days_ago=d)
        ids.append((d, w.id))
    cards = recent_confirmed_fixes(s, p.id, user_id=1, as_of=NOW)
    assert [c["watch_id"] for c in cards] == [i for _, i in sorted(ids)[:3]]


def test_dismissal_is_per_user_and_sticks(s):
    p, _, _, w = _case(s, status="approved", watch_status="confirmed")
    dismiss_fix(s, 1, w.id)
    s.commit()
    assert recent_confirmed_fixes(s, p.id, user_id=1, as_of=NOW) == []
    assert [c["watch_id"] for c in recent_confirmed_fixes(s, p.id, user_id=2, as_of=NOW)] == [w.id]


# ── endpoints ───────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch, Session):
    engine = Session.kw["bind"]
    with Session() as sess:
        a, inv, f, w = _case(sess, "Lumo", status="approved", watch_status="confirmed",
                             confirmed_days_ago=1)
        b, _, _, wb = _case(sess, "Other", status="approved", watch_status="confirmed",
                            confirmed_days_ago=1)
        sess.commit()
        ids = dict(pid=a.id, other=b.id, inv=inv.id, watch=w.id, other_watch=wb.id)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from echolens.api.app import app
    c = TestClient(app)
    c.ids, c.app = ids, app
    return c


def test_finding_and_case_rows_carry_trust(client):
    i = client.ids
    inv = client.get(f"/investigations/{i['inv']}?product_id={i['pid']}").json()
    trust = inv["finding"]["trust"]
    assert trust["two_source_ok"] and trust["distinct_sources"] == 2
    rows = client.get(f"/cases?product_id={i['pid']}").json()["cases"]
    row = next(r for r in rows if r["id"] == i["inv"])
    assert row["trust"] == trust


def test_today_cards_are_product_scoped_and_dismissable(client, monkeypatch):
    import echolens.evidence_summary as es
    real = es.recent_confirmed_fixes
    monkeypatch.setattr(es, "recent_confirmed_fixes",
                        lambda *a, **k: real(*a, **{**k, "as_of": NOW}))
    i = client.ids
    cards = client.get(f"/today/overview?product_id={i['pid']}").json()["confirmed_fixes"]
    assert [c["watch_id"] for c in cards] == [i["watch"]]
    # Another product's watch cannot be dismissed from here, and is not shown here.
    assert client.post(f"/fixwatch/{i['other_watch']}/dismiss?product_id={i['pid']}"
                       ).status_code == 404
    r = client.post(f"/fixwatch/{i['watch']}/dismiss?product_id={i['pid']}")
    assert r.status_code == 200 and r.json() == {"dismissed": i["watch"]}
    assert client.get(f"/today/overview?product_id={i['pid']}").json()["confirmed_fixes"] == []
    other = client.get(f"/today/overview?product_id={i['other']}").json()["confirmed_fixes"]
    assert [c["watch_id"] for c in other] == [i["other_watch"]]


def test_dismiss_requires_reviewer(client):
    from echolens.auth import current_user
    client.app.dependency_overrides[current_user] = lambda: {
        "id": 9, "email": "v@x", "role": "viewer"}
    try:
        i = client.ids
        assert client.post(f"/fixwatch/{i['watch']}/dismiss?product_id={i['pid']}"
                           ).status_code == 403
    finally:
        client.app.dependency_overrides.clear()
