"""GitHub collector (v1.0): issues (with labels + reactions) and releases.

Uses the REST API with optional token auth and pagination. `since` watermark is
the issue `updated_at`; dedup by issue number. Network call injectable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.collectors.base import Collector, iso
from echolens.config import settings
from echolens.db.models import Issue, Release


def _default_fetch(repo: str, since: str | None, per_page: int) -> dict:
    import httpx

    headers = {"Accept": "application/vnd.github+json"}
    token = settings.github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params = {"state": "all", "per_page": min(per_page, 100), "sort": "updated", "direction": "desc"}
    if since:
        params["since"] = since
    with httpx.Client(timeout=20, headers=headers) as c:
        issues = c.get(f"https://api.github.com/repos/{repo}/issues", params=params).json()
        releases = c.get(f"https://api.github.com/repos/{repo}/releases",
                         params={"per_page": 30}).json()
    return {"issues": issues, "releases": releases}


class GitHubCollector(Collector):
    source = "github"

    def fetch(self, since: str | None, limit: int) -> list[dict]:
        fetch = self._fetch_fn or (lambda: _default_fetch(self.identifier, since, limit))
        data = fetch() if callable(fetch) else fetch
        items = []
        for iss in data.get("issues", []):
            if "pull_request" in iss:  # the issues endpoint also returns PRs
                iss = {**iss, "_is_pr": True}
            items.append({"kind": "issue", **iss})
        for rel in data.get("releases", []):
            items.append({"kind": "release", **rel})
        return items

    def ingest_item(self, session: Session, item: dict) -> tuple[bool, str | None]:
        if item.get("kind") == "release":
            return self._ingest_release(session, item)
        return self._ingest_issue(session, item)

    def _ingest_issue(self, session: Session, item: dict) -> tuple[bool, str | None]:
        num = item.get("number")
        ext_id = f"#{num}"
        updated = _dt(item.get("updated_at"))
        wm = iso(updated) if updated else None
        existing = session.scalars(select(Issue).where(Issue.ext_id == ext_id)).first()
        labels = [l.get("name") for l in item.get("labels", []) if isinstance(l, dict)]
        reactions = (item.get("reactions") or {}).get("total_count", 0)
        if existing:  # refresh mutable fields, but it's not a NEW insert
            existing.state = item.get("state", existing.state)
            existing.reactions = reactions
            existing.labels = labels
            return False, wm
        session.add(Issue(
            ext_id=ext_id, title=item.get("title", ""),
            body_snippet=(item.get("body") or "")[:2000],
            state=item.get("state", "open"), reactions=reactions,
            created_at=_dt(item.get("created_at")) or datetime.now(timezone.utc),
            labels=labels, product=self.product,
        ))
        return True, wm

    def _ingest_release(self, session: Session, item: dict) -> tuple[bool, str | None]:
        version = item.get("tag_name") or item.get("name")
        if not version:
            return False, None
        published = _dt(item.get("published_at"))
        if session.scalars(select(Release).where(Release.version == version)).first():
            return False, iso(published) if published else None
        session.add(Release(
            version=version, notes=(item.get("body") or item.get("name") or "")[:4000],
            released_at=published or datetime.now(timezone.utc), product=self.product,
        ))
        return True, iso(published) if published else None


def _dt(v) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
