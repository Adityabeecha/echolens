"""App Store review collector (v7.1) via Apple's public iTunes RSS feed.

Unlike the Play Store scraper this is a real, documented, free JSON endpoint
(itunes.apple.com/.../customerreviews), so no fragile unofficial scraper. The
network call is injectable so tests run offline.

Identifier = the numeric App Store app id (the digits in the store URL, id######).
"""
from __future__ import annotations

import hashlib

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
                # A rate-limit or 5xx is NOT end-of-pages. Treating it as one
                # made run() record a HEALTHY run and advance the watermark past
                # reviews that were never fetched — silently skipping them for
                # good. Raise so run() records the error and leaves the
                # watermark where it is, and the next run retries this window.
                raise RuntimeError(
                    f"App Store HTTP {resp.status_code} while paging; "
                    "stopping without advancing the watermark")
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

    def _ext_id_for(self, item: dict) -> str:
        """A stable, PRODUCT-SCOPED id for one review.

        sha1, not builtin hash(): Python salts string hashing per PROCESS
        (PYTHONHASHSEED), so an id-less review got a different ext_id on every
        restart — dedupe never matched and the same review was re-inserted on
        each run, inflating the corpus the detector reasons over.

        Product-qualified because Review.ext_id is globally unique. Apple reuses
        review ids across storefronts, and boilerplate text ("Doesn't work")
        hashes identically, so two products collided on one id: the second one's
        insert either read as a duplicate or failed the constraint outright, and
        its corpus silently lost the row.
        """
        review_id = _label(item, "id") or ""
        tag = hashlib.sha1((self.product or "").encode("utf-8")).hexdigest()[:6]
        if review_id:
            return f"as_{tag}_{review_id}"
        digest = hashlib.sha1(
            str(item.get("content", {}).get("label", "")).encode("utf-8")
        ).hexdigest()[:20]
        return f"as_{tag}_{digest}"

    def ingest_item(self, session: Session, item: dict) -> tuple[bool, str | None]:
        ext_id = self._ext_id_for(item)
        at = _at(item)
        wm = iso(at) if at else None
        # Scoped by product, like the GitHub collector already does: an ext_id
        # is only unique WITHIN a product, and Apple reuses review ids across
        # storefronts.
        if session.scalars(select(Review).where(
                Review.ext_id == ext_id, Review.product == self.product)).first():
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
