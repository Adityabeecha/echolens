from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from echolens.db.models import Review
from echolens.textkit import needs_translation
from echolens.tools._util import cap_items, match_score, parse_date, snippet, terms_of
from echolens.translate import analysis_text


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
    # The embedding is never needed here: semantic.augment reads it for a
    # bounded set of ids. Loading it per row was ~1 KB of JSON each.
    stmt = select(Review).options(defer(Review.embedding))
    if product:
        stmt = stmt.where(Review.product == product)
    if date_from:
        stmt = stmt.where(Review.created_at >= parse_date(date_from))
    if date_to:
        stmt = stmt.where(Review.created_at <= parse_date(date_to, end_of_day=True))
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
    # Matched on the English translation when there is one; the snippet below
    # is always the original text, so evidence quotes stay verbatim.
    scored = [(match_score(analysis_text(r), terms), r) for r in rows]
    matched = sorted(
        (sr for sr in scored if sr[0] > 0),
        key=lambda sr: (-sr[0], sr[1].created_at, sr[1].ext_id),
    )
    ranked = [r for _, r in matched]
    # v1.0: append semantically-close reviews the keywords missed (no-op until
    # the corpus is embedded — keyword results are never dropped or reordered).
    from echolens.search.semantic import augment
    ranked += augment(query, rows, set(ranked), analysis_text, limit or 8,
                      session=session, model=Review)
    items, total = cap_items(ranked, limit)
    hint = _widen_hint(session, terms, product, date_from or date_to, version_prefix, os_version,
                       rating_min, rating_max) if total == 0 else None
    return {
        **({"hint": hint} if hint else {}),
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
                # Only for non-English rows: says what language the quote is in.
                **({"lang": r.lang} if needs_translation(r.lang) else {}),
            }
            for r in items
        ],
    }


def _widen_hint(session: Session, terms: list[str], product: str | None, dated, version_prefix,
                os_version, rating_min, rating_max) -> str | None:
    """Why a filtered search came back empty, when the words alone do match.
    Brave's case asked for "ad blocker shield YouTube crash" inside a narrow
    window, got 0, and spent its last steps re-asking the same way."""
    if not terms or not (dated or version_prefix or os_version or rating_min is not None
                         or rating_max is not None):
        return None
    stmt = select(Review.text, Review.created_at)
    if product:
        stmt = stmt.where(Review.product == product)
    hits = [at for text, at in session.execute(stmt).all() if match_score(text or "", terms) > 0]
    if not hits:
        return None
    return (f"0 within these filters, but {len(hits)} reviews match the words with no filters "
            f"({min(hits).date().isoformat()} to {max(hits).date().isoformat()}). "
            "Widen or drop the date/version/rating filters.")
