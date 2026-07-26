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

# The principal for an unauthenticated visitor when ALLOW_GUEST is on.
#
# `viewer` on purpose, and never anything higher. A guest can read every screen
# but cannot reach a single endpoint guarded by require_role("reviewer") or
# ("admin") — which is every endpoint that spends OpenAI credits, mutates a
# case, connects a source, or deletes a product. `id: None` because no row in
# `users` backs this principal; anything that writes an author id must not
# silently attribute it to user 0.
GUEST = {"id": None, "email": None, "role": "viewer", "guest": True}


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


# Marker stored in `password_hash` for accounts that authenticate via Google.
# It is not a bcrypt hash, so verify_password can never match it and the
# password endpoint cannot be used to sign in as a Google user. `password_hash`
# is NOT NULL, hence a sentinel rather than a null.
SSO_ONLY = "!sso-google"


def upsert_google_user(session, email: str, role: str) -> User:
    """Find or create the local user behind a verified Google account.

    An existing password account with the same address is linked, not
    duplicated or overwritten: the email came from a verified Google claim, so
    it is the same person, and clobbering their stored hash would silently
    disable their password login.
    """
    user = session.scalars(select(User).where(User.email == email)).first()
    if user:
        # Only ever raise a role, never lower it: an admin who signs in with
        # Google while not on the allowlist must not be demoted to reviewer.
        if _RANK.get(role, 0) > _RANK.get(user.role, 0):
            user.role = role
            session.flush()
        return user
    user = User(email=email, password_hash=SSO_ONLY, role=role)
    session.add(user)
    session.flush()
    return user


# ── FastAPI dependencies ────────────────────────────────────────────────

def current_user(request: Request) -> dict:
    """Return the authenticated principal.

    Three ways to arrive here without a token:
      - dev mode           -> synthetic ADMIN (local development only)
      - ALLOW_GUEST on     -> read-only GUEST (public demo)
      - neither            -> 401

    A malformed or expired token is always a 401, even with guests allowed: a
    token that fails to verify is a broken session to be re-authenticated, not
    an anonymous visitor, and silently downgrading it would hide expiry from
    the user and make a tampered token look like a successful anonymous call.
    """
    if not settings.auth_required:
        return DEV_ADMIN
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        if settings.allow_guest:
            return dict(GUEST)
        raise HTTPException(401, "missing bearer token")
    try:
        payload = decode_token(auth.split(" ", 1)[1])
        # int(payload["sub"]) sat OUTSIDE this try, so a correctly-signed token
        # carrying sub="abc" raised ValueError and a token with no sub raised
        # KeyError — neither is a JWTError, so both escaped as an unhandled 500
        # with a stack trace instead of a clean 401.
        uid = int(payload["sub"])
    except (JWTError, KeyError, ValueError, TypeError, AttributeError):
        raise HTTPException(401, "invalid or expired token")
    return {"id": uid, "email": payload.get("email"), "role": payload.get("role", "viewer")}


def require_role(minimum: str):
    """Dependency factory: require at least `minimum` role."""
    def dep(user: dict = Depends(current_user)) -> dict:
        if _RANK.get(user["role"], -1) < _RANK[minimum]:
            raise HTTPException(403, f"requires {minimum} role or higher")
        return user
    return dep
