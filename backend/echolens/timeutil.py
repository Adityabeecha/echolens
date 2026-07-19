"""Tiny shared time helper. SQLite drops tzinfo on round-trip, so datetimes read
back naive; everything that compares them normalizes through here."""
from __future__ import annotations

from datetime import datetime, timezone


def aware_utc(dt: datetime | None) -> datetime | None:
    """Return `dt` as a UTC-aware datetime (None passes through)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
