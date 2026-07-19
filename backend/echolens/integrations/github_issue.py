"""Create a GitHub issue from a finding (v4.0). The one native integration —
we already hold the token for the collector. Jira/Linear stay out until asked.

The HTTP call is injectable (`post_fn`) so tests never hit the network.
"""
from __future__ import annotations

from echolens.config import settings


class GitHubIssueError(RuntimeError):
    pass


def _default_post(repo: str, title: str, body: str, token: str, labels: list[str]) -> dict:
    import httpx

    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}"}
    payload = {"title": title, "body": body, "labels": labels}
    with httpx.Client(timeout=20, headers=headers) as c:
        r = c.post(f"https://api.github.com/repos/{repo}/issues", json=payload)
        if r.status_code >= 300:
            raise GitHubIssueError(f"GitHub API {r.status_code}: {r.text[:200]}")
        return r.json()


def create_issue(repo: str, title: str, body: str, token: str | None = None,
                 labels: list[str] | None = None, post_fn=None) -> dict:
    """Open an issue on `repo` (owner/name). Returns {number, url}. Raises
    GitHubIssueError on a missing token or an API failure."""
    token = token or settings.github_token
    if not token:
        raise GitHubIssueError("no GITHUB_TOKEN configured — cannot create an issue")
    if not repo or "/" not in repo:
        raise GitHubIssueError(f"invalid repo '{repo}' (expected owner/name)")
    post = post_fn or _default_post
    data = post(repo, title, body, token, labels or ["echolens"])
    return {"number": data.get("number"), "url": data.get("html_url")}
