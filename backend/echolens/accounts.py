"""Accounts that work without the operator: reset links, invites, password
changes, the team list, and access requests.

Before this, a forgotten password meant editing the database by hand, and the
only way onto the team was an admin typing a password for someone else.

Links are single-use and expire. Only a token's SHA-256 is stored, so reading
the database does not yield a working link. Setting a password bumps the
user's session version, which ends every existing session for that account
(see auth.principal_for).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from echolens.auth import ROLES, SSO_ONLY, hash_password, password_problem, verify_password
from echolens.config import settings
from echolens.db.models import AccessRequest, Comment, Mention, PasswordReset, ReviewRequest, User

RESET_TTL = timedelta(hours=1)
INVITE_TTL = timedelta(days=3)
# An invited account has no password until its link is used. Like SSO_ONLY,
# it is not a bcrypt hash, so it can never match a password at sign-in.
INVITED = "!invited"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _naive(at: datetime) -> datetime:
    """SQLite returns naive datetimes and Postgres aware ones; compare as UTC."""
    return at.astimezone(timezone.utc).replace(tzinfo=None) if at.tzinfo else at


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def link_for(token: str) -> str:
    """The page that redeems a token. Relative when APP_BASE_URL is unset, so
    an admin copying it from the UI still gets a working path on this site."""
    return f"{settings.app_base_url.rstrip('/')}/reset-password?token={token}"


def sign_in_method(user: User) -> str:
    if user.password_hash == SSO_ONLY:
        return "google"
    if user.password_hash == INVITED:
        return "invited"
    return "password"


def issue_link(session: Session, user: User, purpose: str = "reset",
               created_by_id: int | None = None) -> str:
    """A fresh single-use link. Earlier unused links for the user stop working,
    so only the newest one sent is ever valid."""
    session.execute(update(PasswordReset)
                    .where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
                    .values(used_at=_now()))
    token = secrets.token_urlsafe(32)
    session.add(PasswordReset(
        user_id=user.id, token_hash=_digest(token), purpose=purpose,
        expires_at=_now() + (INVITE_TTL if purpose == "invite" else RESET_TTL),
        created_by_id=created_by_id))
    session.flush()
    return token


def set_password(user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    user.session_version = (user.session_version or 0) + 1


def redeem_link(session: Session, token: str, password: str) -> User:
    """Set the password behind a link. ValueError carries the reason to show."""
    row = session.scalars(select(PasswordReset).where(
        PasswordReset.token_hash == _digest(token or ""))).first()
    if row is None or row.used_at is not None:
        raise ValueError("This link has already been used or replaced by a newer one. Ask for a new link.")
    if _naive(row.expires_at) < _naive(_now()):
        raise ValueError("This link has expired. Ask for a new one.")
    problem = password_problem(password)
    if problem:
        raise ValueError(problem[0].upper() + problem[1:] + ".")
    user = session.get(User, row.user_id)
    if user is None:
        raise ValueError("This account no longer exists.")
    set_password(user, password)
    row.used_at = _now()
    session.flush()
    return user


def change_password(user: User, current: str, new: str) -> None:
    if user.password_hash == SSO_ONLY:
        raise ValueError("You sign in with Google, so there is no EchoLens password to change.")
    if not verify_password(current or "", user.password_hash):
        raise ValueError("Your current password isn't right.")
    problem = password_problem(new)
    if problem:
        raise ValueError(problem[0].upper() + problem[1:] + ".")
    set_password(user, new)


def _admins(session: Session) -> int:
    return session.scalar(select(func.count(User.id)).where(User.role == "admin")) or 0


def team(session: Session, me_id: int | None) -> dict:
    users = session.scalars(select(User).order_by(User.created_at, User.id)).all()
    requests = session.scalars(select(AccessRequest).order_by(AccessRequest.created_at.desc())).all()
    return {
        "users": [{"id": u.id, "email": u.email, "role": u.role, "sign_in": sign_in_method(u),
                   "created_at": u.created_at.isoformat() if u.created_at else None,
                   "you": u.id == me_id} for u in users],
        "access_requests": [{"id": r.id, "email": r.email, "app": r.app, "note": r.note,
                             "created_at": r.created_at.isoformat() if r.created_at else None}
                            for r in requests],
    }


def invite(session: Session, email: str, role: str, created_by_id: int | None) -> tuple[User, str]:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 256:
        raise ValueError("Enter a valid email address.")
    if role not in ROLES:
        raise ValueError(f"Role must be one of {', '.join(ROLES)}.")
    if session.scalars(select(User).where(func.lower(User.email) == email)).first():
        raise ValueError("Someone with that email is already on the team.")
    user = User(email=email, password_hash=INVITED, role=role)
    session.add(user)
    session.flush()
    token = issue_link(session, user, "invite", created_by_id)
    # Whoever was invited no longer needs their access request.
    session.execute(delete(AccessRequest).where(func.lower(AccessRequest.email) == email))
    return user, token


def set_role(session: Session, actor_id: int | None, user_id: int, role: str) -> User:
    if role not in ROLES:
        raise ValueError(f"Role must be one of {', '.join(ROLES)}.")
    user = session.get(User, user_id)
    if user is None:
        raise LookupError("no such user")
    if user.role == "admin" and role != "admin" and _admins(session) <= 1:
        raise ValueError("This is the only admin. Make someone else an admin first.")
    user.role = role
    session.flush()
    return user


def remove(session: Session, actor_id: int | None, user_id: int) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise LookupError("no such user")
    if user.id == actor_id:
        raise ValueError("You can't remove yourself. Ask another admin.")
    if user.role == "admin" and _admins(session) <= 1:
        raise ValueError("This is the only admin. Make someone else an admin first.")
    # Their words stay in discussions, attributed to "a removed user"; what was
    # only addressed to them goes. Nothing is left pointing at a missing row.
    session.execute(update(Comment).where(Comment.user_id == user.id).values(user_id=None))
    session.execute(delete(Mention).where(Mention.user_id == user.id))
    session.execute(update(ReviewRequest).where(ReviewRequest.requested_by_id == user.id)
                    .values(requested_by_id=None))
    session.execute(update(ReviewRequest).where(ReviewRequest.requested_of_id == user.id)
                    .values(requested_of_id=None))
    session.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    session.delete(user)
    session.flush()


def request_access(session: Session, email: str, app: str, note: str) -> bool:
    """Record a request. Returns False for a repeat, which is not an error to
    the visitor: asking twice should not reveal anything or fail."""
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 256:
        raise ValueError("Enter a valid email address.")
    if session.scalars(select(AccessRequest).where(func.lower(AccessRequest.email) == email)).first():
        return False
    session.add(AccessRequest(email=email, app=(app or "").strip()[:256], note=(note or "").strip()[:2000]))
    session.flush()
    return True


def dismiss_request(session: Session, request_id: int) -> None:
    session.execute(delete(AccessRequest).where(AccessRequest.id == request_id))


def email_link(to: str, token: str, purpose: str) -> bool:
    """Send a reset or invite link. False when this deployment has no email."""
    from echolens.notify import _send_email, email_configured
    if not email_configured():
        return False
    link = link_for(token)
    if purpose == "invite":
        subject = "You're invited to EchoLens"
        body = (f"You've been added to an EchoLens workspace.\n\nSet your password here (the link works "
                f"once and expires in {INVITE_TTL.days} days):\n{link}\n")
    else:
        subject = "Reset your EchoLens password"
        body = (f"Someone asked to reset the password for this address.\n\nChoose a new one here (the link "
                f"works once and expires in {int(RESET_TTL.total_seconds() // 3600)} hour):\n{link}\n\n"
                f"If that wasn't you, ignore this email; your password stays the same.\n")
    try:
        return _send_email(subject, body, to=to)
    except Exception as err:  # noqa: BLE001 — the caller says what to do instead
        from echolens.logging import get_logger
        get_logger("accounts").error("account_email_failed", purpose=purpose, error=str(err))
        return False
