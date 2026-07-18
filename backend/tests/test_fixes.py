"""Regression tests for the audit fixes (dynamic dates, real sources, limits,
pause, signup hardening, generic detection)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens.config import settings
from echolens.db.models import Base, Setting
from echolens.detector.detect import detect_rating_drop, reference_now, scan
from echolens.synthetic.generate import generate


# ── #3 dynamic dates ────────────────────────────────────────────────────

def test_reference_now_tracks_latest_data(session):
    # synthetic corpus ends 2026-07-17 → reference_now reflects the data, not a
    # hardcoded constant
    assert reference_now(session).date().isoformat() == "2026-07-17"


def test_scan_uses_data_derived_now(session):
    events = scan(session)  # no as_of → derived from data
    assert any(e.slug == "auto-neg-review-spike" for e in events)


# ── #4 generic detection ────────────────────────────────────────────────

def test_rating_drop_detector_is_theme_agnostic(session):
    c = detect_rating_drop(session)
    assert c is not None and c.type == "rating_drop"
    assert c.z >= 1.0


# ── API fixture ─────────────────────────────────────────────────────────

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
    from echolens.api.app import app
    return TestClient(app)


# ── #7 adjustable limits ────────────────────────────────────────────────

def test_limits_can_be_changed_and_persist(client):
    r = client.put("/settings/limits", json={"daily_investigations": 9})
    assert r.status_code == 200 and r.json()["daily_investigations"] == 9
    # reflected in the feed summary's daily_limit
    assert client.get("/feed/summary").json()["daily_limit"] == 9
    # reflected in costs summary limits
    assert client.get("/costs/summary").json()["limits"]["daily_investigations"] == 9


# ── #2 real sources ─────────────────────────────────────────────────────

def test_sources_reflect_connected_state(client):
    client.post("/sources/connect", json={"source": "github", "identifier": "acme/app", "product": "Acme"})
    names = [c["detail"] for c in client.get("/sources").json()["connected"]]
    assert any("acme/app" in d for d in names)


# ── #8 signup hardening ─────────────────────────────────────────────────

def test_open_signup_blocked_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "echolens_env", "production")
    r = client.post("/auth/signup", json={"email": "x@y.com", "password": "pw"})
    assert r.status_code == 403  # first admin must come from bootstrap env


# ── #6 pause endpoint ───────────────────────────────────────────────────

def test_pause_sets_flag(client):
    from echolens.db.models import Investigation
    with db_session.session_scope() as s:
        inv = Investigation(anomaly_id=1, status="running", budget_tier="quick", budget_json={})
        s.add(inv); s.flush()
        inv_id = inv.id
    r = client.post(f"/investigations/{inv_id}/pause")
    assert r.status_code == 200
    assert client.get(f"/investigations/{inv_id}").json()["paused"] is True
