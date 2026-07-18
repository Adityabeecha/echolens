"""Auth & RBAC (v1.0). JWT bearer tokens, bcrypt passwords, three roles.

In `dev` mode (`ECHOLENS_ENV=dev`, the default) auth is OFF — every request is
treated as an admin so local development and the existing tests need no tokens.
Set `ECHOLENS_ENV=staging|production` to require real logins.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy import select

from echolens.config import settings
from echolens.db.models import User

ROLES = ("admin", "reviewer", "viewer")
# who may do what — higher roles inherit lower privileges
_RANK = {"viewer": 0, "reviewer": 1, "admin": 2}

DEV_ADMIN = {"id": 0, "email": "dev@localhost", "role": "admin"}


# ── password + token helpers ────────────────────────────────────────────

def hash_password(pw: str) -> str:
    # bcrypt caps at 72 bytes; truncate defensively (standard practice).
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user.id), "email": user.email, "role": user.role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# ── user management ─────────────────────────────────────────────────────

def create_user(session, email: str, password: str, role: str = "viewer") -> User:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if session.scalars(select(User).where(User.email == email)).first():
        raise ValueError("email already registered")
    user = User(email=email, password_hash=hash_password(password), role=role)
    session.add(user)
    session.flush()
    return user


def authenticate(session, email: str, password: str) -> User | None:
    user = session.scalars(select(User).where(User.email == email)).first()
    if user and verify_password(password, user.password_hash):
        return user
    return None


# ── FastAPI dependencies ────────────────────────────────────────────────

def current_user(request: Request) -> dict:
    """Return the authenticated principal. In dev mode, a synthetic admin."""
    if not settings.auth_required:
        return DEV_ADMIN
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        payload = decode_token(auth.split(" ", 1)[1])
    except JWTError:
        raise HTTPException(401, "invalid or expired token")
    return {"id": int(payload["sub"]), "email": payload.get("email"), "role": payload.get("role", "viewer")}


def require_role(minimum: str):
    """Dependency factory: require at least `minimum` role."""
    def dep(user: dict = Depends(current_user)) -> dict:
        if _RANK.get(user["role"], -1) < _RANK[minimum]:
            raise HTTPException(403, f"requires {minimum} role or higher")
        return user
    return dep
