"""GitHub Discussions and team activity (v2.0).

Two collectors that share the repo identifier but sit on opposite sides of the
witness line:

- `GitHubDiscussionsCollector` — user feedback, counted as corroboration.
- `GitHubActivityCollector` — the team's own PRs and commits, ingested as
  timeline context and excluded from corroboration by `feedback.TEAM_CHANNELS`.

Discussions are only reachable through GraphQL, so unlike the REST collectors
this one needs a token; without one it fails with a clear message rather than
returning an empty page that would read as "no discussions".
"""
from __future__ import annotations

from echolens.collectors.feedback_base import FeedbackCollector, iso_dt
from echolens.config import settings

GRAPHQL_ENDPOINT = "https://api.github.com/graphql"

_DISCUSSIONS_QUERY = """
query($owner:String!, $name:String!, $first:Int!) {
  repository(owner:$owner, name:$name) {
    discussions(first:$first, orderBy:{field:CREATED_AT, direction:DESC}) {
      nodes {
        id number title bodyText createdAt url
        category { name }
        answer { id }
        comments(first:20) { nodes { id bodyText createdAt url author { login } } }
      }
    }
  }
}
"""


def _split_repo(identifier: str) -> tuple[str, str]:
    parts = (identifier or "").strip().strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"expected 'owner/repo', got {identifier!r}")
    return parts[0], parts[1]


def _default_discussions_fetch(repo: str, limit: int) -> dict:
    import httpx

    token = settings.github_token
    if not token:
        raise RuntimeError(
            "GitHub Discussions needs GITHUB_TOKEN — the GraphQL API has no "
            "anonymous access")
    owner, name = _split_repo(repo)
    with httpx.Client(timeout=20) as c:
        resp = c.post(
            GRAPHQL_ENDPOINT,
            headers={"Authorization": f"Bearer {token}"},
            json={"query": _DISCUSSIONS_QUERY,
                  "variables": {"owner": owner, "name": name,
                                "first": min(max(limit, 1), 100)}},
        )
    if resp.status_code >= 300:
        raise RuntimeError(f"GitHub GraphQL HTTP {resp.status_code}: {resp.text[:160]}")
    data = resp.json()
    if data.get("errors"):
        msg = "; ".join(e.get("message", "") for e in data["errors"])
        raise RuntimeError(f"GitHub GraphQL: {msg[:160]}")
    return data


class GitHubDiscussionsCollector(FeedbackCollector):
    source = "github_discussions"
    channel = "github_discussion"
    author_kind = "user"

    def fetch(self, since: str | None, limit: int) -> list[dict]:
        fetch = self._fetch_fn or (lambda: _default_discussions_fetch(self.identifier, limit))
        data = fetch() if callable(fetch) else fetch
        repo = (((data.get("data") or {}).get("repository")) or {})
        nodes = ((repo.get("discussions") or {}).get("nodes")) or []
        items: list[dict] = []
        for d in nodes:
            if not d:
                continue
            items.append({"kind": "discussion", **d})
            for c in ((d.get("comments") or {}).get("nodes")) or []:
                if c:
                    items.append({"kind": "comment", "_discussion": d.get("number"), **c})
        return sorted(items, key=lambda i: i.get("createdAt") or "")

    def parse_item(self, item: dict) -> dict | None:
        native = item.get("id")
        if not native:
            return None
        if item.get("kind") == "comment":
            text = (item.get("bodyText") or "").strip()
            if not text:
                return None
            return {
                "native_id": native,
                "text": text,
                "created_at": iso_dt(item.get("createdAt")),
                "meta": {"url": item.get("url"),
                         "discussion": item.get("_discussion"),
                         "kind": "comment"},
            }
        title = (item.get("title") or "").strip()
        body = (item.get("bodyText") or "").strip()
        text = f"{title}. {body}".strip(". ").strip() if title else body
        if not text:
            return None
        return {
            "native_id": native,
            "text": text,
            "created_at": iso_dt(item.get("createdAt")),
            "status": "answered" if item.get("answer") else "unanswered",
            "meta": {
                "number": item.get("number"),
                "category": (item.get("category") or {}).get("name"),
                "url": item.get("url"),
                "kind": "discussion",
            },
        }


def _default_activity_fetch(repo: str, since: str | None, limit: int) -> dict:
    import httpx

    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    per_page = min(max(limit, 1), 100)
    with httpx.Client(timeout=20, headers=headers) as c:
        pr_params: dict = {"state": "closed", "per_page": per_page,
                           "sort": "updated", "direction": "desc"}
        prs = c.get(f"https://api.github.com/repos/{repo}/pulls", params=pr_params)
        commit_params: dict = {"per_page": per_page}
        if since:
            commit_params["since"] = since
        commits = c.get(f"https://api.github.com/repos/{repo}/commits", params=commit_params)
    out: dict = {"pulls": [], "commits": []}
    for resp, key, what in ((prs, "pulls", "pulls"), (commits, "commits", "commits")):
        if resp.status_code >= 300:
            raise RuntimeError(f"GitHub {what} HTTP {resp.status_code}: {resp.text[:120]}")
        body = resp.json()
        out[key] = body if isinstance(body, list) else []
    return out


class GitHubActivityCollector(FeedbackCollector):
    """Merged PRs and commits as release-timeline context.

    Deliberately NOT a complaint channel — see `feedback.TEAM_CHANNELS`. This
    exists so an investigator can say "this shipped two days before the spike",
    which is causal evidence, without the team's own writing inflating how many
    independent people reported the problem.
    """

    source = "github_activity"
    channel = "github_pr"
    author_kind = "engineer"

    def fetch(self, since: str | None, limit: int) -> list[dict]:
        fetch = self._fetch_fn or (lambda: _default_activity_fetch(self.identifier, since, limit))
        data = fetch() if callable(fetch) else fetch
        items: list[dict] = []
        for pr in data.get("pulls", []) or []:
            if pr.get("merged_at"):
                items.append({"kind": "pr", **pr})
        for cm in data.get("commits", []) or []:
            items.append({"kind": "commit", **cm})
        return sorted(items, key=lambda i: _activity_dt(i) or "")

    def parse_item(self, item: dict) -> dict | None:
        if item.get("kind") == "commit":
            sha = item.get("sha")
            commit = item.get("commit") or {}
            message = (commit.get("message") or "").strip()
            if not sha or not message:
                return None
            return {
                "native_id": f"commit:{sha}",
                "text": message,
                "created_at": iso_dt(((commit.get("author") or {}).get("date"))),
                "author_kind": "engineer",
                "meta": {"sha": sha, "url": item.get("html_url"), "kind": "commit"},
            }
        num = item.get("number")
        if num is None:
            return None
        title = (item.get("title") or "").strip()
        body = (item.get("body") or "").strip()
        text = f"{title}. {body}".strip(". ").strip() if title else body
        if not text:
            return None
        return {
            "native_id": f"pr:{num}",
            "text": text,
            "created_at": iso_dt(item.get("merged_at")),
            "status": "merged",
            "author_kind": "engineer",
            "meta": {"number": num, "url": item.get("html_url"),
                     "merged_at": item.get("merged_at"), "kind": "pr"},
        }


def _activity_dt(item: dict) -> str | None:
    if item.get("kind") == "commit":
        return ((item.get("commit") or {}).get("author") or {}).get("date")
    return item.get("merged_at")
