"""Universal CSV review import (v7.1).

Widens the evidence base beyond the two live scrapers: a PM can drop in an App
Store export, a Zendesk export, in-app feedback, or any spreadsheet of reviews.
Header mapping is forgiving (rating/score/stars, text/content/review/body,
date/created_at/at). Dedup by a content hash so re-importing is idempotent.
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review

_TEXT_KEYS = ("text", "content", "review", "body", "comment", "feedback")
_RATING_KEYS = ("rating", "score", "stars", "star")
_DATE_KEYS = ("date", "created_at", "at", "time", "timestamp", "created")
_VERSION_KEYS = ("version", "app_version", "reviewcreatedversion")
_OS_KEYS = ("os", "os_version", "device", "platform")


def _pick(row: dict, keys) -> str | None:
    for k in keys:
        if row.get(k):
            return row[k]
    return None


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("iso", "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00")) if fmt == "iso" else datetime.strptime(raw, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _int(raw: str | None) -> int | None:
    """A star rating, or None when the column is missing/unparseable.

    This used to return 0 on failure, which was catastrophic rather than
    merely lossy: every negativity filter in the codebase is `rating <= 2`,
    so an absent rating column made 0 the MOST negative value possible. A
    Zendesk export with no ratings imported as a corpus of 1-star complaints,
    the detector fired on it, and the investigator gathered "evidence" from
    what was often praise. None means unknown, and unknown rows are skipped.
    """
    try:
        return max(0, min(5, int(float(str(raw).strip()))))
    except (TypeError, ValueError):
        return None


def import_reviews_csv(session: Session, text: str, product: str | None = None,
                       source: str = "csv") -> dict:
    """Ingest a CSV of reviews.

    Returns {imported, skipped, unrated, total}. `unrated` is reported
    separately because "your export had no rating column" is a fixable
    problem the user needs told, not a silent no-op.
    """
    reader = csv.DictReader(io.StringIO(text))
    imported = skipped = total = unrated = 0
    now = datetime.now(timezone.utc)
    for raw_row in reader:
        total += 1
        row = {(k or "").lower().strip(): (v or "") for k, v in raw_row.items()}
        body = _pick(row, _TEXT_KEYS)
        if not body or not body.strip():
            skipped += 1
            continue
        body = body.strip()
        rating = _int(_pick(row, _RATING_KEYS))
        if rating is None:
            # No rating means we cannot say whether this is a complaint. Guessing
            # would make it a 1-star; the honest move is to skip it and report it.
            skipped += 1
            unrated += 1
            continue
        created = _parse_date(_pick(row, _DATE_KEYS)) or now
        ext_id = "csv_" + hashlib.sha1(
            f"{source}|{product}|{body}|{created.date()}".encode("utf-8")).hexdigest()[:20]
        if session.scalars(select(Review).where(Review.ext_id == ext_id)).first():
            skipped += 1
            continue
        session.add(Review(
            source=source, ext_id=ext_id, rating=rating,
            text=body[:4000], version=_pick(row, _VERSION_KEYS),
            os_version=_pick(row, _OS_KEYS), created_at=created, product=product,
        ))
        imported += 1
    session.flush()
    return {"imported": imported, "skipped": skipped,
            "unrated": unrated, "total": total}
