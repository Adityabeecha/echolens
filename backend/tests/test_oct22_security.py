"""Regressions for the 2026-10-22 review: auth and deployment safety."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from echolens import auth, google_auth
from echolens.config import Settings, settings


def test_google_sign_in_needs_an_allowed_domain_or_an_account(monkeypatch):
    monkeypatch.setattr(settings, "google_admin_emails", "owner@gmail.com")
    monkeypatch.setattr(settings, "google_allowed_domains", "acme.com")
    assert google_auth.may_join("owner@gmail.com", existing_user=False)
    assert google_auth.may_join("pm@acme.com", existing_user=False)
    assert google_auth.may_join("pm@ACME.com", existing_user=False)
    assert not google_auth.may_join("stranger@gmail.com", existing_user=False)
    assert google_auth.may_join("stranger@gmail.com", existing_user=True)
    monkeypatch.setattr(settings, "google_allowed_domains", "")
    assert not google_auth.may_join("pm@acme.com", existing_user=False)


def test_google_default_role_is_viewer():
    assert Settings.model_fields["google_default_role"].default == "viewer"


def test_role_comes_from_the_database_not_the_token(monkeypatch, engine):
    from sqlalchemy.orm import sessionmaker
    from echolens.db import session as db_session

    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        u = auth.create_user(s, "demoted@team.com", "irrelevant-pw", "admin")
        s.commit()
        uid = u.id
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    token_claims = {"sub": str(uid), "role": "admin"}

    with Session() as s:
        s.get(auth.User, uid).role = "viewer"
        s.commit()
    assert auth.principal_for(uid, token_claims)["role"] == "viewer"

    with Session() as s:
        s.delete(s.get(auth.User, uid))
        s.commit()
    with pytest.raises(HTTPException) as e:
        auth.principal_for(uid, token_claims)
    assert e.value.status_code == 401


def test_password_rule():
    assert auth.password_problem("short")
    assert auth.password_problem("password123")
    assert auth.password_problem("a-long-unique-passphrase") is None


def test_forgotten_env_on_a_real_database_refuses_to_boot(monkeypatch):
    # CI exports ECHOLENS_ENV=dev; a process environment counts as "set", so
    # it has to be absent for this to model a deploy that forgot it.
    monkeypatch.delenv("ECHOLENS_ENV", raising=False)
    s = Settings(_env_file=None, echolens_db_url="postgresql://x@db/echolens")
    assert any("ECHOLENS_ENV is not set" in p for p in s.check_production_ready())
    local = Settings(_env_file=None, echolens_db_url="sqlite:///echolens.db")
    assert not any("ECHOLENS_ENV" in p for p in local.check_production_ready())
    explicit = Settings(_env_file=None, echolens_env="dev",
                        echolens_db_url="postgresql://x@db/echolens")
    assert not any("ECHOLENS_ENV is not set" in p for p in explicit.check_production_ready())


def test_slack_clicks_verified_by_signing_secret(monkeypatch):
    import hashlib, hmac, json, time
    from urllib.parse import urlencode
    from fastapi.testclient import TestClient
    from echolens.api import app as api

    monkeypatch.setattr(settings, "slack_signing_secret", "sign-secret")
    monkeypatch.setattr(settings, "slack_action_token", "")
    body = urlencode({"payload": json.dumps({"actions": [{"value": "approve:999999"}]})}).encode()
    ts = str(int(time.time()))

    def sig(b: bytes, t: str) -> str:
        return "v0=" + hmac.new(b"sign-secret", f"v0:{t}:".encode() + b, hashlib.sha256).hexdigest()

    tc = TestClient(api.app, raise_server_exceptions=False)
    hdr = {"content-type": "application/x-www-form-urlencoded",
           "x-slack-request-timestamp": ts}
    bad = tc.post("/integrations/slack/act", content=body,
                  headers=hdr | {"x-slack-signature": "v0=deadbeef"})
    assert bad.status_code == 401
    stale = str(int(time.time()) - 3600)
    old = tc.post("/integrations/slack/act", content=body,
                  headers=hdr | {"x-slack-request-timestamp": stale,
                                 "x-slack-signature": sig(body, stale)})
    assert old.status_code == 401
    good = tc.post("/integrations/slack/act", content=body,
                   headers=hdr | {"x-slack-signature": sig(body, ts)})
    assert good.status_code != 401  # past auth; finding 999999 doesn't exist


def test_bare_postgres_url_names_the_installed_driver():
    from echolens.db.session import _with_driver
    assert _with_driver("postgresql://u:p@h:6543/db") == "postgresql+psycopg2://u:p@h:6543/db"
    assert _with_driver("postgres://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"
    assert _with_driver("postgresql+psycopg2://u@h/db") == "postgresql+psycopg2://u@h/db"
    assert _with_driver("sqlite://") == "sqlite://"
