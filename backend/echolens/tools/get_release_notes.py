from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Release
from echolens.tools._util import cap_items, parse_date, snippet


def get_release_notes(
    session: Session,
    version: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    product: str | None = None,
) -> dict:
    stmt = select(Release).order_by(Release.released_at)
    if product:
        stmt = stmt.where(Release.product == product)
    if version:
        stmt = stmt.where(Release.version.like(f"{version}%"))
    if date_from:
        stmt = stmt.where(Release.released_at >= parse_date(date_from))
    if date_to:
        stmt = stmt.where(Release.released_at <= parse_date(date_to))
    rows = session.scalars(stmt).all()
    # Capped like every other tool. _util's docstring says "every tool truncates
    # its output before anything reaches LLM context"; this one did not, so a
    # mature product with 300 releases returned ~120KB of notes in a single tool
    # result, dumped whole into the next update prompt.
    rows, total = cap_items(list(rows))
    return {
        "returned": len(rows),
        "total_matching": total,
        "truncated": total > len(rows),
        "releases": [
            {
                "ref": f"release v{r.version}",
                "version": r.version,
                "released_at": r.released_at.date().isoformat(),
                "notes": snippet(r.notes, 400),
            }
            for r in rows
        ],
    }
