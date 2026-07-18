from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Release
from echolens.tools._util import parse_date, snippet


def get_release_notes(
    session: Session,
    version: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    stmt = select(Release).order_by(Release.released_at)
    if version:
        stmt = stmt.where(Release.version.like(f"{version}%"))
    if date_from:
        stmt = stmt.where(Release.released_at >= parse_date(date_from))
    if date_to:
        stmt = stmt.where(Release.released_at <= parse_date(date_to))
    rows = session.scalars(stmt).all()
    return {
        "returned": len(rows),
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
