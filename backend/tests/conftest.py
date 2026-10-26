from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from echolens.config import settings
from echolens.db.models import Base
from echolens.synthetic.generate import generate


@pytest.fixture(autouse=True)
def _hermetic_auth(monkeypatch):
    """Pin the auth-affecting settings for every test.

    `Settings` reads the developer's real `.env`, so switching it to
    `ECHOLENS_ENV=staging` to try Google sign-in turned auth on for the whole
    suite and 32 tests started getting 401 where they asserted 404. The DB was
    already hermetic; these are the other inputs that decide behaviour.

    Tests that exercise auth (test_auth, test_guest_and_google) override these
    with their own monkeypatch, which still wins — this only sets the baseline.
    """
    monkeypatch.setattr(settings, "echolens_env", "dev", raising=False)
    monkeypatch.setattr(settings, "allow_guest", False, raising=False)
    monkeypatch.setattr(settings, "google_client_id", "", raising=False)
    monkeypatch.setattr(settings, "google_admin_emails", "", raising=False)
    monkeypatch.setattr(settings, "google_default_role", "reviewer", raising=False)


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, expire_on_commit=False)
    with Session() as s:
        generate(s)
        s.commit()
    return eng


@pytest.fixture()
def session(engine):
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    yield s
    s.rollback()
    s.close()


@pytest.fixture()
def api_db_r4(monkeypatch):
    """The API over a fresh in-memory DB (round 4 fix tests)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from echolens.db import session as db_session
    from echolens.db.models import Base
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from echolens.api.app import app
    return TestClient(app), Session
