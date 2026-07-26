"""Play Store review collector (v1.0) via google-play-scraper.

Incremental by review timestamp watermark; dedup by reviewId (ext_id). The
scraper call is injectable so tests run offline.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.collectors.base import Collector, iso
from echolens.db.models import Review


def _default_fetch(app_id: str, count: int, retries: int = 3) -> list[dict]:
    # Lazy import: the heavy/unofficial dep is only needed for a live pull.
    import time as _t

    from google_play_scraper import Sort, reviews  # type: ignore

    # google-play-scraper is an unofficial scraper — transient failures (throttling,
    # flaky network) are common, so retry with backoff before giving up.
    last: Exception | None = None
    for attempt in range(retries):
        try:
            result, _ = reviews(app_id, lang="en", country="us", sort=Sort.NEWEST, count=count)
            return result
        except Exception as err:  # noqa: BLE001 — retry any scraper failure
            last = err
            _t.sleep(1.5 * (attempt + 1))
    raise last if last else RuntimeError("play store fetch failed")


class PlayStoreCollector(Collector):
    source = "play_store"

    def fetch(self, since: str | None, limit: int) -> list[dict]:
        fetch = self._fetch_fn or (lambda: _default_fetch(self.identifier, limit))
        raw = fetch() if callable(fetch) else fetch
        if since:  # keep only reviews strictly newer than the watermark
            cutoff = _aware(datetime.fromisoformat(since))
            # Parse ONCE per item, not twice, and compare aware-to-aware. _at()
            # used to return a NAIVE datetime for the string branch while the
            # watermark iso() always writes an aware one, so the comparison
            # raised TypeError — and because run() catches that and never
            # advances the watermark, EVERY subsequent run failed identically
            # and the collector was wedged forever.
            dated = [(r, _at(r)) for r in raw]
            raw = [r for r, at in dated if at is not None and at > cutoff]
        # `limit` is honoured after filtering. It was passed in and then ignored,
        # so a run had no bound on how much it ingested (app_store.py:67 does
        # this correctly).
        return raw[:limit] if limit else raw

    def ingest_item(self, session: Session, item: dict) -> tuple[bool, str | None]:
        ext_id = f"gp_{item.get('reviewId')}"
        if item.get("score") in (None, ""):
            return False, None      # unrated: cannot tell praise from complaint
        at = _at(item)
        wm = iso(at) if at else None
        if session.scalars(select(Review).where(Review.ext_id == ext_id)).first():
            return False, wm
        session.add(Review(
            source="play_store", ext_id=ext_id,
            # A missing score must not become 0: every negativity filter is
            # `rating <= 2`, so 0 reads as the most negative value possible.
            # Skip the row instead of inventing a complaint.
            rating=int(item["score"]),
            text=(item.get("content") or "").strip(),
            version=item.get("reviewCreatedVersion"),
            os_version=None,
            created_at=at or datetime.now(timezone.utc),
            product=self.product,
        ))
        return True, wm


def _aware(dt: datetime | None) -> datetime | None:
    """UTC-aware, always. Mixing naive and aware datetimes is a TypeError at
    comparison time, and this module compares timestamps to a watermark."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _at(item: dict) -> datetime | None:
    v = item.get("at")
    if isinstance(v, datetime):
        return _aware(v)
    if isinstance(v, str):
        try:
            return _aware(datetime.fromisoformat(v))
        except ValueError:
            return None
    return None
