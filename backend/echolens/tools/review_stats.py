from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review
from echolens.tools._util import parse_date, terms_of, match_score


def review_stats(
    session: Session,
    term: str,
    date_from: str | None = None,
    date_to: str | None = None,
    version_prefix: str | None = None,
    os_version: str | None = None,
    product: str | None = None,
) -> dict:
    """Daily counts of reviews mentioning `term`, share of negatives (<=2★),
    segmentable by version/OS/product. Pure counting — the agent interprets."""
    stmt = select(Review)
    if product:
        stmt = stmt.where(Review.product == product)
    if date_from:
        stmt = stmt.where(Review.created_at >= parse_date(date_from))
    if date_to:
        stmt = stmt.where(Review.created_at <= parse_date(date_to))
    if version_prefix:
        stmt = stmt.where(Review.version.like(f"{version_prefix}%"))
    if os_version:
        stmt = stmt.where(Review.os_version == os_version)
    rows = session.scalars(stmt).all()

    terms = terms_of(term)
    daily: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "neg": 0, "term": 0, "term_neg": 0})
    for r in rows:
        d = daily[r.created_at.date().isoformat()]
        d["total"] += 1
        hit = match_score(r.text, terms) > 0
        if hit:
            d["term"] += 1
        if r.rating <= 2:
            d["neg"] += 1
            if hit:
                d["term_neg"] += 1

    days = sorted(daily)
    total_neg = sum(daily[d]["neg"] for d in days)
    total_term_neg = sum(daily[d]["term_neg"] for d in days)
    return {
        "term": term,
        "segment": {"version_prefix": version_prefix, "os_version": os_version},
        "days": len(days),
        "total_reviews": sum(daily[d]["total"] for d in days),
        "total_negatives": total_neg,
        "term_mentions_in_negatives": total_term_neg,
        "term_share_of_negatives_pct": round(100 * total_term_neg / total_neg, 1) if total_neg else 0.0,
        # compact tail so long ranges don't blow up context
        "daily_tail": [
            {"date": d, "neg": daily[d]["neg"], "term_neg": daily[d]["term_neg"]}
            for d in days[-14:]
        ],
    }
