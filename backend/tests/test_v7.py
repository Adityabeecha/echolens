"""v7.0 tests: conversational RAG, the weekly brief, and theme lifecycle.
One test per exit criterion."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens.brief import weekly_brief
from echolens.chat import route
from echolens.db.models import (
    AnomalyEvent, Base, Finding, FixWatch, Investigation, Recommendation, Review)
from echolens.impact import quantify
from echolens.synthetic.generate import generate
from echolens.themes import theme_lifecycle

TZ = timezone.utc


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    generate(s)
    s.commit()
    return s


def _resolved(s, summary, days_ago=1):
    anomaly = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).first()
    inv = Investigation(anomaly_id=anomaly.id, status="resolved", opened_by="anomaly",
                        budget_tier="quick", budget_json={},
                        created_at=datetime.now(TZ) - timedelta(days=days_ago))
    s.add(inv); s.flush()
    fj = {"summary": summary, "prose": f"{summary} confirmed.", "confidence": 0.85,
          "impact": quantify(s, anomaly, {"summary": summary, "prose": ""})}
    f = Finding(investigation_id=inv.id, summary=summary, confidence=0.85, status="approved", json=fj)
    s.add(f); s.flush()
    s.add(Recommendation(finding_id=f.id, action=f"fix {summary}", rank=1, impact="HIGH", effort="MED"))
    s.flush()
    return inv, f


# ── exit #1: a chat question → cited answer OR a launched investigation ──

def test_chat_answer_is_cited_to_a_finding():
    s = _session()
    inv, f = _resolved(s, "battery drain from the v3.2 background sync")
    s.commit()
    r = route(s, "what's going on with battery drain?")
    assert r["type"] == "answer"
    assert r["citations"] and r["citations"][0]["investigation_id"] == inv.id  # clickable to the case


def test_chat_unknown_topic_is_honest():
    s = _session()
    r = route(s, "how is the onboarding funnel doing")
    assert r["type"] == "answer" and r["citations"] == [] and "haven't investigated" in r["text"].lower()


def test_chat_investigate_intent_launches():
    s = _session()
    r = route(s, "why did ratings dip last Tuesday?")
    assert r["type"] == "launch" and "ratings dip" in r["description"].lower()


def test_chat_ranking_query_uses_open_problems():
    s = _session()
    inv, f = _resolved(s, "checkout crash on payment step")
    s.commit()
    r = route(s, "what's our biggest unresolved complaint?")
    assert r["type"] == "answer" and r["citations"]
    assert r["citations"][0]["investigation_id"] == inv.id


# ── exit #2: the weekly brief sends unprompted, every claim cites a case ─

def test_weekly_brief_is_cited_and_recommends_a_fix():
    s = _session()
    inv, f = _resolved(s, "battery drain from background sync", days_ago=2)
    s.commit()
    b = weekly_brief(s)
    assert b["new_problems"] and b["new_problems"][0]["investigation_id"] == inv.id
    assert b["fix_next"] and b["fix_next"]["investigation_id"] == inv.id
    # every line that makes a claim references a clickable case #N
    claim_lines = [ln for ln in b["lines"] if ln.startswith(("•", "→"))]
    assert claim_lines and all("case #" in ln for ln in claim_lines)


# ── exit #3: a chronic theme (>60 days) is visibly flagged with history ──

def test_chronic_theme_flagged_with_history():
    s = _session()
    inv, f = _resolved(s, "battery drain from background sync", days_ago=75)  # old + unfixed
    s.commit()
    themes = theme_lifecycle(s)
    chronic = [t for t in themes if t["status"] == "chronic"]
    assert chronic, "an unresolved 75-day-old theme should be chronic"
    t = chronic[0]
    assert t["age_days"] >= 60 and t["first_seen"] and t["last_seen"]   # history present
    assert inv.id in t["cases"]


def test_confirmed_theme_is_resolved_not_chronic():
    s = _session()
    inv, f = _resolved(s, "shipping cost complaints", days_ago=90)
    s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="r/r", issue_number=1,
                   status="confirmed", terms=["shipping", "cost"], metric="shipping",
                   baseline_rate=5.0, post_rate=0.0, confirmed_at=datetime.now(TZ)))
    s.commit()
    statuses = {t["theme"]: t["status"] for t in theme_lifecycle(s)}
    assert any(st == "resolved" for st in statuses.values())


# ── API surface ─────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        generate(s)
        _resolved(s, "battery drain from background sync")
        s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    import echolens.api.app as app_mod
    monkeypatch.setattr(app_mod, "_run_investigation_bg", lambda *a, **k: None)
    return TestClient(app_mod.app)


def test_chat_endpoint_answers(client):
    r = client.post("/chat", json={"message": "tell me about battery drain"})
    assert r.status_code == 200 and r.json()["type"] == "answer" and r.json()["citations"]


def test_chat_endpoint_launches(client):
    r = client.post("/chat", json={"message": "investigate the new crash on export"})
    body = r.json()
    assert body["type"] == "investigation" and body["investigation_id"]


def test_brief_and_themes_endpoints(client):
    assert "lines" in client.get("/brief").json()
    assert "themes" in client.get("/themes").json()


def test_finding_followup_addendum(client):
    r = client.post("/findings/1/followup", json={"question": "does this affect iOS too?"})
    assert r.status_code == 200 and "answer" in r.json()
    # the addendum is persisted on the finding
    inv_id = r.json()["investigation_id"]
    fin = client.get(f"/investigations/{inv_id}").json()["finding"]
    assert fin.get("addenda") and fin["addenda"][0]["question"] == "does this affect iOS too?"
