"""API smoke tests over an isolated in-memory DB (no live server, no LLM)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens.db.models import Base
from echolens.synthetic.generate import generate


@pytest.fixture()
def client(monkeypatch):
    # StaticPool: every connection shares ONE in-memory DB (background thread included)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        generate(s)
        s.commit()
    # point the app's session factory at this in-memory DB
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from echolens.api.app import app
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["db"] is True


def test_scan_then_list_anomalies(client):
    scanned = client.post("/anomalies/scan").json()
    assert "auto-neg-review-spike" in scanned["detected"]
    listed = client.get("/anomalies").json()["anomalies"]
    assert any(a["slug"] == "auto-neg-review-spike" for a in listed)


def test_costs_endpoint_shape(client):
    r = client.get("/costs").json()
    assert set(r) >= {"total_cost_usd", "total_tokens", "per_agent"}


def test_manual_case_validation(client):
    r = client.post("/investigations", json={})  # neither slug nor description
    assert r.status_code == 422


def test_first_signup_becomes_admin(client):
    # the very first account is bootstrapped as admin regardless of requested role
    r = client.post("/auth/signup", json={"email": "first@x.com", "password": "pw", "role": "viewer"})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
