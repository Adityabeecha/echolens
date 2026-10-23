"""Auth & RBAC (v1.0). JWT bearer tokens, bcrypt passwords, three roles.

In `dev` mode (`ECHOLENS_ENV=dev`, the default) auth is OFF — every request is
treated as an admin so local development and the existing tests need no tokens.
Set `ECHOLENS_ENV=staging|production` to require real logins.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request
import jwt
from jwt import PyJWTError as JWTError
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

MIN_PASSWORD_LENGTH = 10


def password_problem(password: str) -> str | None:
    """Why this password is unacceptable for a NEW account, or None.

    Enforced at the account-creation surfaces (signup, the CLI, bootstrap),
    not inside create_user, so fixtures can still make throwaway users."""
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"password must be at least {MIN_PASSWORD_LENGTH} characters"
    if (password or "").strip().lower() in {"password123", "1234567890", "qwertyuiop", "echolens123"}:
        return "that password is too common"
    return None


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


# ── browser session cookie + CSRF ───────────────────────────────────────
#
# The browser keeps its session in an HttpOnly cookie, so script on the page
# (an XSS payload, a compromised dependency) cannot read the JWT the way it
# could from localStorage. Automation keeps sending `Authorization: Bearer`.
#
# A cookie is sent by the browser on its own, so a cookie-authenticated write
# also needs proof that it came from our frontend: the double-submit token. A
# second, script-readable cookie holds a random value that the SPA echoes in
# X-CSRF-Token. Another site can make the browser SEND both cookies but cannot
# READ either one, so it cannot produce the matching header. The value is also
# returned in the login response body, because a frontend on another origin
# cannot read a cookie set by the API's origin through document.cookie.

SESSION_COOKIE = "echolens_session"
CSRF_COOKIE = "echolens_csrf"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _cookie_kwargs() -> dict:
    samesite = settings.session_cookie_samesite.lower()
    kw = {"secure": settings.session_cookie_secure or samesite == "none",
          "samesite": samesite if samesite in ("lax", "strict", "none") else "lax",
          "path": "/"}
    if settings.session_cookie_domain:
        kw["domain"] = settings.session_cookie_domain
    return kw


def new_csrf_token() -> str:
    import secrets
    return secrets.token_urlsafe(32)


def set_session_cookies(response, token: str, csrf: str | None = None) -> str:
    """Attach the session + CSRF cookies to `response`; returns the CSRF value."""
    csrf = csrf or new_csrf_token()
    max_age = settings.jwt_expire_minutes * 60
    kw = _cookie_kwargs()
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, **kw)
    # Not HttpOnly by design: same-origin deployments may read it from
    # document.cookie. It authorises nothing on its own.
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, **kw)
    return csrf


def clear_session_cookies(response) -> None:
    kw = _cookie_kwargs()
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path=kw["path"], domain=kw.get("domain"),
                               secure=kw["secure"], samesite=kw["samesite"],
                               httponly=name == SESSION_COOKIE)


def session_token(request: Request) -> tuple[str | None, bool]:
    """(raw JWT, came_from_cookie). A Bearer header wins over the cookie, so
    automation and tests are unaffected by whatever cookie a client holds."""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header.split(" ", 1)[1], False
    cookie = (getattr(request, "cookies", None) or {}).get(SESSION_COOKIE)
    return (cookie, True) if cookie else (None, False)


def check_csrf(request: Request) -> None:
    """403 a cookie-authenticated state-changing request without the token."""
    import hmac
    if request.method.upper() in _SAFE_METHODS:
        return
    sent = request.headers.get(CSRF_HEADER, "")
    expected = request.cookies.get(CSRF_COOKIE, "")
    if not sent or not expected or not hmac.compare_digest(sent, expected):
        raise HTTPException(403, "missing or invalid CSRF token")


# ── FastAPI dependencies ────────────────────────────────────────────────

def current_user(request: Request) -> dict:
    """Return the authenticated principal.

    The token is a Bearer header (automation) or the HttpOnly session cookie
    (the browser); a cookie-authenticated write must also pass check_csrf.

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
    raw, via_cookie = session_token(request)
    if raw is None:
        if settings.allow_guest:
            return dict(GUEST)
        raise HTTPException(401, "missing bearer token")
    if via_cookie:
        check_csrf(request)
    return principal_from_token(raw)


def principal_from_token(raw: str) -> dict:
    """Verify a JWT and resolve the principal behind it (401 on any failure)."""
    try:
        payload = decode_token(raw)
        # int(payload["sub"]) sat OUTSIDE this try, so a correctly-signed token
        # carrying sub="abc" raised ValueError and a token with no sub raised
        # KeyError — neither is a JWTError, so both escaped as an unhandled 500
        # with a stack trace instead of a clean 401.
        uid = int(payload["sub"])
    except (JWTError, KeyError, ValueError, TypeError, AttributeError):
        raise HTTPException(401, "invalid or expired token")
    return principal_for(uid, payload)


def principal_for(uid: int, payload: dict) -> dict:
    """The caller's CURRENT role, from the database.

    The role used to come from the token claim, so a user who was demoted or
    deleted kept their old powers until the token expired (24h by default).
    One indexed lookup per request is the price of revocation that works."""
    from echolens.db.session import session_scope
    with session_scope() as session:
        user = session.get(User, uid)
        if user is None:
            raise HTTPException(401, "account no longer exists")
        return {"id": user.id, "email": user.email, "role": user.role}


def require_role(minimum: str):
    """Dependency factory: require at least `minimum` role."""
    def dep(user: dict = Depends(current_user)) -> dict:
        if _RANK.get(user["role"], -1) < _RANK[minimum]:
            raise HTTPException(403, f"requires {minimum} role or higher")
        return user
    return dep
