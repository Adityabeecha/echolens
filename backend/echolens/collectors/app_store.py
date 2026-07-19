"""App Store review collector (v7.1) via Apple's public iTunes RSS feed.

Unlike the Play Store scraper this is a real, documented, free JSON endpoint
(itunes.apple.com/.../customerreviews), so no fragile unofficial scraper. The
network call is injectable so tests run offline.

Identifier = the numeric App Store app id (the digits in the store URL, id######).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.collectors.base import Collector, iso
from echolens.db.models import Review

RSS = "https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"


def _default_fetch(app_id: str, country: str = "us", pages: int = 4) -> list[dict]:
    import httpx

    entries: list[dict] = []
    with httpx.Client(timeout=20) as c:
        for page in range(1, pages + 1):
            resp = c.get(RSS.format(country=country, page=page, app_id=app_id))
            if resp.status_code >= 300:
                break
            feed = (resp.json() or {}).get("feed", {})
            page_entries = feed.get("entry", []) or []
            # the first entry on page 1 is app metadata (no im:rating) — skip those
            entries += [e for e in page_entries if isinstance(e, dict) and "im:rating" in e]
            if not page_entries:
                break
    return entries


def _label(node: dict, key: str) -> str | None:
    v = node.get(key)
    if isinstance(v, dict):
        return v.get("label")
    return None


def _at(item: dict) -> datetime | None:
    raw = _label(item, "updated")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class AppStoreCollector(Collector):
    source = "app_store"

    def fetch(self, since: str | None, limit: int) -> list[dict]:
        fetch = self._fetch_fn or (lambda: _default_fetch(self.identifier))
        raw = fetch() if callable(fetch) else fetch
        if since:
            cutoff = datetime.fromisoformat(since)
            raw = [e for e in raw if (_at(e) and _at(e) > cutoff)]
        return raw[:limit] if limit else raw

    def ingest_item(self, session: Session, item: dict) -> tuple[bool, str | None]:
        review_id = _label(item, "id") or ""
        ext_id = f"as_{review_id}" if review_id else f"as_{hash(item.get('content', {}).get('label', ''))}"
        at = _at(item)
        wm = iso(at) if at else None
        if session.scalars(select(Review).where(Review.ext_id == ext_id)).first():
            return False, wm
        try:
            rating = int(_label(item, "im:rating") or 0)
        except (TypeError, ValueError):
            rating = 0
        text = (_label(item, "content") or "").strip()
        session.add(Review(
            source="app_store", ext_id=ext_id, rating=rating, text=text,
            version=_label(item, "im:version"), os_version=None,
            created_at=at or datetime.now(timezone.utc), product=self.product,
        ))
        return True, wm
