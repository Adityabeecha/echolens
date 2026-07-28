"""Shared base for collectors that land in `FeedbackEntry` (v2.0).

Hacker News, Stack Overflow, GitHub Discussions and GitHub team activity all
arrive in the shape FeedbackEntry was built for, so none of them need a table or
a migration — once a row is in FeedbackEntry, `feedback.collect_items` normalises
it and the corroboration scoring and theme surges pick it up unchanged.

Subclasses own `fetch` and `parse_item`; dedup, watermarking and the undated-row
rule are handled once, here.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.collectors.base import Collector, iso
from echolens.db.models import FeedbackEntry


def ext_id_for(channel: str, native_id: str) -> str:
    """Channel-qualified id fitting FeedbackEntry.ext_id (String(96)).

    ext_id is globally unique, so an unqualified native id collides the moment
    two channels both number from 1. Long ids are hashed, not truncated —
    right-truncation is what collapsed distinct GitHub issues onto one id.
    """
    native = str(native_id)
    candidate = f"{channel}:{native}"
    if len(candidate) <= 96:
        return candidate
    digest = hashlib.sha1(native.encode("utf-8", "replace")).hexdigest()[:12]
    keep = 96 - len(channel) - len(digest) - 2  # ':' and '~'
    return f"{channel}:{native[:keep]}~{digest}"


class FeedbackCollector(Collector):
    """Collector whose items become `FeedbackEntry` rows."""

    channel: str = "feedback"
    author_kind: str = "user"

    def parse_item(self, item: dict) -> dict | None:
        """Return {native_id, text, created_at, priority?, status?, meta?} or None."""
        raise NotImplementedError

    def ingest_item(self, session: Session, item: dict) -> tuple[bool, str | None]:
        parsed = self.parse_item(item)
        if parsed is None:
            return False, None
        created = parsed.get("created_at")
        # Undated rows are skipped, never stamped with collection time: detectors
        # bucket by created_at, so an invented date reads as activity that never
        # happened. Same rule as the GitHub collector.
        if created is None:
            return False, None
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        text = (parsed.get("text") or "").strip()
        if not text:
            return False, iso(created)

        ext_id = ext_id_for(self.channel, parsed["native_id"])
        wm = iso(created)
        existing = session.scalars(
            select(FeedbackEntry).where(FeedbackEntry.ext_id == ext_id)).first()
        if existing:
            # Refresh what a re-fetch legitimately changes (replies, answered
            # state) without counting it as a new insert.
            existing.status = parsed.get("status", existing.status)
            if parsed.get("meta") is not None:
                existing.meta_json = parsed["meta"]
            return False, wm

        session.add(FeedbackEntry(
            channel=self.channel,
            ext_id=ext_id,
            text=text[:8000],
            product=self.product,
            author_kind=parsed.get("author_kind", self.author_kind),
            priority=parsed.get("priority"),
            status=parsed.get("status"),
            created_at=created,
            meta_json=parsed.get("meta"),
        ))
        return True, wm


def epoch_dt(value) -> datetime | None:
    """Unix seconds -> aware UTC datetime, or None if unusable."""
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def iso_dt(value) -> datetime | None:
    """ISO-8601 string -> aware UTC datetime, or None if unusable."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None
