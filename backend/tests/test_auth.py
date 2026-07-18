"""Auth & RBAC: password hashing, JWT, role hierarchy, and dev-mode bypass."""
from __future__ import annotations

import pytest
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


def test_password_hash_roundtrip():
    h = auth.hash_password("hunter2")
    assert h != "hunter2"
    assert auth.verify_password("hunter2", h)
    assert not auth.verify_password("wrong", h)


def test_create_user_and_authenticate(db):
    auth.create_user(db, "pm@team.com", "pw", "reviewer")
    assert auth.authenticate(db, "pm@team.com", "pw").role == "reviewer"
    assert auth.authenticate(db, "pm@team.com", "nope") is None
    with pytest.raises(ValueError):
        auth.create_user(db, "pm@team.com", "pw2")  # duplicate email


def test_jwt_encode_decode(db):
    u = auth.create_user(db, "a@b.com", "pw", "admin")
    payload = auth.decode_token(auth.create_token(u))
    assert payload["role"] == "admin" and payload["email"] == "a@b.com"


def test_role_hierarchy():
    from fastapi import HTTPException
    admin = {"id": 1, "email": "a", "role": "admin"}
    viewer = {"id": 2, "email": "v", "role": "viewer"}
    dep = auth.require_role("reviewer")
    assert dep(admin) is admin              # admin satisfies reviewer
    with pytest.raises(HTTPException):
        dep(viewer)                          # viewer does not


def test_dev_mode_bypasses_auth(monkeypatch):
    monkeypatch.setattr(settings, "echolens_env", "dev")
    from starlette.requests import Request
    req = Request({"type": "http", "headers": []})
    user = auth.current_user(req)
    assert user["role"] == "admin"  # dev mode → synthetic admin, no token needed


def test_prod_mode_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "echolens_env", "production")
    from fastapi import HTTPException
    from starlette.requests import Request
    req = Request({"type": "http", "headers": []})
    with pytest.raises(HTTPException):
        auth.current_user(req)
