"""Issue trackers beyond GitHub: Linear and Jira Cloud.

Every tracker takes the same {title, body} markdown that `finding_ticket`
builds, so a ticket reads the same wherever it lands. Credentials come from
settings and are never echoed back; `configured_trackers()` reports only which
ones are usable.

The HTTP call is injectable (`post_fn(url, json, headers) -> (status, dict)`)
so tests never hit the network — same contract as github_issue.create_issue.
"""
from __future__ import annotations

import base64

from echolens.config import settings

TRACKERS = ("github", "linear", "jira")


class TrackerError(RuntimeError):
    pass


def _default_post(url: str, payload: dict, headers: dict) -> tuple[int, dict]:
    import httpx

    with httpx.Client(timeout=20) as c:
        r = c.post(url, json=payload, headers=headers)
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text[:200]}
        return r.status_code, data


def configured_trackers() -> dict[str, bool]:
    """Which trackers have every setting they need. Booleans only — no secrets."""
    return {
        "github": bool(settings.github_token),
        "linear": bool(settings.linear_api_key and settings.linear_team_id),
        "jira": bool(settings.jira_base_url and settings.jira_email
                     and settings.jira_api_token and settings.jira_project_key),
    }


# ── Linear ──────────────────────────────────────────────────────────────

_LINEAR_URL = "https://api.linear.app/graphql"
_LINEAR_MUTATION = """
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { id identifier url } }
}
""".strip()


def create_linear_issue(title: str, body: str, api_key: str | None = None,
                        team_id: str | None = None, post_fn=None) -> dict:
    """Open a Linear issue. Returns {number, url} (number is e.g. "ENG-123")."""
    api_key = api_key or settings.linear_api_key
    team_id = team_id or settings.linear_team_id
    if not api_key or not team_id:
        raise TrackerError("Linear is not configured — set LINEAR_API_KEY and LINEAR_TEAM_ID")
    post = post_fn or _default_post
    # Linear personal API keys go in Authorization as-is (no "Bearer").
    status, data = post(_LINEAR_URL, {
        "query": _LINEAR_MUTATION,
        "variables": {"input": {"teamId": team_id, "title": title, "description": body}},
    }, {"Authorization": api_key, "Content-Type": "application/json"})
    if status >= 300 or data.get("errors"):
        raise TrackerError(f"Linear API {status}: {str(data.get('errors') or data)[:200]}")
    result = (data.get("data") or {}).get("issueCreate") or {}
    issue = result.get("issue") or {}
    if not result.get("success") or not issue:
        raise TrackerError("Linear did not create the issue")
    return {"number": issue.get("identifier"), "url": issue.get("url")}


# ── Jira Cloud ──────────────────────────────────────────────────────────

def markdown_to_adf(body: str) -> dict:
    """Jira REST v3 wants Atlassian Document Format, not markdown.

    A faithful converter is a project of its own; a ticket only needs to be
    readable. Headings become headings, list lines become bullets, everything
    else a paragraph per line. Markdown that slips through is still legible.
    """
    content: list[dict] = []
    bullets: list[dict] = []

    def flush() -> None:
        if bullets:
            content.append({"type": "bulletList", "content": list(bullets)})
            bullets.clear()

    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if line.startswith("#"):
            flush()
            level = min(6, len(line) - len(line.lstrip("#")))
            text = line.lstrip("#").strip()
            if text:
                content.append({"type": "heading", "attrs": {"level": level},
                                "content": [{"type": "text", "text": text}]})
            continue
        stripped = line.lstrip()
        if stripped.startswith(("- ", "* ")):
            text = stripped[2:].strip() or " "
            bullets.append({"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text}]}]})
            continue
        flush()
        content.append({"type": "paragraph", "content": [{"type": "text", "text": line}]})
    flush()
    return {"type": "doc", "version": 1, "content": content or [
        {"type": "paragraph", "content": [{"type": "text", "text": "(no description)"}]}]}


def create_jira_issue(title: str, body: str, base_url: str | None = None,
                      email: str | None = None, api_token: str | None = None,
                      project_key: str | None = None, issue_type: str | None = None,
                      post_fn=None) -> dict:
    """Open a Jira Cloud issue via REST v3. Returns {number, url} (number is the key)."""
    base_url = (base_url or settings.jira_base_url).rstrip("/")
    email = email or settings.jira_email
    api_token = api_token or settings.jira_api_token
    project_key = project_key or settings.jira_project_key
    issue_type = issue_type or settings.jira_issue_type or "Task"
    if not (base_url and email and api_token and project_key):
        raise TrackerError("Jira is not configured — set JIRA_BASE_URL, JIRA_EMAIL, "
                           "JIRA_API_TOKEN and JIRA_PROJECT_KEY")
    if not base_url.startswith("https://"):
        raise TrackerError("JIRA_BASE_URL must be an https:// URL")
    auth = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    post = post_fn or _default_post
    status, data = post(f"{base_url}/rest/api/3/issue", {
        "fields": {
            "project": {"key": project_key},
            # Jira caps summary at 255 characters and rejects the whole request past it.
            "summary": title[:255],
            "description": markdown_to_adf(body),
            "issuetype": {"name": issue_type},
            "labels": ["echolens"],
        }
    }, {"Authorization": f"Basic {auth}", "Accept": "application/json",
        "Content-Type": "application/json"})
    if status >= 300 or not data.get("key"):
        raise TrackerError(f"Jira API {status}: {str(data.get('errors') or data)[:200]}")
    return {"number": data["key"], "url": f"{base_url}/browse/{data['key']}"}


def create_ticket(tracker: str, title: str, body: str, *, repo: str | None = None,
                  post_fn=None) -> dict:
    """One entry point for every tracker. GitHub keeps its own module (and its
    own post_fn shape) because fix-watch already links to it."""
    if tracker == "github":
        from echolens.integrations.github_issue import GitHubIssueError, create_issue
        try:
            return create_issue(repo or "", title, body, post_fn=post_fn)
        except GitHubIssueError as err:
            raise TrackerError(str(err)) from err
    if tracker == "linear":
        return create_linear_issue(title, body, post_fn=post_fn)
    if tracker == "jira":
        return create_jira_issue(title, body, post_fn=post_fn)
    raise TrackerError(f"unknown tracker '{tracker}' (expected one of {', '.join(TRACKERS)})")
