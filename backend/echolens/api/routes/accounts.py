"""Accounts: reset and invite links, password change, the team list, and
access requests (Phase 3). Logic lives in echolens/accounts.py; these are the
HTTP edges."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from echolens.api.ratelimit import limiter
from echolens.auth import create_token, current_user, require_role, set_session_cookies
from echolens.db.session import session_scope

router = APIRouter()

class ResetRequestBody(BaseModel):
    email: str = Field(max_length=256)


class ResetConfirmBody(BaseModel):
    token: str = Field(max_length=256)
    password: str = Field(max_length=256)


class PasswordChangeBody(BaseModel):
    current_password: str = Field("", max_length=256)
    new_password: str = Field(max_length=256)


class InviteBody(BaseModel):
    email: str = Field(max_length=256)
    role: str = "viewer"


class RoleBody(BaseModel):
    role: str


class AccessRequestBody(BaseModel):
    email: str = Field(max_length=256)
    app: str = Field("", max_length=256)
    note: str = Field("", max_length=2000)


def _send_later(fn, *args) -> None:
    """Mail goes out off the request path: SMTP is slow, and a response that
    takes longer when an address exists would reveal which addresses do."""
    threading.Thread(target=fn, args=args, daemon=True, name="echolens-mail").start()


@router.post("/auth/password-reset")
@limiter.limit("5/minute")
def password_reset_request(body: ResetRequestBody, request: Request) -> dict:
    """Email a reset link. The answer is the same whether or not the address
    has an account, so this can't be used to discover who is on the team."""
    from echolens import accounts
    from echolens.auth import SSO_ONLY
    from echolens.db.models import User
    from echolens.notify import email_configured
    if not email_configured():
        return {"sent": False, "message": "Password reset emails aren't set up on this workspace. "
                                          "Ask your workspace admin for a reset link."}
    target: tuple[str, str] | None = None
    with session_scope() as session:
        user = session.scalars(select(User).where(
            func.lower(User.email) == body.email.strip().lower())).first()
        if user is not None and user.password_hash != SSO_ONLY:
            target = (user.email, accounts.issue_link(session, user, "reset"))
    if target:
        _send_later(accounts.email_link, target[0], target[1], "reset")
    return {"sent": True, "message": "If that address has an EchoLens password, a reset link is on its way. "
                                     "It works once, for one hour."}


@router.post("/auth/password-reset/confirm")
@limiter.limit("10/minute")
def password_reset_confirm(body: ResetConfirmBody, request: Request, response: Response) -> dict:
    """Set a new password from a reset or invite link, then sign in with it.
    Every other session for the account ends."""
    from echolens import accounts
    with session_scope() as session:
        try:
            user = accounts.redeem_link(session, body.token, body.password)
        except ValueError as err:
            raise HTTPException(422, str(err))
        token, role = create_token(user), user.role
    return {"role": role, "csrf_token": set_session_cookies(response, token)}


@router.post("/auth/password")
@limiter.limit("10/minute")
def password_change(body: PasswordChangeBody, request: Request, response: Response,
                    user: dict = Depends(current_user)) -> dict:
    """Change your own password. Other sessions end; this one continues."""
    from echolens import accounts
    from echolens.db.models import User
    if user.get("guest") or not user.get("id"):
        raise HTTPException(403, "Sign in to your own account to change its password.")
    with session_scope() as session:
        row = session.get(User, user["id"])
        if row is None:
            raise HTTPException(404, "account not found")
        try:
            accounts.change_password(row, body.current_password, body.new_password)
        except ValueError as err:
            raise HTTPException(422, str(err))
        session.flush()
        token = create_token(row)
    return {"ok": True, "csrf_token": set_session_cookies(response, token)}


@router.get("/users")
def users_list(user: dict = Depends(require_role("admin"))) -> dict:
    from echolens.accounts import team
    from echolens.notify import email_configured
    with session_scope() as session:
        return {**team(session, user.get("id")), "email_enabled": email_configured()}


@router.post("/users")
def users_invite(body: InviteBody, user: dict = Depends(require_role("admin"))) -> dict:
    """Add someone. They get a link to set their own password; the admin never
    chooses or sees it. The link is returned too, to send by hand."""
    from echolens import accounts
    with session_scope() as session:
        try:
            invited, token = accounts.invite(session, body.email, body.role, user.get("id"))
        except ValueError as err:
            raise HTTPException(422, str(err))
        out = {"id": invited.id, "email": invited.email, "role": invited.role}
    emailed = accounts.email_link(out["email"], token, "invite")
    return {**out, "link": accounts.link_for(token), "emailed": emailed}


@router.patch("/users/{user_id}")
def users_set_role(user_id: int, body: RoleBody, user: dict = Depends(require_role("admin"))) -> dict:
    from echolens import accounts
    with session_scope() as session:
        try:
            row = accounts.set_role(session, user.get("id"), user_id, body.role)
        except LookupError:
            raise HTTPException(404, "no such user")
        except ValueError as err:
            raise HTTPException(422, str(err))
        return {"id": row.id, "role": row.role}


@router.delete("/users/{user_id}")
def users_remove(user_id: int, user: dict = Depends(require_role("admin"))) -> dict:
    from echolens import accounts
    with session_scope() as session:
        try:
            accounts.remove(session, user.get("id"), user_id)
        except LookupError:
            raise HTTPException(404, "no such user")
        except ValueError as err:
            raise HTTPException(422, str(err))
    return {"removed": user_id}


@router.post("/users/{user_id}/reset-link")
def users_reset_link(user_id: int, user: dict = Depends(require_role("admin"))) -> dict:
    """A fresh reset link for someone locked out, to send them by hand. Their
    earlier links stop working."""
    from echolens import accounts
    from echolens.auth import SSO_ONLY
    from echolens.db.models import User
    with session_scope() as session:
        row = session.get(User, user_id)
        if row is None:
            raise HTTPException(404, "no such user")
        if row.password_hash == SSO_ONLY:
            raise HTTPException(422, "This person signs in with Google, so there is no password to reset.")
        purpose = "invite" if row.password_hash == accounts.INVITED else "reset"
        token, email = accounts.issue_link(session, row, purpose, user.get("id")), row.email
    return {"link": accounts.link_for(token), "email": email, "purpose": purpose}


@router.post("/access-requests")
@limiter.limit("3/minute")
def access_request(body: AccessRequestBody, request: Request) -> dict:
    """"Request access" from the sign-in screen, for people without an account."""
    from echolens import accounts
    from echolens.notify import _send_email
    with session_scope() as session:
        try:
            new = accounts.request_access(session, body.email, body.app, body.note)
        except ValueError as err:
            raise HTTPException(422, str(err))
    if new:
        _send_later(_send_email, "EchoLens access request",
                    f"{body.email.strip()} asked for access"
                    f"{f' for {body.app.strip()}' if body.app.strip() else ''}.\n\n{body.note.strip()}\n\n"
                    "Add them from Settings → Team.")
    return {"ok": True, "message": "Thanks. We'll email you when your account is ready."}


@router.delete("/access-requests/{request_id}")
def access_request_dismiss(request_id: int, user: dict = Depends(require_role("admin"))) -> dict:
    from echolens.accounts import dismiss_request
    with session_scope() as session:
        dismiss_request(session, request_id)
    return {"dismissed": request_id}


