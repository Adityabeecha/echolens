from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Post
from echolens.tools._util import cap_items, match_score, parse_date, snippet, terms_of


def search_reddit(
    session: Session,
    query: str,
    subreddit: str | None = None,
    since: str | None = None,
    product: str | None = None,
    limit: int | None = None,
) -> dict:
    stmt = select(Post)
    if product:
        stmt = stmt.where(Post.product == product)
    if subreddit:
        stmt = stmt.where(Post.subreddit == subreddit)
    if since:
        stmt = stmt.where(Post.created_at >= parse_date(since))
    rows = session.scalars(stmt).all()

    terms = terms_of(query)
    scored = [(match_score(p.text_snippet, terms), p) for p in rows]
    matched = sorted(
        (sp for sp in scored if sp[0] > 0),
        key=lambda sp: (-sp[0], sp[1].created_at, sp[1].ext_id),
    )
    ranked = [p for _, p in matched]
    from echolens.search.semantic import augment
    ranked += augment(query, rows, set(ranked), lambda p: p.text_snippet, limit or 8)
    items, total = cap_items(ranked, limit)
    return {
        "total_matches": total,
        "returned": len(items),
        "posts": [
            {
                "ref": p.ext_id,
                "subreddit": p.subreddit,
                "date": p.created_at.date().isoformat(),
                "snippet": snippet(p.text_snippet),
            }
            for p in items
        ],
    }
