"""App Store reviews via Apple's public customer-reviews RSS JSON feed.

Identifier = numeric App Store app ID or an apps.apple.com URL. Fetching is
injectable, with incremental timestamps and product-scoped dedup like Play Store.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.collectors.base import Collector, iso
from echolens.db.models import Review

RSS = "https://itunes.apple.com/{country}/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"
MAX_PAGES = 10


def parse_app_id(identifier: str) -> str:
    """Canonical numeric identity; never use an arbitrary input URL to fetch."""
    identifier = identifier.strip()
    if re.fullmatch(r"[0-9]+", identifier):
        return identifier
    try:
        url = urlsplit(identifier)
        match = re.search(r"/id([0-9]+)/?$", url.path)
        if (url.scheme in {"https", "http"} and url.hostname == "apps.apple.com"
                and not url.username and not url.password and match):
            return match[1]
    except ValueError:
        pass
    raise ValueError("App Store identifier must be digits or an apps.apple.com URL ending in id<digits>")


def _entries(payload) -> list:
    """Accept an RSS envelope or an injected entry list, like other collectors."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict) or not isinstance(payload.get("feed"), dict):
        raise RuntimeError("App Store: unrecognised RSS feed")
    entries = payload["feed"].get("entry", [])
    if entries is None:
        return []
    if isinstance(entries, dict):
        return [entries]
    if not isinstance(entries, list):
        raise RuntimeError("App Store: unrecognised RSS entries")
    return entries


def _default_fetch(app_id: str, country: str = "us", pages: int = MAX_PAGES) -> list[dict]:
    import httpx

    entries: list[dict] = []
    with httpx.Client(timeout=20) as client:
        for page in range(1, max(1, min(MAX_PAGES, pages)) + 1):
            resp = client.get(RSS.format(country=country, page=page, app_id=app_id))
            if resp.status_code >= 300:
                # A failed page must not turn partial results into a healthy
                # run or advance the watermark past unfetched reviews.
                raise RuntimeError(
                    f"App Store HTTP {resp.status_code} while paging; "
                    "stopping without advancing the watermark")
            page_entries = _entries(resp.json())
            entries.extend(e for e in page_entries if isinstance(e, dict) and "im:rating" in e)
            if not page_entries:
                break
    return entries


def _label(node, key: str) -> str | None:
    value = node.get(key) if isinstance(node, dict) else None
    label = value.get("label") if isinstance(value, dict) else None
    return label.strip() if isinstance(label, str) and label.strip() else None


def _at(item) -> datetime | None:
    raw = _label(item, "updated")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except ValueError:
        return None


class AppStoreCollector(Collector):
    source = "app_store"

    def __init__(self, identifier: str, product: str | None = None, fetch_fn=None,
                 product_id: int | None = None, *, country: str = "us"):
        super().__init__(parse_app_id(identifier), product, fetch_fn, product_id)
        country = country.lower()
        if not re.fullmatch(r"[a-z]{2}", country):
            raise ValueError("App Store country must be a two-letter country code")
        self.country = country

    def fetch(self, since: str | None, limit: int) -> list[dict]:
        # Apple supplies roughly 50 reviews/page; never exceed its ten pages.
        pages = min(MAX_PAGES, max(1, (limit + 49) // 50)) if limit else MAX_PAGES
        fetch = self._fetch_fn or (lambda: _default_fetch(
            self.identifier, country=self.country, pages=pages))
        payload = fetch() if callable(fetch) else fetch
        raw = [e for e in _entries(payload) if isinstance(e, dict) and "im:rating" in e]
        if since:
            cutoff = datetime.fromisoformat(since.replace("Z", "+00:00"))
            cutoff = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
            dated = [(e, _at(e)) for e in raw]
            raw = [e for e, at in dated if at is not None and at > cutoff]
        selected = raw[:limit] if limit else raw
        return sorted(selected, key=lambda e: _at(e) or datetime.min.replace(tzinfo=timezone.utc))

    def _ext_id_for(self, item: dict) -> str:
        """App- and product-qualified IDs; stable across process restarts."""
        review_id = _label(item, "id") or hashlib.sha1(
            (_label(item, "content") or "").encode("utf-8")).hexdigest()[:20]
        tag = hashlib.sha1(self.product.encode("utf-8")).hexdigest()[:6]
        return f"appstore:{self.identifier}:{tag}:{review_id}"

    def ingest_item(self, session: Session, item: dict) -> tuple[bool, str | None]:
        review_id = _label(item, "id")
        at = _at(item)
        raw_rating = _label(item, "im:rating")
        if not review_id or at is None or raw_rating not in {"1", "2", "3", "4", "5"}:
            return False, None
        text = "\n\n".join(part for part in (_label(item, "title"), _label(item, "content")) if part)
        if not text:
            return False, None
        ext_id = self._ext_id_for(item)
        wm = iso(at)
        # Older releases used a product hash without the app ID. Recognise
        # those stored rows as well, without rewriting their identity.
        tag = hashlib.sha1(self.product.encode("utf-8")).hexdigest()[:6]
        legacy_id = f"as_{tag}_{review_id}"
        if session.scalars(select(Review).where(
                Review.ext_id.in_([ext_id, legacy_id]), Review.product == self.product,
                Review.source == self.source)).first():
            return False, wm
        session.add(Review(
            source=self.source, ext_id=ext_id, rating=int(raw_rating), text=text,
            version=_label(item, "im:version"), os_version=None,
            created_at=at, product=self.product,
        ))
        return True, wm
