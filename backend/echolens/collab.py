"""Collaboration (v5.0): comments, @mentions, and review sign-off.

Discussion hangs off the INVESTIGATION rather than the finding, because a
challenged case re-opens as a new investigation with a new finding — anchoring
to the finding would strand the conversation that caused the challenge on the
superseded row.

Nothing here can change a finding's status. approve/challenge remain the only
paths to that, so the evidence guarantees around a conclusion are unaffected by
anything said in a comment thread.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from echolens.db.models import (Comment, Investigation, Mention, ReviewRequest,
                                User)

MAX_COMMENT_CHARS = 4000

# Matches @handle where the handle is the local part of an email (before the @)
# or a full address. Trailing punctuation is excluded so "@ana," resolves.
MENTION_RE = re.compile(r"@([A-Za-z0-9._%+-]+(?:@[A-Za-z0-9.-]+\.[A-Za-z]{2,})?)")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def handle_of(user: User) -> str:
    """The @handle for a user: the local part of their email."""
    return (user.email or "").split("@")[0]


def resolve_mentions(session: Session, body: str) -> list[User]:
    """Users actually named in `body`.

    Resolved against the users table rather than trusted from the text, so an
    @handle nobody owns is dropped instead of becoming a notification pointing
    at nothing. Matching is case-insensitive because people type @Ana for ana@.
    """
    raw = {m.lower() for m in MENTION_RE.findall(body or "")}
    if not raw:
        return []
    found: dict[int, User] = {}
    for user in session.scalars(select(User)).all():
        email = (user.email or "").lower()
        if email in raw or handle_of(user).lower() in raw:
            found[user.id] = user
    return list(found.values())


def add_comment(session: Session, investigation_id: int, body: str,
                user_id: int | None, parent_id: int | None = None) -> Comment:
    """Post a comment and record whoever it mentions.

    `user_id` is required: the GUEST principal carries `id: None` precisely so
    nothing silently attributes its writes to user 0, and an unattributed
    comment on a review thread is worse than no comment.
    """
    text = (body or "").strip()
    if not text:
        raise ValueError("a comment needs a body")
    if len(text) > MAX_COMMENT_CHARS:
        raise ValueError(f"comment is too long (max {MAX_COMMENT_CHARS} characters)")
    if user_id is None:
        raise ValueError("comments must be attributed to a signed-in user")

    inv = session.get(Investigation, investigation_id)
    if inv is None:
        raise ValueError(f"no investigation with id {investigation_id}")

    if parent_id is not None:
        parent = session.get(Comment, parent_id)
        if parent is None or parent.investigation_id != investigation_id:
            raise ValueError("parent comment does not belong to this case")
        # Threads are one level deep; a reply to a reply attaches to the root so
        # a decision never ends up buried under a chain.
        parent_id = parent.parent_id or parent.id

    comment = Comment(investigation_id=investigation_id, parent_id=parent_id,
                      user_id=user_id, body=text, product_id=inv.product_id)
    session.add(comment)
    session.flush()

    for user in resolve_mentions(session, text):
        # Mentioning yourself must not fill your own inbox.
        if user.id == user_id:
            continue
        session.add(Mention(comment_id=comment.id, user_id=user.id,
                            product_id=inv.product_id))
    session.flush()
    return comment


def edit_comment(session: Session, comment: Comment, body: str, user_id: int) -> Comment:
    """Edit your own comment. Mentions are recomputed, but ones already there
    are kept — un-notifying someone because a typo was fixed would erase a
    notification they may have already acted on."""
    if comment.user_id != user_id:
        raise PermissionError("you can only edit your own comment")
    text = (body or "").strip()
    if not text:
        raise ValueError("a comment needs a body")
    if len(text) > MAX_COMMENT_CHARS:
        raise ValueError(f"comment is too long (max {MAX_COMMENT_CHARS} characters)")

    comment.body = text
    comment.edited_at = _now()
    existing = {m.user_id for m in session.scalars(
        select(Mention).where(Mention.comment_id == comment.id)).all()}
    for user in resolve_mentions(session, text):
        if user.id != user_id and user.id not in existing:
            session.add(Mention(comment_id=comment.id, user_id=user.id,
                                product_id=comment.product_id))
    session.flush()
    return comment


def delete_comment(session: Session, comment: Comment, user_id: int,
                   is_admin: bool = False) -> Comment:
    """Soft delete. The row stays so replies keep their anchor and the audit
    trail behind a challenge decision is not rewritten."""
    if comment.user_id != user_id and not is_admin:
        raise PermissionError("you can only delete your own comment")
    comment.deleted_at = _now()
    session.flush()
    return comment


def _author_label(session: Session, user_id: int | None,
                  cache: dict[int, str]) -> str:
    if user_id is None:
        return "unknown"
    if user_id not in cache:
        user = session.get(User, user_id)
        cache[user_id] = handle_of(user) if user else "unknown"
    return cache[user_id]


def comment_thread(session: Session, investigation_id: int) -> list[dict]:
    """The discussion for one case, roots first with their replies nested."""
    rows = session.scalars(
        select(Comment).where(Comment.investigation_id == investigation_id)
        .order_by(Comment.created_at)).all()
    cache: dict[int, str] = {}

    def render(c: Comment) -> dict:
        return {
            "id": c.id,
            "author": _author_label(session, c.user_id, cache),
            "author_id": c.user_id,
            # Body withheld rather than the row hidden: the reply structure and
            # the fact that something was said stay honest.
            "body": None if c.deleted_at else c.body,
            "deleted": c.deleted_at is not None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "edited": c.edited_at is not None,
            "replies": [],
        }

    out: dict[int, dict] = {}
    roots: list[dict] = []
    for c in rows:
        if c.parent_id is None:
            node = render(c)
            out[c.id] = node
            roots.append(node)
    for c in rows:
        if c.parent_id is not None and c.parent_id in out:
            out[c.parent_id]["replies"].append(render(c))
    return roots


def inbox(session: Session, user_id: int, product_id: int | None = None,
          unread_only: bool = True, limit: int = 50) -> list[dict]:
    """Mentions addressed to one user, newest first."""
    stmt = select(Mention).where(Mention.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Mention.read_at.is_(None))
    if product_id is not None:
        stmt = stmt.where(Mention.product_id == product_id)
    rows = session.scalars(stmt.order_by(Mention.created_at.desc()).limit(limit)).all()

    cache: dict[int, str] = {}
    out = []
    for m in rows:
        comment = session.get(Comment, m.comment_id)
        if comment is None or comment.deleted_at is not None:
            continue
        out.append({
            "mention_id": m.id,
            "investigation_id": comment.investigation_id,
            "comment_id": comment.id,
            "from": _author_label(session, comment.user_id, cache),
            "excerpt": comment.body[:160],
            "read": m.read_at is not None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })
    return out


def mark_read(session: Session, user_id: int, mention_ids: list[int] | None = None,
              product_id: int | None = None) -> int:
    """Mark mentions read. Scoped to the caller so one user cannot clear
    another's inbox."""
    stmt = select(Mention).where(Mention.user_id == user_id, Mention.read_at.is_(None))
    if mention_ids:
        stmt = stmt.where(Mention.id.in_(mention_ids))
    if product_id is not None:
        stmt = stmt.where(Mention.product_id == product_id)
    rows = session.scalars(stmt).all()
    for m in rows:
        m.read_at = _now()
    session.flush()
    return len(rows)


