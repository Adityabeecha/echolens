"""Stack Overflow collector (v2.0), via the keyless StackExchange API.

The identifier is a tag (`react-native`) or a free-text query. Keyless access is
capped at 300 requests/day per IP, which one scheduled run per source stays well
inside.
"""
from __future__ import annotations

from echolens.collectors.feedback_base import FeedbackCollector, epoch_dt, iso_dt

SO_ENDPOINT = "https://api.stackexchange.com/2.3/search/advanced"


def _default_fetch(query: str, since: str | None, limit: int) -> dict:
    import httpx

    params = {
        "site": "stackoverflow",
        "order": "asc",
        "sort": "creation",
        "pagesize": min(max(limit, 1), 100),
        "filter": "withbody",
    }
    # A bare tag is treated as a tag filter; anything with a space is a search.
    if query and " " not in query:
        params["tagged"] = query
    else:
        params["q"] = query
    since_dt = iso_dt(since)
    if since_dt:
        params["fromdate"] = int(since_dt.timestamp())
    with httpx.Client(timeout=20) as c:
        resp = c.get(SO_ENDPOINT, params=params)
        if resp.status_code >= 300:
            raise RuntimeError(
                f"Stack Overflow HTTP {resp.status_code}: {resp.text[:120]}")
        data = resp.json()
    if data.get("error_id"):
        raise RuntimeError(
            f"Stack Overflow error {data['error_id']}: {data.get('error_message', '')}")
    return data


class StackOverflowCollector(FeedbackCollector):
    source = "stack_overflow"
    channel = "stack_overflow"
    author_kind = "engineer"

    def fetch(self, since: str | None, limit: int) -> list[dict]:
        fetch = self._fetch_fn or (lambda: _default_fetch(self.identifier, since, limit))
        data = fetch() if callable(fetch) else fetch
        items = data.get("items", []) if isinstance(data, dict) else list(data)
        return sorted(items, key=lambda q: q.get("creation_date") or 0)

    def parse_item(self, item: dict) -> dict | None:
        native = item.get("question_id")
        if native is None:
            return None
        title = (item.get("title") or "").strip()
        body = _strip_html(item.get("body") or "")
        text = f"{title}. {body}".strip(". ").strip() if title else body
        if not text:
            return None
        return {
            "native_id": native,
            "text": text,
            "created_at": epoch_dt(item.get("creation_date")),
            # An unanswered question is an open problem; an accepted answer means
            # the community solved it. Downstream can tell those apart.
            "status": "answered" if item.get("is_answered") else "unanswered",
            "meta": {
                "score": item.get("score"),
                "view_count": item.get("view_count"),
                "answer_count": item.get("answer_count"),
                "tags": item.get("tags"),
                "url": item.get("link"),
            },
        }


def _strip_html(text: str) -> str:
    import html
    import re

    # Code blocks are dropped: a stack trace pasted into a question is not the
    # user's description of the problem, and it swamps the theme vocabulary.
    text = re.sub(r"<pre>.*?</pre>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()
