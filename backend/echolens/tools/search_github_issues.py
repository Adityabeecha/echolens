from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Issue
from echolens.tools._util import cap_items, match_score, parse_date, snippet, terms_of


def search_github_issues(
    session: Session,
    query: str,
    state: str | None = None,
    since: str | None = None,
    product: str | None = None,
    limit: int | None = None,
) -> dict:
    stmt = select(Issue)
    if product:
        stmt = stmt.where(Issue.product == product)
    if state:
        stmt = stmt.where(Issue.state == state)
    if since:
        stmt = stmt.where(Issue.created_at >= parse_date(since))
    rows = session.scalars(stmt).all()

    terms = terms_of(query)
    scored = [(match_score(i.title + " " + i.body_snippet, terms), i) for i in rows]
    matched = sorted(
        (si for si in scored if si[0] > 0),
        key=lambda si: (-si[0], -si[1].reactions, si[1].ext_id),
    )
    ranked = [i for _, i in matched]
    from echolens.search.semantic import augment
    ranked += augment(query, rows, set(ranked), lambda i: f"{i.title} {i.body_snippet}", limit or 8)
    items, total = cap_items(ranked, limit)
    return {
        "total_matches": total,
        "returned": len(items),
        "issues": [
            {
                "ref": f"issue {i.ext_id}",
                "title": i.title,
                "state": i.state,
                "reactions": i.reactions,
                "date": i.created_at.date().isoformat(),
                "snippet": snippet(i.body_snippet),
            }
            for i in items
        ],
    }
