"""get_release_changes: what actually changed in the code between two releases.

Release notes say what a team CHOSE to announce. The commits and pull requests
between two tags say what shipped — "enable background photo sync by default
(#412)" is the kind of line that turns a guess about a release into a cause.

Read-only and bounded: commit subjects, PR titles (parsed from the merge and
squash messages, so no extra API calls), changed file paths, and at most a
short excerpt of a few patches. Never a diff body. Only for products with a
connected GitHub repository; the network call is injectable.
"""
from __future__ import annotations

import re
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import CollectorState, Release
from echolens.tools._util import cap_items, parse_date, snippet

MAX_FILES = 30
EXCERPT_FILES = 5
EXCERPT_CHARS = 160

# "Merge pull request #412 from org/branch\n\nEnable background sync" (merge)
# and "Enable background sync (#412)" (squash).
_MERGE = re.compile(r"^Merge pull request #(\d+)\b")
_SQUASH = re.compile(r"\(#(\d+)\)\s*$")

FetchFn = Callable[[str, str, str], dict]


def _repo_for(session: Session, product: str | None) -> str | None:
    """THIS product's connected repo. One repo or none: with several connected
    there is no honest way to pick, so the tool declines rather than guess."""
    stmt = select(CollectorState).where(CollectorState.source == "github",
                                        CollectorState.enabled == True)  # noqa: E712
    if product:
        stmt = stmt.where(CollectorState.product == product)
    repos = {s.identifier for s in session.scalars(stmt).all() if s.identifier}
    return repos.pop() if len(repos) == 1 else None


def _releases(session: Session, product: str | None) -> list[Release]:
    stmt = select(Release).order_by(Release.released_at)
    if product:
        stmt = stmt.where(Release.product == product)
    return list(session.scalars(stmt).all())


def _normalise(version: str) -> str:
    v = str(version).strip()
    return v[1:] if v[:1] in ("v", "V") and v[1:2].isdigit() else v


def _pick_range(rels: list[Release], version: str | None, date_from: str | None,
                date_to: str | None) -> tuple[Release, Release] | None:
    """(base, head): the release before the one asked about, and that one."""
    if len(rels) < 2:
        return None
    if version:
        want = _normalise(version)
        idx = next((i for i, r in enumerate(rels) if _normalise(r.version) == want), None)
        if idx is None:   # "3.2" → the first 3.2.x
            idx = next((i for i, r in enumerate(rels)
                        if _normalise(r.version).startswith(want)), None)
        if idx is None or idx == 0:
            return None
        return rels[idx - 1], rels[idx]
    start, end = parse_date(date_from), parse_date(date_to, end_of_day=True)

    def aware(r: Release):
        d = r.released_at
        return d if d.tzinfo else d.replace(tzinfo=(start or end).tzinfo)

    inside = [i for i, r in enumerate(rels)
              if (start is None or aware(r) >= start) and (end is None or aware(r) <= end)]
    if not inside:
        return None
    head_i = inside[-1]
    base_i = inside[0] - 1 if inside[0] > 0 else None
    if base_i is None:
        return None
    return rels[base_i], rels[head_i]


def get_release_changes(
    session: Session,
    version: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    product: str | None = None,
    fetch_fn: FetchFn | None = None,
) -> dict:
    repo = _repo_for(session, product)
    if repo is None:
        return {"available": False, "commits": [], "files": [],
                "note": "No GitHub repository is connected for this product (or more than "
                        "one is), so code changes between releases cannot be read."}
    if not version and not (date_from or date_to):
        raise ValueError("get_release_changes: give a version, or a date_from/date_to range")
    pair = _pick_range(_releases(session, product), version, date_from, date_to)
    if pair is None:
        return {"available": False, "repo": repo, "commits": [], "files": [],
                "note": "Could not find two release tags bracketing that version or range."}
    base, head = pair
    if fetch_fn is None:
        from echolens.collectors.github import fetch_compare
        fetch_fn = fetch_compare
    data = fetch_fn(repo, base.version, head.version) or {}

    commits = []
    for c in data.get("commits") or []:
        message = ((c.get("commit") or {}).get("message") or "").strip()
        lines = [ln.strip() for ln in message.splitlines() if ln.strip()]
        subject = lines[0] if lines else ""
        pr, title = None, None
        if m := _MERGE.match(subject):
            pr, title = int(m.group(1)), (lines[1] if len(lines) > 1 else None)
        elif m := _SQUASH.search(subject):
            pr, title = int(m.group(1)), _SQUASH.sub("", subject).strip()
        sha = str(c.get("sha") or "")[:7]
        commits.append({
            "ref": f"commit {sha}",
            "message": snippet(subject, 160),
            "pr": pr, "pr_title": snippet(title, 160) if title else None,
            "date": (((c.get("commit") or {}).get("author") or {}).get("date") or "")[:10] or None,
        })
    shown, total_commits = cap_items(commits)

    files = []
    for i, f in enumerate((data.get("files") or [])[:MAX_FILES]):
        path = f.get("filename") or ""
        entry = {"ref": f"file {path} @ {head.version}", "path": path,
                 "status": f.get("status"),
                 "changes": f.get("changes", (f.get("additions") or 0) + (f.get("deletions") or 0))}
        if i < EXCERPT_FILES and f.get("patch"):
            entry["excerpt"] = snippet(f["patch"], EXCERPT_CHARS)
        files.append(entry)

    return {
        "available": True,
        "repo": repo,
        "base": base.version, "head": head.version,
        "head_released_at": head.released_at.date().isoformat(),
        "total_commits": total_commits,
        "returned_commits": len(shown),
        "truncated": total_commits > len(shown) or len(data.get("files") or []) > MAX_FILES,
        "commits": shown,
        "total_files": len(data.get("files") or []),
        "files": files,
    }