# ── review sign-off ─────────────────────────────────────────────────────

REQUEST_STATUSES = ("pending", "approved", "changes_requested", "cancelled")


def request_review(session: Session, investigation_id: int, requested_by_id: int | None,
                   requested_of_id: int | None = None, note: str = "") -> ReviewRequest:
    """Ask for sign-off on a case.

    Re-asking on a case that already has an open request returns the existing
    one rather than stacking duplicates in everybody's queue.
    """
    inv = session.get(Investigation, investigation_id)
    if inv is None:
        raise ValueError(f"no investigation with id {investigation_id}")
    if requested_of_id is not None and session.get(User, requested_of_id) is None:
        raise ValueError("cannot request review from a user who does not exist")

    existing = session.scalars(select(ReviewRequest).where(
        ReviewRequest.investigation_id == investigation_id,
        ReviewRequest.status == "pending")).first()
    if existing is not None:
        return existing

    req = ReviewRequest(investigation_id=investigation_id, requested_by_id=requested_by_id,
                        requested_of_id=requested_of_id, note=(note or "").strip(),
                        status="pending", product_id=inv.product_id)
    session.add(req)
    session.flush()
    return req


def resolve_request(session: Session, req: ReviewRequest, status: str) -> ReviewRequest:
    """Close out a review request.

    This records who signed off; it deliberately does NOT change the finding's
    status. approve/challenge stay the only way a conclusion moves, so a
    sign-off cannot smuggle a finding to `approved` without the evidence checks.
    """
    if status not in REQUEST_STATUSES or status == "pending":
        raise ValueError(f"status must be one of {REQUEST_STATUSES[1:]}")
    req.status = status
    req.resolved_at = _now()
    session.flush()
    return req


def team_activity(session: Session, product_id: int | None = None,
                  limit: int = 20) -> dict:
    """What the team is doing: open review requests, and recent discussion.

    Product-scoped like every other screen, so one product's dashboard never
    shows another's activity.
    """
    cache: dict[int, str] = {}

    req_stmt = select(ReviewRequest).where(ReviewRequest.status == "pending")
    com_stmt = select(Comment).where(Comment.deleted_at.is_(None))
    if product_id is not None:
        req_stmt = req_stmt.where(ReviewRequest.product_id == product_id)
        com_stmt = com_stmt.where(Comment.product_id == product_id)

    pending = [{
        "id": r.id,
        "investigation_id": r.investigation_id,
        "requested_by": _author_label(session, r.requested_by_id, cache),
        "requested_of": (_author_label(session, r.requested_of_id, cache)
                         if r.requested_of_id else "anyone"),
        "note": r.note,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in session.scalars(
        req_stmt.order_by(ReviewRequest.created_at.desc()).limit(limit)).all()]

    recent = [{
        "id": c.id,
        "investigation_id": c.investigation_id,
        "author": _author_label(session, c.user_id, cache),
        "excerpt": c.body[:140],
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in session.scalars(
        com_stmt.order_by(Comment.created_at.desc()).limit(limit)).all()]

    contributor_stmt = select(Comment.user_id, func.count(Comment.id)).where(
        Comment.deleted_at.is_(None))
    if product_id is not None:
        contributor_stmt = contributor_stmt.where(Comment.product_id == product_id)
    contributors = [
        {"user": _author_label(session, uid, cache), "comments": n}
        for uid, n in session.execute(
            contributor_stmt.group_by(Comment.user_id)).all() if uid is not None
    ]
    contributors.sort(key=lambda c: -c["comments"])

    return {
        "awaiting_review": pending,
        "recent_comments": recent,
        "contributors": contributors,
        "open_request_count": len(pending),
    }
