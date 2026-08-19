from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review
from echolens.tools._util import cap_items, match_score, parse_date, snippet, terms_of


def search_reviews(
    session: Session,
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    rating_max: int | None = None,
    rating_min: int | None = None,
    version_prefix: str | None = None,
    os_version: str | None = None,
    product: str | None = None,
    limit: int | None = None,
) -> dict:
    """Keyword search over reviews; supports version/OS segmentation
    (the decoy-killer: e.g. version_prefix='3.1', os_version='Android 15') and
    optional product scoping for multi-app workspaces."""
    stmt = select(Review)
    if product:
        stmt = stmt.where(Review.product == product)
    if date_from:
        stmt = stmt.where(Review.created_at >= parse_date(date_from))
    if date_to:
        stmt = stmt.where(Review.created_at <= parse_date(date_to))
    if rating_max is not None:
        stmt = stmt.where(Review.rating <= rating_max)
    if rating_min is not None:
        stmt = stmt.where(Review.rating >= rating_min)
    if version_prefix:
        stmt = stmt.where(Review.version.like(f"{version_prefix}%"))
    if os_version:
        stmt = stmt.where(Review.os_version == os_version)

    rows = session.scalars(stmt).all()
    terms = terms_of(query)
    scored = [(match_score(r.text, terms), r) for r in rows]
    matched = sorted(
        (sr for sr in scored if sr[0] > 0),
        key=lambda sr: (-sr[0], sr[1].created_at, sr[1].ext_id),
    )
    ranked = [r for _, r in matched]
    # v1.0: append semantically-close reviews the keywords missed (no-op until
    # the corpus is embedded — keyword results are never dropped or reordered).
    from echolens.search.semantic import augment
    ranked += augment(query, rows, set(ranked), lambda r: r.text, limit or 8)
    items, total = cap_items(ranked, limit)
    return {
        "total_matches": total,
        "returned": len(items),
        "reviews": [
            {
                "ref": r.ext_id,
                "rating": r.rating,
                "date": r.created_at.date().isoformat(),
                "version": r.version,
                "os": r.os_version,
                "snippet": snippet(r.text),
            }
            for r in items
        ],
    }
