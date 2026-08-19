"""Chrome Web Store review collector (v2.0). BEST-EFFORT.

Google publishes no API for extension reviews, so this reads the same internal
endpoint the store page itself calls. That is a real dependency on an
undocumented format: it can change without notice.

The failure is designed to be loud rather than quiet. A shape we don't recognise
raises, which marks the source errored and makes `source_health` report it stale
— so a finding never silently rests on a channel that stopped returning data.
Reviews land in the `Review` table like any other store.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.collectors.base import Collector, iso
from echolens.db.models import Review

CWS_ENDPOINT = ("https://chrome.google.com/reviews/components")
# This is an undocumented, best-effort endpoint and has been observed holding
# a failed 502 response open for 20+ seconds. Optional Chrome reviews must not
# become the critical path for an otherwise healthy multi-source onboarding.
CWS_TIMEOUT_S = 5


def _default_fetch(extension_id: str, limit: int) -> list[dict]:
    import httpx

    payload = {
        "f.req": json.dumps([[
            ["ugvhpe", json.dumps([[None, [[None, 0, min(max(limit, 1), 100)], None,
                                           None, None, None], [2, extension_id, 7]]]),
             None, "generic"],
        ]]),
    }
    with httpx.Client(timeout=CWS_TIMEOUT_S) as c:
        resp = c.post(CWS_ENDPOINT, data=payload,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    if resp.status_code >= 300:
        raise RuntimeError(f"Chrome Web Store HTTP {resp.status_code}: {resp.text[:120]}")
    return _parse_batch(resp.text)


def _parse_batch(text: str) -> list[dict]:
    """Unwrap Google's batchexecute envelope: `)]}'` then nested JSON strings."""
    body = text.lstrip()
    if body.startswith(")]}'"):
        body = body.split("\n", 1)[1] if "\n" in body else body[4:]
    try:
        outer = json.loads(body)
        inner = json.loads(outer[0][2])
    except (ValueError, IndexError, TypeError) as err:
        raise RuntimeError(
            f"Chrome Web Store: unrecognised response shape ({type(err).__name__}). "
            "The undocumented endpoint likely changed.") from err
    rows = inner[0] if inner and isinstance(inner[0], list) else []
    return [r for r in rows if isinstance(r, list)]


class ChromeWebStoreCollector(Collector):
    source = "chrome_web_store"

    def fetch(self, since: str | None, limit: int) -> list[dict]:
        fetch = self._fetch_fn or (lambda: _default_fetch(self.identifier, limit))
        raw = fetch() if callable(fetch) else fetch
        items = [_normalise(r) for r in (raw or [])]
        items = [i for i in items if i is not None]
        if since:
            cutoff = _aware(datetime.fromisoformat(since))
            items = [i for i in items if i["created_at"] and i["created_at"] > cutoff]
        items.sort(key=lambda i: i["created_at"] or datetime.min.replace(tzinfo=timezone.utc))
        return items[:limit] if limit else items

    def ingest_item(self, session: Session, item: dict) -> tuple[bool, str | None]:
        native = item.get("id")
        rating = item.get("rating")
        if not native or rating in (None, ""):
            return False, None
        at = item.get("created_at")
        if at is None:
            return False, None
        wm = iso(at)
        ext_id = f"cws_{native}"[:64]
        if session.scalars(select(Review).where(
                Review.ext_id == ext_id, Review.product == self.product)).first():
            return False, wm
        session.add(Review(
            source="chrome_web_store", ext_id=ext_id, rating=int(rating),
            text=(item.get("text") or "").strip(),
            version=item.get("version"), os_version=None,
            created_at=at, product=self.product,
        ))
        return True, wm


def _normalise(row: list) -> dict | None:
    """Map one positional row to named fields.

    The payload is positional and undocumented, so each field is probed by type
    rather than trusted by index — a shifted column then yields None (a skipped
    row) instead of silently writing a rating into the text field.
    """
    if not isinstance(row, list) or len(row) < 3:
        return None
    native = next((v for v in row if isinstance(v, str) and len(v) > 8), None)
    rating = next((v for v in row if isinstance(v, int) and 1 <= v <= 5), None)
    text = ""
    for v in row:
        if isinstance(v, str) and v != native and len(v) > len(text):
            text = v
    created = None
    for v in row:
        if isinstance(v, (int, float)) and v > 1_000_000_000:
            created = _epoch(v)
            break
    if native is None or rating is None:
        return None
    return {"id": native, "rating": rating, "text": text,
            "created_at": created, "version": None}


def _epoch(value) -> datetime | None:
    # The endpoint has used both seconds and milliseconds.
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v > 1e12:
        v /= 1000.0
    try:
        return datetime.fromtimestamp(v, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
