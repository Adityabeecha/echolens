"""GitHub collector (v1.0): issues (with labels + reactions) and releases.

Uses the REST API with optional token auth and pagination. `since` watermark is
the issue `updated_at`; dedup by issue number. Network call injectable.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.collectors.base import Collector, iso
from echolens.config import settings
from echolens.db.models import Issue, Release


def _ensure_list(resp, what: str) -> list:
    """GitHub returns a JSON list on success but an object {"message": ...} on
    error (bad repo, invalid token, rate limit). Turn those into a clear error the
    collector framework records, instead of crashing in the iteration loop."""
    if resp.status_code >= 300:
        msg = ""
        try:
            msg = resp.json().get("message", "")
        except Exception:
            pass
        raise RuntimeError(f"GitHub {what} HTTP {resp.status_code}: {msg or resp.text[:120]}")
    data = resp.json()
    if not isinstance(data, list):
        msg = data.get("message", "") if isinstance(data, dict) else ""
        raise RuntimeError(f"GitHub {what}: unexpected response — {msg or str(data)[:120]}")
    return data


def _default_fetch(repo: str, since: str | None, per_page: int, max_pages: int = 5) -> dict:
    import httpx

    headers = {"Accept": "application/vnd.github+json"}
    token = settings.github_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params = {"state": "all", "per_page": min(per_page, 100), "sort": "updated", "direction": "desc"}
    if since:
        params["since"] = since
    issues: list = []
    with httpx.Client(timeout=20, headers=headers) as c:
        # paginate via the Link header (bounded) so big repos aren't truncated to 100
        url: str | None = f"https://api.github.com/repos/{repo}/issues"
        page_params: dict | None = dict(params)
        for _ in range(max_pages):
            resp = c.get(url, params=page_params)
            page = _ensure_list(resp, "issues")
            issues.extend(page)
            nxt = resp.links.get("next", {}).get("url")
            if not nxt or not page:
                break
            url, page_params = nxt, None  # the next link already carries the query
        releases = _ensure_list(
            c.get(f"https://api.github.com/repos/{repo}/releases", params={"per_page": 30}), "releases")
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
        # Qualified by repo. `#1` alone is globally unique in the schema, so two
        # tracked repos that both have issue #1 collided: the second was reported
        # as a duplicate and silently dropped, AND the `existing` branch below
        # overwrote the first repo's state/labels/reactions with the second's.
        ext_id = _issue_ext_id(self.identifier, num)
        updated = _dt(item.get("updated_at"))
        wm = iso(updated) if updated else None
        existing = session.scalars(select(Issue).where(
            Issue.ext_id == ext_id, Issue.product == self.product)).first()
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
        # Scope the dedupe by product. The version string itself is left alone:
        # get_release_notes matches it with a PREFIX LIKE ("3.2%"), so prefixing
        # the repo would break every version lookup the agent makes. Uniqueness
        # is enforced by the (version, product) pair at the query level.
        if session.scalars(select(Release).where(
                Release.version == version, Release.product == self.product)).first():
            return False, iso(published) if published else None
        session.add(Release(
            version=version, notes=(item.get("body") or item.get("name") or "")[:4000],
            released_at=published or datetime.now(timezone.utc), product=self.product,
        ))
        return True, iso(published) if published else None


def _issue_ext_id(repo: str, number) -> str:
    """Repo-qualified issue id that fits String(64) WITHOUT losing the number.

    The old form was `f"{repo}#{number}"[:64]`, which truncates from the right —
    so past a ~62-character repo it cut the issue number off and every issue in
    that repo collapsed onto one ext_id. They were then dropped as duplicates,
    and the surviving row's state and labels were overwritten by each later
    issue. Measured: a 74-char repo gave 1 distinct id for 4 issues.

    The number is now always kept whole; only the repo is shortened, and a short
    digest of the full repo keeps two long repos that share a prefix distinct.
    """
    suffix = f"#{number}"
    if len(repo) + len(suffix) <= 64:
        return repo + suffix
    digest = hashlib.sha1(repo.encode()).hexdigest()[:8]
    keep = 64 - len(suffix) - len(digest) - 1  # 1 for the '~' separator
    return f"{repo[:keep]}~{digest}{suffix}"


def _dt(v) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
