"""What the public pages read before anyone signs in: /auth/config's
`signup_open`, which decides whether the sign-in form offers "Create the admin
account" at all."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens import auth
from echolens.config import settings
from echolens.db.models import Base

PASSWORD = "correct-horse-battery-9"


def _client(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", eng)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: eng)
    from echolens.api.app import app
    return TestClient(app), Session


def test_signup_is_open_only_before_the_first_account_in_dev(monkeypatch):
    monkeypatch.setattr(settings, "echolens_env", "dev")
    client, Session = _client(monkeypatch)
    assert client.get("/auth/config").json()["signup_open"] is True
    with Session() as s:
        auth.create_user(s, "admin@team.com", PASSWORD, "admin")
        s.commit()
    assert client.get("/auth/config").json()["signup_open"] is False


def test_signup_is_never_open_when_auth_is_required(monkeypatch):
    monkeypatch.setattr(settings, "echolens_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-" + "x" * 32)
    client, _ = _client(monkeypatch)
    # Even with no users: production bootstraps its admin from the environment,
    # and /auth/signup refuses a stranger who is merely first.
    body = client.get("/auth/config").json()
    assert body["auth_required"] is True and body["signup_open"] is False
