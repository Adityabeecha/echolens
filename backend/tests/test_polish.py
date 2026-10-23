"""Polish regressions: one incident per decision, with health weights unchanged."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens import chat
from echolens.db.models import (AnomalyEvent, Base, Investigation, Product,
                                QueuedInvestigation, TriageDecision)
from echolens.detector.incidents import incident_view
from echolens.cases import signal_rows
from echolens.portfolio import portfolio

NOW = datetime.now(timezone.utc)


@pytest.fixture()
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    p = Product(name="Polish"); s.add(p); s.flush()

    def signal(slug, typ, z, metric="battery", **kw):
        a = AnomalyEvent(slug=slug, type=typ, z=z, metric=metric, delta=0.4,
                         window="7d", window_start=NOW - timedelta(days=7),
                         window_end=NOW, description=metric, status="pending",
                         product_id=p.id, **kw)
        s.add(a); s.flush()
        return a

    # Insert weaker incident first to catch insertion-order ranking.
    battery = signal("auto-theme-battery", "theme_volume_surge", 2.8)
    signal("auto-issues-battery", "issue_velocity_surge", 2.1)
    spike = signal("spike", "negative_review_spike", 4.0, "1-star rate")
    signal("drop", "rating_drop", 3.4, "rating")
    signal("drop-copy", "rating_drop", 2.9, "rating")
    signal("standalone", "manual", 3.7, "Export crashes")
    signal("other", "manual", 1.2, "Login confusing")
    s.commit()

    import echolens.api.app as app_mod
    from echolens.db import session as db_session
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    monkeypatch.setattr(app_mod, "_drain_queue_bg", lambda *a, **kw: None)
    monkeypatch.setattr(app_mod, "_run_investigation_bg", lambda *a, **kw: None)
    app_mod.limiter.reset()
    yield s, p, spike, battery, signal, TestClient(app_mod.app)
    s.close(); engine.dispose()


def test_portfolio_counts_cases_incidents_but_preserves_raw_health_weight(world):
    s, p, *_ = world
    signals, incidents = incident_view(s, p.name, signal_rows(s, p.id))
    grouped = set(slug for i in incidents for slug in i["members"])
    expected = len(incidents) + sum(not r["dismissed"] and r["slug"] not in grouped
                                    for r in signals)
    row = portfolio(s, NOW)["products"][0]
    assert expected == 4
    assert row["untriaged"] == expected
    assert row["score"] == 7 * 4.0
    assert row["health"] == 72.0
    reason = next(r for r in row["reasons"] if r["kind"] == "untriaged")
    assert reason["text"] == "4 incidents waiting for triage"
    assert reason["weight"] == 28.0


def test_ranking_lists_incident_leads_once_and_in_strength_order(world):
    s, p, spike, _, *_ = world
    result = chat.route(s, "What's our biggest unresolved complaint?", p.id, p.name)
    assert [r["slug"] for r in result["signals"]] == [spike.slug, "standalone", "auto-theme-battery"]
    assert result["signal_count"] == 4
    assert "4 incidents waiting" in result["text"]
    assert result["text"].count("Average rating is falling") == 0


def test_waiting_count_excludes_muted_dismissed_queued_and_investigated(world):
    s, p, spike, battery, make, _ = world
    from echolens.themes.overrides import set_override
    set_override(s, p.id, "theme-p1-battery", "mute")
    s.add(TriageDecision(anomaly_id=spike.id, decision="ignore", reason="noise"))
    # The remaining two product-wide members still form one incident.
    queued = s.scalar(select(AnomalyEvent).where(AnomalyEvent.slug == "standalone"))
    s.add(QueuedInvestigation(product_id=p.id, anomaly_id=queued.id, status="queued",
                              source="anomaly", priority=10, budget_tier="quick"))
    other = s.scalar(select(AnomalyEvent).where(AnomalyEvent.slug == "other"))
    s.add(Investigation(anomaly_id=other.id, product_id=p.id, status="running",
                        opened_by="anomaly", budget_tier="quick"))
    s.commit()
    row = portfolio(s, NOW)["products"][0]
    assert row["untriaged"] == 1
    assert row["score"] == 28.0
    assert chat.route(s, "biggest complaint", p.id)["signal_count"] == 1


def test_topic_signal_answer_uses_incident_lead(world):
    s, p, _, battery, *_ = world
    response = chat.route(s, "tell me about battery", p.id)
    assert [r["slug"] for r in response["signals"]] == [battery.slug]
    assert set(response["signals"][0]["members"]) == {battery.slug, "auto-issues-battery"}


@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
def test_ranking_card_targets_the_named_incident_and_queues_it(world, path):
    s, p, spike, _, _, tc = world
    response = tc.post(path, json={"message": "What's our biggest unresolved complaint?",
                                   "product_id": p.id})
    if path.endswith("stream"):
        import json
        blocks = response.text.split("\n\n")
        result = next(json.loads(b.split("data: ", 1)[1]) for b in blocks
                      if b.startswith("event: answer\n"))
    else:
        result = response.json()
    step = result["next_step"]
    assert step["slug"] == spike.slug
    assert step["question"] == "1-star reviews are spiking"
    # Same API the Cases selection uses; never a new manual question anomaly.
    queued = tc.post("/queue/themes", json={"product_id": p.id, "slugs": [step["slug"]],
                                           "statements": {step["slug"]: step["question"]}})
    assert queued.status_code == 200
    assert len(queued.json()["queued"]) == 1
    s.expire_all()
    row = s.scalar(select(QueuedInvestigation))
    assert row.anomaly_id == spike.id
    assert s.scalar(select(AnomalyEvent).where(AnomalyEvent.slug == "drop")).status == "merged"
    assert len(s.scalars(select(AnomalyEvent)).all()) == 7


def test_topic_without_waiting_signals_keeps_literal_question(world):
    _, p, *_, tc = world
    result = tc.post("/chat", json={"message": "tell me about dark mode", "product_id": p.id}).json()
    assert result["next_step"] == {"kind": "investigate", "question": "tell me about dark mode",
                                    "allowed": True, "reason": None}


def test_topic_in_a_weaker_member_still_routes_to_the_incident_lead(world):
    s, p, _, battery, *_ = world
    issue = s.scalar(select(AnomalyEvent).where(AnomalyEvent.slug == "auto-issues-battery"))
    issue.metric = "background wakeups per week"
    s.commit()
    result = chat.route(s, "tell me about background wakeups", p.id)
    assert result["basis"]["kind"] == "signals"
    assert result["signals"][0]["slug"] == battery.slug


def test_waiting_counts_are_product_scoped_and_latest_triage_wins(world):
    s, p, spike, _, _, _ = world
    other = Product(name="Other"); s.add(other); s.flush()
    s.add(AnomalyEvent(slug="other-spike", product_id=other.id, type="negative_review_spike",
                      metric="1-star rate", delta=0.4, z=9.0, window="7d", description="spike",
                      window_start=NOW - timedelta(days=7), window_end=NOW, status="pending"))
    s.add(TriageDecision(anomaly_id=spike.id, decision="ignore", reason="noise")); s.flush()
    s.add(TriageDecision(anomaly_id=spike.id, decision="investigate", reason="reconsidered"))
    s.commit()
    rows = {r["product_id"]: r for r in portfolio(s, NOW)["products"]}
    assert rows[p.id]["untriaged"] == 4
    assert rows[other.id]["untriaged"] == 1
    assert chat.route(s, "biggest complaint", p.id)["signals"][0]["slug"] == spike.slug


def test_ranking_without_a_waiting_target_never_offers_a_literal_question_case(world):
    s, p, *_, tc = world
    for a in s.scalars(select(AnomalyEvent)).all():
        s.add(TriageDecision(anomaly_id=a.id, decision="ignore", reason="not actionable"))
    s.commit()
    result = tc.post("/chat", json={"message": "What's our biggest unresolved complaint?",
                                  "product_id": p.id}).json()
    assert result["next_step"] is None
