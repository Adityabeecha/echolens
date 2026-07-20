"""Regression tests for the code-audit fixes: dynamic trigger date, anomaly
status by outcome, wall-clock survival, async challenge, concurrency guard,
adaptive-tier baseline, real-product terms, GitHub error handling."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
import echolens.detector.detect as det
from echolens.config import settings
from echolens.db.models import AnomalyEvent, Base, Finding, Investigation, Review
from echolens.eval.harness import ScriptedLLM
from echolens.synthetic.generate import generate

TZ = timezone.utc


def _lumo():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    generate(s)
    s.commit()
    return s


# ── #1 dynamic 'today' + #8 anomaly status by outcome ───────────────────

def test_trigger_today_is_dynamic_and_anomaly_status_reflects_outcome():
    from echolens.investigator.graph import Investigator
    s = _lumo()
    s.add(Review(source="play_store", ext_id="late_1", rating=1, text="new complaint",
                 created_at=datetime(2026, 8, 1, tzinfo=TZ)))
    s.commit()
    anomaly = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).first()
    responses = [
        {"thought": "thin", "action": "conclude", "conclusion": {"status": "insufficient_evidence", "reason": "x"}},
        {"summary": "insufficient", "prose": "checked", "confidence": 0.3, "supported_hypothesis": None,
         "checked": ["play_store"], "what_would_settle_it": "more"},
    ]
    inv = Investigator(s, anomaly, llm=ScriptedLLM(responses)).run()
    assert inv.checkpoint_json["trigger"]["today"] == "2026-08-01"   # not the hardcoded 2026-07-17
    assert inv.status == "insufficient_evidence"
    assert anomaly.status == "insufficient_evidence"                 # not blindly "closed"


# ── #2 wall-clock budget survives restart ───────────────────────────────

def test_wall_clock_counts_prior_elapsed():
    import time
    from echolens.investigator import guards
    from echolens.investigator.state import Budget
    b = Budget.for_tier("quick")             # max_wall_clock_s = 900
    b.started_at = time.monotonic()
    b.prior_elapsed_s = 100_000              # already way over from a prior segment
    assert any("wall_clock" in r for r in guards.budget_exceeded(b))


# ── #7 adaptive_tier keeps the LLM's choice as a baseline ───────────────

def test_adaptive_tier_uses_proposed_as_baseline():
    from echolens.orchestrator.triage import adaptive_tier
    s = _lumo()
    # theme surge echoed in GitHub issues → complexity nudges the tier UP one step
    # from whatever the LLM proposed (its choice is the baseline, not discarded).
    a = AnomalyEvent(slug="q1", type="theme_volume_surge", metric="battery drain share",
                     delta=0, z=1.0, window="7d", description="d", status="pending")
    s.add(a); s.flush()
    assert adaptive_tier(a, s, "standard") == "deep"
    assert adaptive_tier(a, s, "quick") == "standard"
    # a strong single-source spike (z>=3) nudges a "deep" proposal DOWN one step
    a2 = AnomalyEvent(slug="q2", type="negative_review_spike", metric="daily volume", delta=0,
                      z=4.0, window="7d", description="d", status="pending")
    s.add(a2); s.flush()
    assert adaptive_tier(a2, s, "deep") == "standard"


# ── #9 a real product's terms replace the Lumo demo terms ───────────────

def test_real_product_terms_drop_demo_terms(monkeypatch):
    monkeypatch.setattr(settings, "detector_extra_terms", "checkout")
    s = _lumo()
    slugs = {e.slug for e in det.scan(s)}
    assert "auto-theme-battery-drain" not in slugs   # demo battery theme no longer scanned
    assert "auto-post-slow" not in slugs             # demo reddit theme dropped too


# ── #12 GitHub collector surfaces API errors instead of crashing ────────

class _Resp:
    def __init__(self, status, data, text=""):
        self.status_code, self._data, self.text = status, data, text

    def json(self):
        return self._data


def test_github_ensure_list_rejects_error_payloads():
    from echolens.collectors.github import _ensure_list
    with pytest.raises(RuntimeError):
        _ensure_list(_Resp(404, {"message": "Not Found"}), "issues")
    with pytest.raises(RuntimeError):
        _ensure_list(_Resp(200, {"message": "API rate limit exceeded"}), "issues")  # 200 but not a list
    assert _ensure_list(_Resp(200, [{"number": 1}]), "issues") == [{"number": 1}]


# ── API fixture for #4 + #16 ────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        generate(s)
        s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    import echolens.api.app as app_mod
    monkeypatch.setattr(app_mod, "_run_challenge_bg", lambda *a, **k: None)      # no real LLM
    monkeypatch.setattr(app_mod, "_run_investigation_bg", lambda *a, **k: None)
    return TestClient(app_mod.app), Session


# ── #16 concurrency guard ───────────────────────────────────────────────

def test_concurrent_investigation_guard(client):
    tc, Session = client
    with Session() as s:
        a = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).first()
        s.add(Investigation(anomaly_id=a.id, status="running", opened_by="anomaly",
                            budget_tier="quick", budget_json={}))
        s.commit()
    r = tc.post("/investigations", json={"anomaly_slug": "demo1", "tier": "quick"})
    assert r.status_code == 200 and r.json()["status"] == "already_running"


# ── #4 challenge returns immediately (does not run the loop inline) ──────

def test_triage_run_does_not_duplicate_cases(client, monkeypatch):
    """Re-running triage must not open a second case for an anomaly that already
    has one (the duplicate-cases bug), and it returns immediately."""
    tc, Session = client
    import echolens.orchestrator.triage as triage_mod
    from echolens.orchestrator.triage import Decision

    class FakeOrch:
        def __init__(self, session, daily_limit=5, product_id=None):
            self.session = session

        def triage(self):
            a = self.session.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).first()
            a.status = "pending"  # pretend it's re-detected each run
            self.session.flush()
            return [Decision(anomaly=a, decision="investigate", reason="x", budget_tier="quick")]

    monkeypatch.setattr(triage_mod, "Orchestrator", FakeOrch)
    assert tc.post("/anomalies/triage?run=true").status_code == 200
    assert tc.post("/anomalies/triage?run=true").status_code == 200
    with Session() as s:
        a = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).first()
        count = len(s.scalars(select(Investigation).where(Investigation.anomaly_id == a.id)).all())
    assert count == 1  # exactly one case, not a duplicate


def test_challenge_returns_immediately(client):
    tc, Session = client
    with Session() as s:
        a = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).first()
        inv = Investigation(anomaly_id=a.id, status="resolved", opened_by="anomaly",
                            budget_tier="quick", budget_json={})
        s.add(inv); s.flush()
        f = Finding(investigation_id=inv.id, summary="cause", confidence=0.8, status="draft",
                    json={"summary": "cause", "confidence": 0.8})
        s.add(f); s.commit()
        fid = f.id
    r = tc.post(f"/findings/{fid}/review", json={"action": "challenge", "note": "reconsider sync"})
    assert r.status_code == 200 and r.json()["status"] == "challenged"
    reopened = r.json()["reopened_investigation_id"]
    # the re-opened row exists (created synchronously) and is running
    assert tc.get(f"/investigations/{reopened}").json()["status"] == "running"
