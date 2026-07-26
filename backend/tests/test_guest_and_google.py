"""Public-demo mode: read-only guests, and Google sign-in.

The whole point of guest mode is that an anonymous visitor can READ everything
and CHANGE nothing. These tests pin that boundary, because the failure mode is
silent and expensive: a guest promoted to admin on a public URL can spend the
deployment's OpenAI credits and delete its data.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from echolens import auth
from echolens.config import settings
from echolens.db.models import Base, User


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, expire_on_commit=False)()


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


@pytest.fixture()
def prod(monkeypatch):
    """Real auth, i.e. not the dev bypass."""
    monkeypatch.setattr(settings, "echolens_env", "production")
    return monkeypatch


# ── guest admission ────────────────────────────────────────────────────

def test_no_token_is_rejected_when_guests_are_off(prod):
    prod.setattr(settings, "allow_guest", False)
    with pytest.raises(HTTPException) as e:
        auth.current_user(FakeRequest())
    assert e.value.status_code == 401


def test_no_token_becomes_a_viewer_when_guests_are_on(prod):
    prod.setattr(settings, "allow_guest", True)
    user = auth.current_user(FakeRequest())
    assert user["role"] == "viewer"
    assert user["guest"] is True
    # No users row backs a guest; attributing writes to id 0 would be a lie.
    assert user["id"] is None


def test_guest_can_read_but_cannot_review_or_admin(prod):
    """The actual security boundary: every endpoint that spends money or
    mutates state is behind require_role('reviewer') or ('admin')."""
    prod.setattr(settings, "allow_guest", True)
    guest = auth.current_user(FakeRequest())

    # viewer-level dependency admits the guest
    assert auth.require_role("viewer")(user=guest) is guest

    for level in ("reviewer", "admin"):
        with pytest.raises(HTTPException) as e:
            auth.require_role(level)(user=guest)
        assert e.value.status_code == 403


def test_guest_mode_never_grants_admin(prod):
    """Guard against the obvious regression: reusing the dev bypass (which
    returns a full ADMIN) for the public demo path."""
    prod.setattr(settings, "allow_guest", True)
    assert auth.current_user(FakeRequest())["role"] != "admin"
    assert auth.GUEST["role"] == "viewer"


def test_a_bad_token_is_401_even_with_guests_on(prod):
    """A token that fails to verify is a broken session, not an anonymous
    visitor. Downgrading it to guest would hide expiry from the user and make a
    tampered token look like a successful anonymous call."""
    prod.setattr(settings, "allow_guest", True)
    with pytest.raises(HTTPException) as e:
        auth.current_user(FakeRequest({"Authorization": "Bearer not-a-real-token"}))
    assert e.value.status_code == 401


def test_guest_dict_is_copied_not_shared(prod):
    """current_user returns a fresh dict; a caller mutating it must not change
    the role every later guest receives."""
    prod.setattr(settings, "allow_guest", True)
    first = auth.current_user(FakeRequest())
    first["role"] = "admin"
    assert auth.current_user(FakeRequest())["role"] == "viewer"


# ── Google account mapping ─────────────────────────────────────────────

def test_google_user_is_created_with_the_configured_role(db):
    u = auth.upsert_google_user(db, "someone@gmail.com", "reviewer")
    assert u.email == "someone@gmail.com"
    assert u.role == "reviewer"
    assert u.id is not None


def test_google_user_cannot_be_password_logged_in(db):
    """The stored marker is not a bcrypt hash, so the password endpoint can
    never authenticate an SSO-only account."""
    auth.upsert_google_user(db, "sso@gmail.com", "reviewer")
    assert auth.authenticate(db, "sso@gmail.com", "") is None
    assert auth.authenticate(db, "sso@gmail.com", auth.SSO_ONLY) is None
    assert auth.authenticate(db, "sso@gmail.com", "password") is None


def test_signing_in_twice_reuses_one_row(db):
    a = auth.upsert_google_user(db, "dup@gmail.com", "reviewer")
    b = auth.upsert_google_user(db, "dup@gmail.com", "reviewer")
    assert a.id == b.id
    assert db.query(User).filter_by(email="dup@gmail.com").count() == 1


def test_google_sign_in_never_demotes_an_admin(db):
    """An admin who is not on the Google allowlist signs in and stays admin."""
    auth.create_user(db, "boss@team.com", "pw", "admin")
    u = auth.upsert_google_user(db, "boss@team.com", "reviewer")
    assert u.role == "admin"


def test_google_sign_in_can_promote(db):
    auth.create_user(db, "quiet@team.com", "pw", "viewer")
    u = auth.upsert_google_user(db, "quiet@team.com", "admin")
    assert u.role == "admin"


def test_linking_google_keeps_an_existing_password(db):
    """Signing in with Google must not clobber the stored hash and silently
    disable the user's existing password login."""
    auth.create_user(db, "both@team.com", "hunter2", "reviewer")
    auth.upsert_google_user(db, "both@team.com", "reviewer")
    assert auth.authenticate(db, "both@team.com", "hunter2") is not None


def test_admin_allowlist_is_case_insensitive(monkeypatch):
    from echolens import google_auth
    monkeypatch.setattr(settings, "google_admin_emails", "Owner@Gmail.com")
    monkeypatch.setattr(settings, "google_default_role", "reviewer")
    assert google_auth.role_for("owner@gmail.com") == "admin"
    assert google_auth.role_for("OWNER@GMAIL.COM") == "admin"
    assert google_auth.role_for("someone.else@gmail.com") == "reviewer"


# ── Google token verification ──────────────────────────────────────────

def test_verification_refuses_when_unconfigured(monkeypatch):
    from echolens import google_auth
    monkeypatch.setattr(settings, "google_client_id", "")
    with pytest.raises(google_auth.GoogleAuthError):
        google_auth.verify_id_token("anything")


def test_verification_rejects_garbage(monkeypatch):
    """An unsigned/!JWT string must never authenticate. This is the attack:
    the credential is attacker-supplied, and decoding without verifying would
    let anyone log in as anyone by editing the payload."""
    from echolens import google_auth
    monkeypatch.setattr(settings, "google_client_id", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(google_auth, "_keys", lambda force=False: {"keys": []})
    for bad in ("", "not-a-jwt", "a.b.c", "null"):
        with pytest.raises(google_auth.GoogleAuthError):
            google_auth.verify_id_token(bad)


def test_verification_rejects_a_self_signed_token(monkeypatch):
    """A token we sign ourselves with a symmetric key is structurally valid
    but not from Google, so it must be refused."""
    from jose import jwt as jose_jwt
    from echolens import google_auth
    monkeypatch.setattr(settings, "google_client_id", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(google_auth, "_keys", lambda force=False: {"keys": []})
    forged = jose_jwt.encode(
        {"email": "attacker@evil.com", "email_verified": True,
         "iss": "https://accounts.google.com",
         "aud": "test-client-id.apps.googleusercontent.com"},
        "attacker-key", algorithm="HS256")
    with pytest.raises(google_auth.GoogleAuthError):
        google_auth.verify_id_token(forged)
