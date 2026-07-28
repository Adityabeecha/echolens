"""Hacker News collector (v2.0), via the keyless Algolia search API.

The identifier is the search query (usually the product name). Results include
comments as well as stories, because on HN the complaint is nearly always in a
comment rather than the submission title.
"""
from __future__ import annotations

from echolens.collectors.feedback_base import FeedbackCollector, epoch_dt, iso_dt

HN_ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"

MIN_COMMENT_CHARS = 40


def _default_fetch(query: str, since: str | None, limit: int) -> dict:
    import httpx

    params = {
        "query": query,
        "tags": "(story,comment)",
        "hitsPerPage": min(max(limit, 1), 100),
    }
    # Our watermark is ISO; Algolia filters on unix seconds. Passing the ISO
    # string straight through silently matches nothing.
    since_dt = iso_dt(since)
    if since_dt:
        params["numericFilters"] = f"created_at_i>{int(since_dt.timestamp())}"
    with httpx.Client(timeout=20) as c:
        resp = c.get(HN_ENDPOINT, params=params)
        if resp.status_code >= 300:
            raise RuntimeError(f"Hacker News HTTP {resp.status_code}: {resp.text[:120]}")
        return resp.json()


class HackerNewsCollector(FeedbackCollector):
    source = "hacker_news"
    channel = "hacker_news"
    author_kind = "user"

    def fetch(self, since: str | None, limit: int) -> list[dict]:
        fetch = self._fetch_fn or (lambda: _default_fetch(self.identifier, since, limit))
        data = fetch() if callable(fetch) else fetch
        hits = data.get("hits", []) if isinstance(data, dict) else list(data)
        # Oldest-first: the base class freezes the watermark at a failed item and
        # resumes there, which is only correct in ascending time order.
        return sorted(hits, key=lambda h: h.get("created_at_i") or 0)

    def parse_item(self, item: dict) -> dict | None:
        native = item.get("objectID")
        if not native:
            return None
        title = (item.get("title") or "").strip()
        body = (item.get("comment_text") or item.get("story_text") or "").strip()
        is_comment = bool(item.get("comment_text"))
        if is_comment and len(body) < MIN_COMMENT_CHARS:
            return None
        text = f"{title}. {body}".strip(". ").strip() if title else body
        if not text:
            return None
        return {
            "native_id": native,
            "text": _strip_html(text),
            "created_at": epoch_dt(item.get("created_at_i")) or iso_dt(item.get("created_at")),
            "meta": {
                "points": item.get("points"),
                "num_comments": item.get("num_comments"),
                "author": item.get("author"),
                "url": f"https://news.ycombinator.com/item?id={native}",
                "kind": "comment" if is_comment else "story",
            },
        }


def _strip_html(text: str) -> str:
    """HN comment_text is HTML; unescaped, `&quot;` and `<p>` cluster as words."""
    import html
    import re

    text = re.sub(r"<p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()
