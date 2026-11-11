"""Phase 3: accounts that work without the operator editing the database."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens import accounts, auth
from echolens.config import settings
from echolens.db.models import (
    AccessRequest, Base, Comment, Investigation, PasswordReset, Product, User,
)

PASSWORD = "correct-horse-battery-9"
NEW_PASSWORD = "another-long-phrase-42"


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setattr(settings, "echolens_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-" + "x" * 32)
    monkeypatch.setattr(settings, "session_cookie_samesite", "lax")
    monkeypatch.setattr(settings, "session_cookie_secure", True)
    monkeypatch.setattr(settings, "smtp_host", "")
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", eng)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: eng)
    with Session() as s:
        auth.create_user(s, "admin@team.com", PASSWORD, "admin")
        auth.create_user(s, "rev@team.com", PASSWORD, "reviewer")
        s.add(Product(name="app", is_demo=True))
        s.commit()
    from echolens.api.app import app
    app.state.limiter.reset()
    return Session, (lambda: TestClient(app, base_url="https://testserver"))


def _login(client, email="admin@team.com", password=PASSWORD):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.headers[auth.CSRF_HEADER] = r.json()["csrf_token"]
    return r


def _uid(Session, email):
    with Session() as s:
        return s.scalars(select(User).where(User.email == email)).one().id


def test_invite_sets_up_an_account_the_admin_never_sees_the_password_of(env):
    Session, client = env
    admin = client()
    _login(admin)
    r = admin.post("/users", json={"email": "New@Team.com", "role": "reviewer"})
    assert r.status_code == 200, r.text
    assert r.json()["emailed"] is False and "/reset-password?token=" in r.json()["link"]
    token = r.json()["link"].split("token=")[1]
    # The invitee cannot sign in until they choose a password.
    assert client().post("/auth/login", json={"email": "new@team.com", "password": "!invited"}).status_code == 401
    invitee = client()
    r = invitee.post("/auth/password-reset/confirm", json={"token": token, "password": NEW_PASSWORD})
    assert r.status_code == 200 and r.json()["role"] == "reviewer"
    assert invitee.get("/auth/me").json()["email"] == "new@team.com"
    # Single use.
    again = client().post("/auth/password-reset/confirm", json={"token": token, "password": NEW_PASSWORD})
    assert again.status_code == 422 and "already been used" in again.json()["detail"]
    listed = {u["email"]: u for u in admin.get("/users").json()["users"]}
    assert listed["new@team.com"]["sign_in"] == "password"


def test_a_reset_ends_every_other_session(env):
    Session, client = env
    old = client()
    _login(old, "rev@team.com")
    assert old.get("/auth/me").status_code == 200
    admin = client()
    _login(admin)
    link = admin.post(f"/users/{_uid(Session, 'rev@team.com')}/reset-link").json()["link"]
    fresh = client()
    assert fresh.post("/auth/password-reset/confirm",
                      json={"token": link.split("token=")[1], "password": NEW_PASSWORD}).status_code == 200
    assert old.get("/auth/me").status_code == 401          # the stolen-token case
    assert fresh.get("/auth/me").status_code == 200
    _login(client(), "rev@team.com", NEW_PASSWORD)


def test_only_the_newest_link_works_and_links_expire(env):
    Session, _ = env
    with Session() as s:
        user = s.scalars(select(User).where(User.email == "rev@team.com")).one()
        first = accounts.issue_link(s, user)
        second = accounts.issue_link(s, user)
        with pytest.raises(ValueError, match="already been used or replaced"):
            accounts.redeem_link(s, first, NEW_PASSWORD)
        row = s.scalars(select(PasswordReset).where(PasswordReset.used_at.is_(None))).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        with pytest.raises(ValueError, match="expired"):
            accounts.redeem_link(s, second, NEW_PASSWORD)
        # Only the hash is stored.
        assert all(len(r.token_hash) == 64 and r.token_hash != second
                   for r in s.scalars(select(PasswordReset)))


def test_change_password_keeps_this_session_and_ends_others(env):
    Session, client = env
    other = client()
    _login(other, "rev@team.com")
    me = client()
    _login(me, "rev@team.com")
    wrong = me.post("/auth/password", json={"current_password": "nope", "new_password": NEW_PASSWORD})
    assert wrong.status_code == 422 and "current password" in wrong.json()["detail"]
    short = me.post("/auth/password", json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 422
    r = me.post("/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 200, r.text
    assert me.get("/auth/me").status_code == 200
    assert other.get("/auth/me").status_code == 401


def test_reset_request_never_reveals_who_has_an_account(env, monkeypatch):
    _, client = env
    c = client()
    off = c.post("/auth/password-reset", json={"email": "rev@team.com"}).json()
    assert off["sent"] is False and "admin" in off["message"]
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "alert_email_from", "echolens@example.com")
    sent = []
    monkeypatch.setattr(accounts, "email_link", lambda to, token, purpose: sent.append(to) or True)
    known = c.post("/auth/password-reset", json={"email": "rev@team.com"}).json()
    unknown = c.post("/auth/password-reset", json={"email": "nobody@team.com"}).json()
    assert known == unknown and known["sent"] is True


def test_roles_and_removal_protect_the_last_admin(env):
    Session, client = env
    admin = client()
    _login(admin)
    me = _uid(Session, "admin@team.com")
    rev = _uid(Session, "rev@team.com")
    assert admin.patch(f"/users/{me}", json={"role": "viewer"}).status_code == 422
    assert admin.delete(f"/users/{me}").status_code == 422
    assert admin.patch(f"/users/{rev}", json={"role": "admin"}).status_code == 200
    assert admin.patch(f"/users/{rev}", json={"role": "boss"}).status_code == 422
    # Reviewers cannot manage the team.
    reviewer = client()
    _login(reviewer, "rev@team.com")
    assert admin.patch(f"/users/{rev}", json={"role": "reviewer"}).status_code == 200
    assert reviewer.get("/users").status_code == 403


def test_removing_someone_keeps_their_comments(env):
    Session, client = env
    rev = _uid(Session, "rev@team.com")
    with Session() as s:
        inv = Investigation(product_id=1, status="resolved")
        s.add(inv)
        s.flush()
        s.add(Comment(investigation_id=inv.id, user_id=rev, body="Looks right to me"))
        s.commit()
    admin = client()
    _login(admin)
    assert admin.delete(f"/users/{rev}").status_code == 200
    with Session() as s:
        assert s.get(User, rev) is None
        comment = s.scalars(select(Comment)).one()
        assert comment.user_id is None and comment.body == "Looks right to me"


def test_access_requests_are_collected_once_and_cleared_by_an_invite(env):
    Session, client = env
    visitor = client()
    r = visitor.post("/access-requests", json={"email": "Pm@Startup.io", "app": "Acme", "note": "We ship weekly"})
    assert r.status_code == 200
    assert visitor.post("/access-requests", json={"email": "pm@startup.io"}).status_code == 200
    assert visitor.post("/access-requests", json={"email": "not-an-email"}).status_code == 422
    admin = client()
    _login(admin)
    reqs = admin.get("/users").json()["access_requests"]
    assert [x["email"] for x in reqs] == ["pm@startup.io"] and reqs[0]["app"] == "Acme"
    admin.post("/users", json={"email": "pm@startup.io", "role": "viewer"})
    assert admin.get("/users").json()["access_requests"] == []
    with Session() as s:
        assert s.scalars(select(AccessRequest)).all() == []
