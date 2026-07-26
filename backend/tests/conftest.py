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


@pytest.fixture(scope="session")
def engine():
    eng = create_engine("sqlite://")  # in-memory, hermetic
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
