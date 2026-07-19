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
            cutoff = datetime.fromisoformat(since)
            raw = [r for r in raw if _at(r) and _at(r) > cutoff]
        return raw

    def ingest_item(self, session: Session, item: dict) -> tuple[bool, str | None]:
        ext_id = f"gp_{item.get('reviewId')}"
        at = _at(item)
        wm = iso(at) if at else None
        if session.scalars(select(Review).where(Review.ext_id == ext_id)).first():
            return False, wm
        session.add(Review(
            source="play_store", ext_id=ext_id,
            rating=int(item.get("score") or 0),
            text=(item.get("content") or "").strip(),
            version=item.get("reviewCreatedVersion"),
            os_version=None,
            created_at=at or datetime.now(timezone.utc),
            product=self.product,
        ))
        return True, wm


def _at(item: dict) -> datetime | None:
    v = item.get("at")
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return None
    return None
