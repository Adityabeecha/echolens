"""The unified feedback layer — one complaint, every voice.

The same problem arrives as a 1-star review, a GitHub issue, a support ticket
and a forum post. Until now each lived in its own table with its own columns, so
the system counted the same problem four times and called that four times the
evidence. It is not: it is one problem with four witnesses, and the witnesses
being *independent* is what makes it credible.

This module does two jobs:

1. **Normalise.** Review / Issue / Post / FeedbackEntry all become `FeedbackItem`,
   so everything downstream stops caring which table a complaint came from.
2. **Weight honestly.** Volume within one channel saturates; distinct channels
   compound. Forty people repeating themselves in one app store is weaker
   evidence than four people reporting the same thing in four places, and the
   scoring says so by construction rather than by a fudge factor.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import FeedbackEntry, Issue, Post, Review
from echolens.timeutil import aware_utc

# ── channels ────────────────────────────────────────────────────────────
# Who is speaking matters as much as what they say: an engineer filing a repro
# on GitHub and a user venting in a review are different kinds of witness, and
# the PM needs to know which ones are already aware of a problem.
CHANNELS: dict[str, dict] = {
    "play_store":  {"label": "Play Store",    "audience": "users",     "kind": "store"},
    "app_store":   {"label": "App Store",     "audience": "users",     "kind": "store"},
    "github":      {"label": "GitHub",        "audience": "engineers", "kind": "tracker"},
    "reddit":      {"label": "Reddit",        "audience": "community", "kind": "social"},
    "forum":       {"label": "Community forum", "audience": "community", "kind": "social"},
    "support":     {"label": "Support tickets", "audience": "support",  "kind": "helpdesk"},
    "in_app":      {"label": "In-app feedback", "audience": "users",   "kind": "direct"},
    "csv":         {"label": "Imported",      "audience": "users",     "kind": "import"},
}

# Per-channel evidence ceiling. No single channel can prove a problem on its own,
# however loud it gets — that ceiling is what makes breadth beat volume.
CHANNEL_CAP = 0.70
# How fast a channel saturates. ~3 corroborating items gets most of the way.
CHANNEL_RATE = 0.55


def channel_meta(channel: str) -> dict:
    return CHANNELS.get(channel, {"label": channel.replace("_", " ").title(),
                                  "audience": "users", "kind": "other"})


@dataclass
class FeedbackItem:
    """One piece of feedback from any channel, in the shape everything else uses."""
    ref: str                  # re-retrievable pointer, as evidence already uses
    channel: str
    text: str
    created_at: datetime | None
    product: str | None = None
    author_kind: str = "user"     # user | engineer | agent
    # per-item strength: an issue with 200 reactions or a P1 ticket carries more
    # than a passing one-liner. Bounded so no single item dominates.
    weight: float = 1.0
    meta: dict = field(default_factory=dict)

    @property
    def audience(self) -> str:
        return channel_meta(self.channel)["audience"]


def _norm_text(text: str | None) -> str:
    """Collapse whitespace/case/punctuation so the same sentence posted in two
    places is recognisably the same sentence."""
    return re.sub(r"[^a-z0-9 ]+", "", (text or "").lower()).strip()


def _reaction_weight(n: int | None) -> float:
    """Diminishing returns: 200 reactions is not 200x one reaction."""
    return round(min(3.0, 1.0 + math.log1p(max(0, n or 0)) / 2.0), 3)


# ── normalisation ───────────────────────────────────────────────────────


def collect_items(session: Session, product: str | None = None, *,
                  since: datetime | None = None, until: datetime | None = None,
                  negatives_only: bool = True) -> list[FeedbackItem]:
    """Every channel, one list, one shape.

    `negatives_only` keeps the complaint surface: a 5-star review and a closed
    'thanks!' ticket are not witnesses to a problem.
    """
    items: list[FeedbackItem] = []

    def in_window(dt) -> bool:
        d = aware_utc(dt)
        if d is None:
            return False
        if since is not None and d < since:
            return False
        if until is not None and d > until:
            return False
        return True

    # reviews (play store, app store, csv imports)
    r_stmt = select(Review)
    if product:
        r_stmt = r_stmt.where(Review.product == product)
    if negatives_only:
        r_stmt = r_stmt.where(Review.rating <= 2)
    for r in session.scalars(r_stmt).all():
        if not in_window(r.created_at) or not (r.text or "").strip():
            continue
        items.append(FeedbackItem(
            ref=r.ext_id, channel=(r.source or "play_store"), text=r.text,
            created_at=aware_utc(r.created_at), product=r.product,
            author_kind="user",
            # a 1-star is a stronger complaint signal than a 2-star
            weight=1.25 if (r.rating or 5) <= 1 else 1.0,
            meta={"rating": r.rating, "version": r.version}))

    # github issues — engineers, and already-aware by definition
    i_stmt = select(Issue)
    if product:
        i_stmt = i_stmt.where(Issue.product == product)
    for i in session.scalars(i_stmt).all():
        if not in_window(i.created_at):
            continue
        items.append(FeedbackItem(
            ref=f"issue {i.ext_id}", channel="github",
            text=f"{i.title}. {i.body_snippet or ''}".strip(),
            created_at=aware_utc(i.created_at), product=i.product,
            author_kind="engineer", weight=_reaction_weight(i.reactions),
            meta={"state": i.state, "reactions": i.reactions, "labels": i.labels}))

    # community posts
    p_stmt = select(Post)
    if product:
        p_stmt = p_stmt.where(Post.product == product)
    for p in session.scalars(p_stmt).all():
        if not in_window(p.created_at):
            continue
        items.append(FeedbackItem(
            ref=p.ext_id, channel=(p.source or "reddit"), text=p.text_snippet,
            created_at=aware_utc(p.created_at), product=p.product,
            author_kind="user", meta={"subreddit": p.subreddit}))

    # support tickets / in-app feedback / forums (the v10 channels)
    f_stmt = select(FeedbackEntry)
    if product:
        f_stmt = f_stmt.where(FeedbackEntry.product == product)
    for f in session.scalars(f_stmt).all():
        if not in_window(f.created_at) or not (f.text or "").strip():
            continue
        items.append(FeedbackItem(
            ref=f"{f.channel} {f.ext_id}", channel=f.channel, text=f.text,
            created_at=aware_utc(f.created_at), product=f.product,
            author_kind=f.author_kind or "user",
            weight=_priority_weight(f.priority),
            meta={"priority": f.priority, "status": f.status, **(f.meta_json or {})}))

    items.sort(key=lambda x: (x.created_at or datetime.min.replace(tzinfo=None)), reverse=True)
    return items


def _priority_weight(priority: str | None) -> float:
    return {"p0": 2.5, "urgent": 2.5, "p1": 2.0, "high": 2.0,
            "p2": 1.3, "normal": 1.0, "p3": 0.8, "low": 0.8}.get(
        (priority or "").strip().lower(), 1.0)


# ── deduplication ───────────────────────────────────────────────────────


def dedupe_witnesses(items: list[FeedbackItem]) -> tuple[list[FeedbackItem], int]:
    """Collapse the SAME complaint appearing in more than one place.

    A user who files a support ticket and then leaves a review saying the same
    thing is one person affected, not two. Counting them twice inflates impact
    precisely when a problem is being escalated — the worst time to be wrong.

    Returns (kept, collapsed_count). The kept item carries `also_seen_in` so the
    corroboration is preserved even though the count is not doubled.
    """
    by_text: dict[str, FeedbackItem] = {}
    collapsed = 0
    for item in items:
        key = _norm_text(item.text)[:180]
        if not key:
            continue
        prior = by_text.get(key)
        if prior is None:
            item.meta.setdefault("also_seen_in", [])
            by_text[key] = item
            continue
        if prior.channel == item.channel:
            collapsed += 1      # a straight duplicate within one channel
            continue
        # Same words, different channel: keep ONE witness but remember the reach.
        seen = prior.meta.setdefault("also_seen_in", [])
        if item.channel not in seen:
            seen.append(item.channel)
        collapsed += 1
    return list(by_text.values()), collapsed


# ── corroboration ───────────────────────────────────────────────────────


def channel_strength(n_items: int, weight_sum: float = 0.0) -> float:
    """How much ONE channel can prove, capped.

    Saturating on purpose: the tenth person saying the same thing in the same
    place is largely repeating the ninth, because they share a population, a
    prompt and a moment. The cap is the formal statement of "volume is not
    corroboration".
    """
    if n_items <= 0:
        return 0.0
    effective = max(float(n_items), weight_sum or 0.0)
    return round(CHANNEL_CAP * (1 - math.exp(-CHANNEL_RATE * effective)), 4)


def corroboration(items: list[FeedbackItem]) -> dict:
    """Score a problem by the independence of its witnesses.

    Channels are combined with a noisy-OR: each is an imperfect, independent
    observer, so they compound rather than add, and no amount of one channel can
    reach what several channels reach together.
    """
    kept, collapsed = dedupe_witnesses(items)
    by_channel: dict[str, list[FeedbackItem]] = {}
    for it in kept:
        by_channel.setdefault(it.channel, []).append(it)

    per_channel = {}
    miss = 1.0
    for ch, group in by_channel.items():
        s = channel_strength(len(group), sum(i.weight for i in group))
        per_channel[ch] = {
            "channel": ch, "label": channel_meta(ch)["label"],
            "audience": channel_meta(ch)["audience"],
            "witnesses": len(group), "strength": s,
        }
        miss *= (1 - s)

    score = round(1 - miss, 4)
    return {
        "score": score,
        "channels": sorted(per_channel.values(), key=lambda c: -c["strength"]),
        "distinct_channels": len(by_channel),
        "witnesses": len(kept),
        "collapsed_duplicates": collapsed,
        "band": ("corroborated" if len(by_channel) >= 3 else
                 "supported" if len(by_channel) == 2 else "single-source"),
    }


def channel_of_origin(corr: dict, configured: list[str]) -> dict:
    """Where a problem lives, and who has not noticed it.

    "Engineers report this on GitHub, users feel it in reviews, but support has
    never seen it" tells a PM who to talk to — and a problem absent from support
    while loud in reviews usually means users gave up rather than got helped.
    """
    present = {c["channel"] for c in corr["channels"]}
    silent = [c for c in configured if c not in present]
    loudest = corr["channels"][0] if corr["channels"] else None
    return {
        "present": [{"channel": c["channel"], "label": c["label"],
                     "audience": c["audience"], "witnesses": c["witnesses"]}
                    for c in corr["channels"]],
        "silent": [{"channel": c, "label": channel_meta(c)["label"],
                    "audience": channel_meta(c)["audience"]} for c in silent],
        "loudest": loudest["channel"] if loudest else None,
        "summary": _origin_sentence(corr["channels"], silent),
    }


def _origin_sentence(present: list[dict], silent: list[str]) -> str:
    if not present:
        return "No channel has reported this."
    said = ", ".join(f"{c['audience']} on {c['label']}" for c in present[:3])
    line = f"Reported by {said}"
    if silent:
        missing = ", ".join(channel_meta(c)["label"] for c in silent[:2])
        line += f" — nothing from {missing}"
    return line + "."


def configured_channels(session: Session, product: str | None = None) -> list[str]:
    """Channels this product actually has connected. Only these can be 'silent';
    a channel that was never wired up is not a meaningful absence."""
    from echolens.db.models import CollectorState
    stmt = select(CollectorState)
    if product:
        stmt = stmt.where(CollectorState.product == product)
    out = {s.source for s in session.scalars(stmt).all() if s.source}
    # anything that has actually delivered data counts as connected too
    for item in collect_items(session, product, negatives_only=False):
        out.add(item.channel)
    return sorted(out)


def window(days: int = 90, as_of: datetime | None = None) -> tuple[datetime, datetime]:
    end = as_of or datetime.now().astimezone()
    return end - timedelta(days=days), end
