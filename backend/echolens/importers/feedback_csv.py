"""Import support tickets, in-app feedback and forum threads from a CSV.

These channels have no universal API — every helpdesk exports differently — so
the import is column-tolerant rather than schema-strict: it looks for the
columns it needs under any of the names vendors actually use, and reports what
it could not read instead of failing the whole file.

Idempotent by content hash, so re-importing an overlapping export is safe.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import FeedbackEntry

# Column aliases seen across Zendesk, Intercom, Freshdesk, Discourse and
# hand-rolled spreadsheet exports.
ALIASES = {
    "text": ["text", "body", "description", "message", "comment", "content",
             "subject", "title", "feedback", "ticket_description"],
    "created_at": ["created_at", "created", "date", "timestamp", "submitted_at",
                   "opened_at", "created_time"],
    "ext_id": ["id", "ticket_id", "external_id", "reference", "number", "key"],
    "priority": ["priority", "severity", "urgency"],
    "status": ["status", "state", "ticket_status"],
    "author_kind": ["author_kind", "requester_type", "author_type"],
}

CHANNELS = ("support", "in_app", "forum")


def _norm_key(key: str | None) -> str:
    """'Ticket ID' and 'ticket_id' are the same column. Vendors disagree about
    spaces, case and hyphens, so normalise before matching aliases."""
    return re.sub(r"[\s\-]+", "_", (key or "").strip().lower())


def _pick(row: dict, field: str) -> str | None:
    lowered = {_norm_key(k): v for k, v in row.items()}
    for alias in ALIASES[field]:
        val = lowered.get(alias)
        if val not in (None, ""):
            return str(val).strip()
    return None


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
                "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def import_feedback_csv(session: Session, raw: str, *, channel: str = "support",
                        product: str | None = None) -> dict:
    """Load a CSV into the unified feedback table."""
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {CHANNELS}, got {channel!r}")

    reader = csv.DictReader(io.StringIO(raw))
    inserted = skipped = undated = 0
    problems: list[str] = []

    for n, row in enumerate(reader, start=2):
        text = _pick(row, "text")
        if not text:
            skipped += 1
            if len(problems) < 5:
                problems.append(f"row {n}: no text column found")
            continue

        created = _parse_dt(_pick(row, "created_at"))
        if created is None:
            undated += 1
            if len(problems) < 5:
                problems.append(f"row {n}: unreadable date, row skipped")
            continue  # undated feedback can't be windowed, so it can't be used

        raw_id = _pick(row, "ext_id")
        digest = hashlib.sha1(f"{channel}:{product}:{text}".encode()).hexdigest()[:16]
        ext_id = f"{channel}-{raw_id}" if raw_id else f"{channel}-{digest}"

        if session.scalars(select(FeedbackEntry).where(
                FeedbackEntry.ext_id == ext_id)).first():
            skipped += 1
            continue

        session.add(FeedbackEntry(
            channel=channel, ext_id=ext_id, text=text, product=product,
            author_kind=_pick(row, "author_kind") or "user",
            priority=_pick(row, "priority"), status=_pick(row, "status"),
            created_at=created, meta_json={"row": n}))
        inserted += 1

    session.flush()
    return {"channel": channel, "product": product, "inserted": inserted,
            "skipped": skipped, "undated": undated, "problems": problems}
