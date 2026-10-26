"""Demo safety and decision quality, with an isolated corpus and scripted IO."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db.models import (
    AnomalyEvent, Base, EvidenceRow, Finding, Investigation, Product,
    QueuedInvestigation, Release, Review, ReviewFeedback)

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


@pytest.fixture()
def db(monkeypatch):
    import echolens.db.session as db_session
    import echolens.llm.openai_client as oc

    class Refuse:
        def __init__(self, *args, **kwargs):
            raise AssertionError("demo automation must not construct a live client")

    monkeypatch.setattr(oc, "OpenAIClient", Refuse)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", factory)
    with factory() as session:
        yield session
    engine.dispose()


def _signal(s, product, slug="battery", metric="battery drain share of negatives"):
    a = AnomalyEvent(slug=slug, type="theme_volume_surge", metric=metric,
                     description=metric, status="pending", delta=0.3, z=3, window="7d",
                     product_id=product.id)
    s.add(a)
    s.flush()
    return a


def test_demo_triage_and_queue_never_launch_but_manual_admin_start_works(db, monkeypatch):
    from echolens.api import app as mod
    from echolens.orchestrator.queue import claim_next
    from echolens.orchestrator.triage import Decision, Orchestrator, run_triaged

    demo = Product(name="Demo", is_demo=True)
    db.add(demo)
    db.flush()
    a = _signal(db, demo)
    db.add(QueuedInvestigation(product_id=demo.id, anomaly_id=a.id, source="anomaly"))
    db.commit()
    assert Orchestrator(db, product_id=demo.id).triage() == []
    assert run_triaged(db, [Decision(a, "investigate", "stale decision")]) == []
    assert claim_next(db, demo.id, 100) is None
    assert claim_next(db, None, 100) is None
    spawned = []
    monkeypatch.setattr(mod, "_spawn", lambda *args: spawned.append(args))
    client = TestClient(mod.app)
    assert client.post(f"/anomalies/scan?product_id={demo.id}").status_code == 200
    result = client.post(f"/anomalies/triage?run=true&product_id={demo.id}")
    assert result.status_code == 200
    assert result.json()["started_investigations"] == []
    assert not spawned
    result = client.post("/investigations", json={"product_id": demo.id,
                         "description": "Investigate battery drain manually", "tier": "quick"})
    assert result.status_code == 200
    assert result.json()["status"] == "started" and len(spawned) == 1


def test_realistic_health_has_headroom_and_catastrophe_can_reach_zero(db):
    from echolens.portfolio import product_snapshot

    product = Product(name="Real app")
    db.add(product)
    db.flush()
    data = {"watches": [], "resolved": [], "latest": {}, "untriaged": 0,
            "waiting_incidents": 0, "sources": [], "chronic": [],
            "rates": (0.4, 0.3), "has_reviews": True}
    for i in range(40):
        inv = Investigation(id=i + 1, product_id=product.id, status="resolved")
        data["resolved"].append(inv)
        data["latest"][inv.id] = Finding(confidence=0.9, summary="Confirmed problem",
                                       json={"impact": {"impact_score": 0.8}})
    row = product_snapshot(db, product, NOW, {**data, "resolved": data["resolved"][:4]})
    assert 30 <= row["health"] <= 75
    assert product_snapshot(db, product, NOW, data)["health"] <= 5


def test_overlapping_cases_only_count_their_own_theme_and_rank_confirmed_first(db):
    from echolens.cases import case_rows

    product = Product(name="Real app")
    db.add(product)
    db.flush()
    for n, text in enumerate(["Battery drain after update"] * 4 +
                             ["Export crashes after update"] * 3 +
                             ["Battery drain and export crashes after update"] +
                             ["Shipping cost is too high"] * 2):
        db.add(Review(product=product.name, source="play_store", ext_id=str(n),
                      text=text, rating=1, created_at=NOW - timedelta(days=1)))
    for slug, confidence, support in [("battery", 0.72, "single_channel"),
                                      ("export", 0.89, "supported")]:
        a = _signal(db, product, slug, f"{slug} share of negatives")
        inv = Investigation(product_id=product.id, anomaly_id=a.id, status="resolved", created_at=NOW)
        db.add(inv)
        db.flush()
        db.add(Finding(investigation_id=inv.id, product_id=product.id, summary=slug,
                       confidence=confidence, json={"support_level": support,
                       "impact": {"terms": [slug, "update", "after"], "impact_score": 0.9,
                                  "affected_pct": 100, "affected_volume": 10}}))
    db.flush()
    rows = case_rows(db, product.id, NOW)
    by_title = {r["title"]: r for r in rows}
    assert by_title["battery"]["impact"]["affected_pct"] == 50
    assert by_title["export"]["impact"]["affected_pct"] == 40
    assert by_title["export"]["decision_rank"] < by_title["battery"]["decision_rank"]


@pytest.fixture()
def story(db):
    from echolens.synthetic.demo_story import seed_demo, reseed_demo
    seed_demo(db)
    reseed_demo(db)
    db.commit()
    return db, db.scalars(select(Product).where(Product.is_demo.is_(True))).one()


def test_reseeded_story_leads_with_confirmed_release_regression_and_has_working_examples(story):
    from echolens.cases import case_rows
    from echolens.synthetic.demo_story import seed_demo_story
    from echolens.themes.requests import discover_requests

    s, demo = story
    rows = sorted(case_rows(s, demo.id), key=lambda r: r["decision_rank"])
    needs = [r for r in rows if r["status"] in ("needs_review", "needs_human", "regressed")]
    first = needs[0]
    f = s.get(Finding, first["finding_id"])
    assert f.json["support_level"] == "supported" and f.confidence >= 0.85
    evidence = s.scalars(select(EvidenceRow).where(EvidenceRow.investigation_id == first["id"])).all()
    assert {"play_store", "github", "release_notes"} <= {e.source for e in evidence}
    release = s.scalars(select(Release).where(Release.product == demo.name, Release.version == "3.2.0")).one()
    assert any(e.ref.endswith("/releases/tag/v3.2.0") for e in evidence)
    first_spike = s.scalars(select(Review).where(Review.product == demo.name,
        Review.text.like("%Battery destroyed%")).order_by(Review.created_at)).first()
    assert (first_spike.created_at - release.released_at).days >= 3
    findings = s.scalars(select(Finding).where(Finding.product_id == demo.id)).all()
    assert any(f.json.get("working_hypotheses") for f in findings)
    assert any("working lead" in f.summary.lower() for f in findings)
    assert len(s.scalars(select(ReviewFeedback)).all()) >= 10
    assert any(g["count"] >= 5 for g in discover_requests(s, product=demo.name)["requests"])
    assert not s.scalars(select(AnomalyEvent).where(
        AnomalyEvent.product_id == demo.id, AnomalyEvent.status == "pending")).all()
    assert seed_demo_story(s) == {"skipped": "demo already has cases"}


def test_seeded_support_never_cites_happy_reviews(story):
    from echolens.intent import BUG, UX_CONFUSION, classify

    s, demo = story
    for inv in s.scalars(select(Investigation).where(Investigation.product_id == demo.id)):
        for e in s.scalars(select(EvidenceRow).where(EvidenceRow.investigation_id == inv.id)):
            review = s.scalars(select(Review).where(Review.product == demo.name, Review.ext_id == e.ref)).first()
            if review and review.rating >= 4 and (e.json or {}).get("supports"):
                assert classify(review.text, review.rating) in (BUG, UX_CONFUSION), (inv.id, e.ref)


def test_missing_demo_case_has_refresh_hint_only_in_demo_scope(db):
    from echolens.api.app import app

    demo, real = Product(name="Demo", is_demo=True), Product(name="Real")
    db.add_all([demo, real])
    db.commit()
    client = TestClient(app)
    missing = client.get(f"/investigations/999999?product_id={demo.id}")
    assert missing.status_code == 404 and missing.json()["demo_refreshed"] is True
    other = client.get(f"/investigations/999999?product_id={real.id}")
    assert other.status_code == 404 and "demo_refreshed" not in other.json()
    inv = Investigation(product_id=real.id, status="resolved")
    db.add(inv)
    db.commit()
    hidden = client.get(f"/investigations/{inv.id}?product_id={demo.id}")
    assert hidden.status_code == 404 and "demo_refreshed" not in hidden.json()


def test_demo_chat_requires_explicit_manual_launch(db, monkeypatch):
    from echolens.api import app as mod
    from echolens import chat

    demo = Product(name="Demo", is_demo=True)
    db.add(demo)
    db.commit()
    monkeypatch.setattr(chat, "route", lambda *a, **k: {"type": "launch", "description": "new crash"})
    spawned = []
    monkeypatch.setattr(mod, "_spawn", lambda *a: spawned.append(a))
    user = {"id": 0, "role": "admin"}
    body = mod.ChatBody(message="new crash", product_id=demo.id)
    result = mod._chat_respond(body, user)
    assert result["type"] == "answer" and not spawned
    body.force_investigate = True
    assert mod._chat_respond(body, user)["type"] == "investigation" and len(spawned) == 1


def test_compound_theme_does_not_count_other_sync_problems(db):
    from echolens.cases import affected_impact

    product = Product(name="Real")
    db.add(product)
    db.flush()
    anomaly = _signal(db, product, metric="sync crashes share of negatives")
    finding = Finding(json={"impact": {"impact_score": 1, "rating_impact": 0, "measured": False}})
    for n, text in enumerate(["Sync crashes after upload"] * 2 + ["Sync drains battery"] * 8):
        db.add(Review(product=product.name, source="play_store", ext_id=str(n), text=text,
                      rating=1, created_at=NOW - timedelta(days=1)))
    db.flush()
    impact = affected_impact(db, finding, anomaly, product.name, NOW)
    assert impact["affected_pct"] == 20 and impact["affected_volume"] == 2
    assert impact["impact_score"] < 0.2
    assert impact["measured"] is True


def test_workspace_triage_and_queue_skip_demo_but_keep_real_work(db):
    from echolens.eval.harness import ScriptedLLM
    from echolens.orchestrator.queue import claim_next
    from echolens.orchestrator.triage import Orchestrator

    demo, real = Product(name="Demo", is_demo=True), Product(name="Real")
    db.add_all([demo, real])
    db.flush()
    da, ra = _signal(db, demo, "demo-signal"), _signal(db, real, "real-signal")
    llm = ScriptedLLM([{"decisions": [{"anomaly": "real-signal", "decision": "investigate",
                                    "reason": "real regression", "budget_tier": "quick"}]}])
    decisions = Orchestrator(db, llm=llm).triage()
    assert [d.anomaly.id for d in decisions] == [ra.id]
    assert da.status == "pending"
    db.add_all([QueuedInvestigation(product_id=demo.id, anomaly_id=da.id, priority=1),
                QueuedInvestigation(product_id=real.id, anomaly_id=ra.id, priority=20)])
    db.flush()
    assert claim_next(db, None, 100).product_id == real.id


def test_rank_uses_timestamp_for_ties_even_when_ids_are_backdated(db):
    from echolens.cases import case_rows

    product = Product(name="Real")
    db.add(product)
    db.flush()
    ids = []
    for at in (NOW - timedelta(hours=1), NOW - timedelta(hours=5)):
        inv = Investigation(product_id=product.id, status="resolved", created_at=at)
        db.add(inv)
        db.flush()
        ids.append(inv.id)
        db.add(Finding(investigation_id=inv.id, confidence=0.89, summary="Confirmed crash",
            json={"support_level": "supported", "impact": {"impact_score": 0.5}}))
    db.flush()
    rows = {r["id"]: r for r in case_rows(db, product.id, NOW)}
    assert rows[ids[0]]["decision_rank"] < rows[ids[1]]["decision_rank"]
