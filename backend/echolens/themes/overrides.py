"""Rename, merge and mute discovered themes — and make the corrections stick.

Discovery regenerates its names whenever new reviews arrive, so a correction
has to live beside it rather than in it. These overrides are applied AFTER the
themes are built and formatted (display_themes / titles, where present), keyed
by the same public slug the UI already holds, so they survive every refresh.

Muting reaches one step further than the list: the detector consults
`muted_word_sets` and stops raising NEW theme signals for a muted theme's
terms. Existing anomaly rows are left alone, so nothing already triaged or
investigated changes underneath anyone.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import ThemeOverride
from echolens.textkit import STOPWORDS

ACTIONS = ("rename", "merge", "mute", "unmute", "reset")
MAX_LABEL = 120

# Prefixes the app adds to a theme's identity: the public theme/request slugs
# from /feed/candidates, and the detector's product-scoped anomaly slugs.
_PREFIX = re.compile(r"^(?:(?:theme|request)-p\d+-|p\d+-)?(?:auto-(?:theme|post|issues)-)?")


def slug_words(slug: str | None) -> set[str]:
    """The content words a slug names: 'theme-p3-dropbox-sync-silent' ->
    {dropbox, sync, silent}. What mute and incident grouping compare on."""
    core = _PREFIX.sub("", (slug or "").lower())
    return {w for w in re.split(r"[^a-z0-9]+", core) if len(w) > 2 and w not in STOPWORDS}


def get_overrides(session: Session, product_id: int | None) -> dict[str, ThemeOverride]:
    stmt = select(ThemeOverride)
    stmt = (stmt.where(ThemeOverride.product_id == product_id) if product_id is not None
            else stmt.where(ThemeOverride.product_id.is_(None)))
    return {o.slug: o for o in session.scalars(stmt).all()}


def override_dicts(session: Session, product_id: int | None) -> list[dict]:
    return [{"slug": o.slug, "label": o.label, "merged_into": o.merged_into,
             "muted": bool(o.muted), "updated_by": o.updated_by,
             "updated_at": o.updated_at.isoformat() if o.updated_at else None}
            for o in sorted(get_overrides(session, product_id).values(), key=lambda o: o.slug)]


def _resolve(slug: str, overrides: dict[str, ThemeOverride]) -> str:
    """Follow merge chains to their end. A cycle stops where it started rather
    than looping — set_override refuses to create one, this is belt and braces."""
    seen = {slug}
    while True:
        o = overrides.get(slug)
        nxt = o.merged_into if o is not None else None
        if not nxt or nxt in seen:
            return slug
        seen.add(nxt)
        slug = nxt


def set_override(session: Session, product_id: int | None, slug: str, action: str, *,
                 label: str | None = None, into: str | None = None,
                 user: str | None = None) -> ThemeOverride | None:
    """Apply one correction. Returns the row, or None after a reset.

    Raises ValueError with a sentence the UI can show for anything invalid.
    """
    slug = (slug or "").strip()
    if not slug:
        raise ValueError("choose a theme first")
    if action not in ACTIONS:
        raise ValueError(f"unknown action '{action}'")
    overrides = get_overrides(session, product_id)
    row = overrides.get(slug)
    if action == "reset":
        if row is not None:
            session.delete(row)
            session.flush()
        return None
    if row is None:
        row = ThemeOverride(product_id=product_id, slug=slug, muted=False)
        session.add(row)
        overrides[slug] = row

    if action == "rename":
        text = " ".join((label or "").split())[:MAX_LABEL]
        row.label = text or None          # an empty rename restores the generated name
    elif action == "merge":
        target = (into or "").strip()
        if not target or target == slug:
            raise ValueError("pick a different theme to merge into")
        if _resolve(target, overrides) == slug:
            raise ValueError("those themes are already merged the other way round")
        row.merged_into = target
    elif action == "mute":
        row.muted = True
    elif action == "unmute":
        row.muted = False
    row.updated_by = user
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return row


def apply_overrides(items: list[dict], overrides: dict[str, ThemeOverride]) -> list[dict]:
    """Labels, merges and mutes applied to a list of theme-shaped dicts
    ({slug, statement, count, verbatims, intents?}). Order is preserved; a theme
    merged into another adds its count, quotes and intents to the target and
    disappears. Muted themes — and anything merged into a muted one — drop out.
    """
    if not overrides:
        return items
    out = [dict(t) for t in items]
    by_slug = {t["slug"]: t for t in out}
    for t in out:
        o = overrides.get(t["slug"])
        if o is not None and o.label:
            t.setdefault("original_statement", t.get("statement"))
            t["statement"] = o.label
            t["renamed"] = True

    dropped: set[str] = set()
    for t in out:
        target_slug = _resolve(t["slug"], overrides)
        if target_slug == t["slug"]:
            continue
        target = by_slug.get(target_slug)
        if target is None:
            continue                       # target not in this list: show as-is
        target["count"] = int(target.get("count") or 0) + int(t.get("count") or 0)
        quotes = list(target.get("verbatims") or [])
        for v in t.get("verbatims") or []:
            if v not in quotes:
                quotes.append(v)
        target["verbatims"] = quotes[:5]
        if isinstance(target.get("intents"), dict) and isinstance(t.get("intents"), dict):
            target["intents"] = {k: target["intents"].get(k, 0) + t["intents"].get(k, 0)
                                 for k in set(target["intents"]) | set(t["intents"])}
        target.setdefault("merged_from", []).append(t["slug"])
        dropped.add(t["slug"])

    muted = {s for s, o in overrides.items() if o.muted}
    return [t for t in out
            if t["slug"] not in dropped
            and t["slug"] not in muted
            and _resolve(t["slug"], overrides) not in muted]


def muted_word_sets(session: Session, product_id: int | None) -> list[set[str]]:
    """Word sets of every muted theme for this product, for the detector."""
    if product_id is None:
        return []
    return [w for w in (slug_words(o.slug) for o in get_overrides(session, product_id).values()
                        if o.muted) if w]


def is_muted_slug(slug: str | None, muted: list[set[str]]) -> bool:
    """A detector term is muted when every one of its words belongs to a muted
    theme: muting "Dropbox sync fails silently" silences the 'sync' surge, but
    not an unrelated 'sync speed' one that only shares a word."""
    words = slug_words(slug)
    return bool(words) and any(words <= m for m in muted)
