"""One bad release, one incident — not four rows.

A broken update shows up in every detector at once: the 1-star spike, the
rating drop, the theme surge and the GitHub issue burst all fire for the same
week. Listing them as four unrelated signals asked the reviewer to notice the
connection themselves, and investigating each one paid four times for one root
cause.

Grouping here is presentation and routing only. Every member stays its own
AnomalyEvent, untouched, so triage, dedupe and investigate still work on each.
Two signals belong together when they are for the same product, their windows
overlap, and either

* both are product-wide rating signals (1-star spike, rating drop), or
* both are theme-shaped and their terms share a word.

Investigating an incident investigates its STRONGEST member (highest z) and
names the others in that anomaly's description, so the case knows the full
picture; the rest are recorded as merged into it rather than queued again.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Review, TriageDecision
from echolens.intent import count_intents
from echolens.themes.overrides import slug_words
from echolens.timeutil import aware_utc

PRODUCT_WIDE = ("negative_review_spike", "rating_drop")
THEMED = ("theme_volume_surge", "issue_velocity_surge")
GROUPABLE = PRODUCT_WIDE + THEMED
# Tie-break for the lead when z is equal: the broadest signal speaks for the rest.
_TYPE_RANK = {"negative_review_spike": 0, "rating_drop": 1,
              "theme_volume_surge": 2, "issue_velocity_surge": 3}

RELATED_MARKER = "Related signals in the same window"
INTENT_REVIEW_CAP = 5000


def _window(a: AnomalyEvent) -> tuple[datetime, datetime]:
    end = aware_utc(a.window_end) or aware_utc(a.created_at) or datetime.now(timezone.utc)
    start = aware_utc(a.window_start) or (end - timedelta(days=7))
    return start, end


def _overlap(a: AnomalyEvent, b: AnomalyEvent) -> bool:
    (s1, e1), (s2, e2) = _window(a), _window(b)
    return s1 <= e2 and s2 <= e1


def related(a: AnomalyEvent, b: AnomalyEvent) -> bool:
    if a.type not in GROUPABLE or b.type not in GROUPABLE:
        return False
    if a.product_id != b.product_id or not _overlap(a, b):
        return False
    if a.type in PRODUCT_WIDE and b.type in PRODUCT_WIDE:
        return True
    if a.type in THEMED and b.type in THEMED:
        return bool(slug_words(a.slug) & slug_words(b.slug))
    return False


def _lead(members: list[AnomalyEvent]) -> AnomalyEvent:
    return sorted(members, key=lambda a: (-(a.z or 0.0), _TYPE_RANK.get(a.type, 9), a.id))[0]


def group(anomalies: list[AnomalyEvent]) -> list[list[AnomalyEvent]]:
    """Connected components under `related`, lead first. Singletons included,
    so every input lands in exactly one group."""
    parent = list(range(len(anomalies)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(anomalies)):
        for j in range(i + 1, len(anomalies)):
            if related(anomalies[i], anomalies[j]):
                parent[find(i)] = find(j)
    comps: dict[int, list[AnomalyEvent]] = {}
    for i, a in enumerate(anomalies):
        comps.setdefault(find(i), []).append(a)
    out = []
    for members in comps.values():
        lead = _lead(members)
        out.append([lead] + sorted((m for m in members if m is not lead),
                                   key=lambda a: (-(a.z or 0.0), a.id)))
    return out


def waiting_groups(session: Session, product_ids: list[int] | None = None) -> list[list[AnomalyEvent]]:
    """The live Cases decisions, batched across products for portfolio/Ask.

    Match signal_rows eligibility: no case, no live queue entry, no latest
    ignore/merge decision, no muted theme. Do not use status=pending: status
    alone neither excludes a queued pick nor captures every waiting signal.
    """
    from sqlalchemy import func
    from echolens.db.models import Investigation, QueuedInvestigation, ThemeOverride
    from echolens.themes.overrides import is_muted_slug

    latest = (select(TriageDecision.decision)
              .where(TriageDecision.anomaly_id == AnomalyEvent.id)
              .order_by(TriageDecision.id.desc()).limit(1).scalar_subquery())
    stmt = select(AnomalyEvent).where(
        AnomalyEvent.merged_into_id.is_(None),
        ~select(Investigation.id).where(Investigation.anomaly_id == AnomalyEvent.id).exists(),
        ~select(QueuedInvestigation.id).where(
            QueuedInvestigation.anomaly_id == AnomalyEvent.id,
            QueuedInvestigation.status.in_(("queued", "running"))).exists(),
        func.coalesce(latest, "").not_in(("ignore", "merge")))
    overrides = select(ThemeOverride).where(ThemeOverride.muted == True)  # noqa: E712
    if product_ids is not None:
        stmt = stmt.where(AnomalyEvent.product_id.in_(product_ids))
        overrides = overrides.where(ThemeOverride.product_id.in_(product_ids))
    muted: dict[int, list[set[str]]] = {}
    for o in session.scalars(overrides).all():
        if o.product_id is not None:
            muted.setdefault(o.product_id, []).append(slug_words(o.slug))
    rows = [a for a in session.scalars(stmt).all()
            if a.type not in THEMED or not is_muted_slug(a.slug, muted.get(a.product_id, []))]
    groups = group(rows)
    # Same severity thresholds as Cases; compare incidents and singletons together.
    def strength(members):
        z = members[0].z or 0.0
        band = 3 if abs(z) >= 3 else 2 if abs(z) >= 2 else 1
        return -band, -z, members[0].id
    return sorted(groups, key=strength)


def waiting_rows(session: Session, product_id: int | None = None) -> list[dict]:
    """One lead/title/queue slug per incident, including standalone signals."""
    from echolens.cases import _headline
    return [{"id": members[0].id, "slug": members[0].slug,
             "title": _headline(members[0]), "metric": members[0].metric,
             "z": members[0].z, "members": [m.slug for m in members],
             "member_topics": [f"{_headline(m)} {m.metric or ''}" for m in members]}
            for members in waiting_groups(session, [product_id] if product_id is not None else None)]


# ── intents per signal ──────────────────────────────────────────────────

def _matcher(words: set[str]):
    if not words:
        return None
    rx = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in sorted(words)) + r")", re.I)
    return rx.search


def signal_intents(session: Session, product: str | None,
                   anomalies: list[AnomalyEvent]) -> dict[int, dict | None]:
    """{anomaly_id: intent counts} over the reviews behind each signal.

    One bounded query for the union of the windows, then per-signal filtering
    in Python. A GitHub issue burst has no reviews behind it, so it gets None
    rather than a row of zeros that would read as "measured, nothing found".
    """
    out: dict[int, dict | None] = {a.id: None for a in anomalies}
    wanted = [a for a in anomalies if a.type in PRODUCT_WIDE + ("theme_volume_surge",)]
    if not wanted or not product:
        return out
    windows = {a.id: _window(a) for a in wanted}
    lo = min(s for s, _ in windows.values())
    hi = max(e for _, e in windows.values())
    rows = session.execute(
        select(Review.text, Review.rating, Review.created_at)
        .where(Review.product == product,
               Review.created_at >= lo.replace(tzinfo=None) - timedelta(days=1),
               Review.created_at <= hi.replace(tzinfo=None) + timedelta(days=1))
        .order_by(Review.created_at.desc()).limit(INTENT_REVIEW_CAP)).all()
    dated = [(t, r, aware_utc(c)) for t, r, c in rows if c is not None]
    for a in wanted:
        start, end = windows[a.id]
        in_window = [(t, r) for t, r, c in dated if start <= c <= end]
        if a.type == "negative_review_spike":
            in_window = [(t, r) for t, r in in_window if r == 1]
        elif a.type == "theme_volume_surge":
            hit = _matcher(slug_words(a.slug))
            in_window = [(t, r) for t, r in in_window if hit and t and hit(t)]
        out[a.id] = count_intents(in_window) if in_window else None
    return out


def _sum(counts: list[dict | None]) -> dict | None:
    real = [c for c in counts if c]
    if not real:
        return None
    keys = set().union(*real)
    return {k: sum(c.get(k, 0) for c in real) for k in keys}


# ── the view ────────────────────────────────────────────────────────────

def incident_view(session: Session, product: str | None, signals: list[dict],
                  muted: list[set[str]] | None = None) -> tuple[list[dict], list[dict]]:
    """Signals enriched with intents (muted themes removed) plus the incidents
    grouping the live ones. Incidents reference member slugs; the members stay
    in `signals` so nothing that reads the flat list loses a row."""
    from echolens.themes.overrides import is_muted_slug

    if muted:
        signals = [s for s in signals
                   if s.get("type") not in THEMED or not is_muted_slug(s.get("slug"), muted)]
    ids = [s["id"] for s in signals if s.get("id") is not None]
    by_id = {a.id: a for a in session.scalars(
        select(AnomalyEvent).where(AnomalyEvent.id.in_(ids))).all()} if ids else {}
    intents = signal_intents(session, product, list(by_id.values()))
    for s in signals:
        s["intents"] = intents.get(s.get("id"))

    live = [by_id[s["id"]] for s in signals
            if not s.get("dismissed") and s.get("id") in by_id]
    sig_by_id = {s["id"]: s for s in signals if s.get("id") is not None}
    incidents = []
    for members in group(live):
        if len(members) < 2:
            continue
        lead = members[0]
        start = min(_window(m)[0] for m in members)
        end = max(_window(m)[1] for m in members)
        lead_sig = sig_by_id[lead.id]
        incidents.append({
            "key": f"incident-{lead.slug}",
            "lead": lead.slug,
            "title": lead_sig["title"],
            "members": [m.slug for m in members],
            "z": lead.z,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "intents": _sum([sig_by_id[m.id].get("intents") for m in members]),
        })
    return signals, incidents


def related_note(lead: AnomalyEvent, others: list[AnomalyEvent], title_of) -> str:
    lines = [f"- {title_of(o)} (z={o.z:.1f})" for o in others]
    return f"{RELATED_MARKER} (one incident, investigated together):\n" + "\n".join(lines)


def preserve_note(old: str | None, new: str) -> str:
    """Keep an incident note across a re-scan, which rewrites the description."""
    old = old or ""
    i = old.find(RELATED_MARKER)
    if i < 0 or RELATED_MARKER in new:
        return new
    return new.rstrip() + "\n\n" + old[i:]


def note_related(lead: AnomalyEvent, others: list[AnomalyEvent], title_of) -> None:
    """Name the other members on the lead's description, once, so the case
    that investigates the lead starts with the whole incident in view."""
    if others and RELATED_MARKER not in (lead.description or ""):
        lead.description = ((lead.description or "").rstrip() + "\n\n"
                            + related_note(lead, others, title_of)).strip()


def commit_incident(session: Session, lead_slug: str, product_id: int | None,
                    product: str | None) -> list[str]:
    """When the reviewer picks an incident: note the other members on the lead's
    description, and record them as merged into it (TriageDecision "merge",
    status "merged") so they are not queued again as separate cases. Returns
    the member slugs that were folded in; [] if the slug leads no incident."""
    from echolens.cases import _headline, signal_rows

    signals = signal_rows(session, product_id)
    _, incidents = incident_view(session, product, signals)
    inc = next((i for i in incidents if i["lead"] == lead_slug), None)
    if inc is None:
        return []
    rows = {a.slug: a for a in session.scalars(select(AnomalyEvent).where(
        AnomalyEvent.slug.in_(inc["members"]))).all()
        if product_id is None or a.product_id == product_id}
    lead = rows.get(lead_slug)
    if lead is None:
        return []
    others = [rows[s] for s in inc["members"][1:] if s in rows]
    note_related(lead, others, _headline)
    for o in others:
        session.add(TriageDecision(
            anomaly_id=o.id, decision="merge", merge_into_anomaly_id=lead.id,
            reason=f"Grouped into one incident with “{_headline(lead)}” — investigated together."))
        o.status = "merged"
    session.flush()
    return [o.slug for o in others]
