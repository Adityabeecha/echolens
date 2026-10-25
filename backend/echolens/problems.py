"""The Problems screen's server side: what each new spike is about, how strong
it is, why a dismissed one was dismissed — in plain words — and the batch
actions a reviewer takes on several spikes at once (merge into one problem,
dismiss with a reason).

Everything here is deterministic: the category comes from echolens.intent's
cue words, strength from the detector's own z-score bands, and a dismissal
reason from the recorded TriageDecision. Nothing calls a model.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Investigation, QueuedInvestigation, TriageDecision
from echolens.detector.detect import SEV1_Z, SEV2_Z
from echolens.intent import FEATURE_REQUEST, spike_category

STRONG_Z, MEDIUM_Z = SEV1_Z, SEV2_Z   # the detector's SEV1 / SEV2 bands
DISMISSED_BY = "Dismissed by "
MAX_BATCH = 100


def strength(z: float | None) -> str:
    """strong / medium / weak, from the detector's own severity bands."""
    z = float(z or 0.0)
    return "strong" if z >= STRONG_Z else "medium" if z >= MEDIUM_Z else "weak"


def _ruled_out(reason: str | None) -> str:
    text = " ".join((reason or "").split()).rstrip(".")
    return f"Ruled out when triaged: {text[0].lower()}{text[1:]}." if text else "Ruled out when triaged."


def dismissal_reason(signal: dict, case_for_anomaly: dict[int, int],
                     titles: dict[int, str]) -> str:
    """Why this spike is not being looked into, in words a person can check.

    `case_for_anomaly` maps an anomaly id to the problem (investigation) that
    grew from it; `titles` maps anomaly ids to their headlines.
    """
    if signal.get("muted"):
        return "You muted this topic"
    if signal.get("dismissed_decision") == "merge":
        target = signal.get("merge_into_anomaly_id")
        if target in case_for_anomaly:
            return f"Merged into problem #{case_for_anomaly[target]}"
        if target in titles:
            return f"Merged into “{titles[target]}”"
        return "Merged into another spike"
    reason = signal.get("dismissed_reason") or ""
    if reason.startswith(DISMISSED_BY):
        return reason
    if signal.get("category") == FEATURE_REQUEST:
        return "A feature request"
    z = float(signal.get("z") or 0.0)
    if z < MEDIUM_Z and signal.get("type") not in ("issue_velocity_surge", "low_volume_watch"):
        return f"Too weak to matter (strength {z:.1f})"
    return _ruled_out(reason)


def annotate_spikes(session: Session, signals: list[dict], incidents: list[dict],
                    muted: list[dict] | None = None) -> list[dict]:
    """Adds `category`, `strength` and, on dismissed ones, `dismissed_why` to
    every signal and incident. `muted` are signals a muted theme hid; they come
    back dismissed so the screen can say why they are not listed above.
    Returns the full signal list (muted ones last)."""
    rows = list(signals) + [{**m, "dismissed": True, "muted": True} for m in (muted or [])]
    for s in rows:
        # The headline is generic for some types ("1-star reviews are
        # spiking"); the metric names the topic ("battery share of …").
        s["category"] = spike_category([s.get("title"), s.get("metric")], s.get("intents"))
        s["strength"] = strength(s.get("z"))
    for inc in incidents:
        inc["category"] = spike_category([inc.get("title")], inc.get("intents"))
        inc["strength"] = strength(inc.get("z"))

    targets = {s["merge_into_anomaly_id"] for s in rows if s.get("merge_into_anomaly_id")}
    case_for: dict[int, int] = {}
    titles = {s["id"]: s["title"] for s in rows if s.get("id") is not None}
    if targets:
        # One query, and only when something was merged.
        for inv_id, a_id in session.execute(select(Investigation.id, Investigation.anomaly_id).where(
                Investigation.anomaly_id.in_(targets)).order_by(Investigation.id)).all():
            case_for.setdefault(a_id, inv_id)
        # A lead that was queued has left the signal list: fetch its headline.
        missing = targets - set(case_for) - set(titles)
        if missing:
            from echolens.cases import _headline
            for a in session.scalars(select(AnomalyEvent).where(AnomalyEvent.id.in_(missing))).all():
                titles[a.id] = _headline(a)
    for s in rows:
        if s.get("dismissed"):
            s["dismissed_why"] = dismissal_reason(s, case_for, titles)
    return rows


# ── batch actions ───────────────────────────────────────────────────────

def _open_spikes(session: Session, product_id: int | None, slugs: list[str]) -> list[AnomalyEvent]:
    """The named spikes of THIS product that are still undecided: not a case,
    not queued, not merged away. Order follows `slugs`."""
    wanted = list(dict.fromkeys(s for s in slugs if s))[:MAX_BATCH]
    if not wanted:
        return []
    stmt = select(AnomalyEvent).where(AnomalyEvent.slug.in_(wanted),
                                      AnomalyEvent.merged_into_id.is_(None))
    if product_id is not None:
        stmt = stmt.where(AnomalyEvent.product_id == product_id)
    found = {a.slug: a for a in session.scalars(stmt).all()}
    ids = [a.id for a in found.values()]
    if ids:
        taken = {i for (i,) in session.execute(select(Investigation.anomaly_id).where(
            Investigation.anomaly_id.in_(ids))).all()}
        taken |= {i for (i,) in session.execute(select(QueuedInvestigation.anomaly_id).where(
            QueuedInvestigation.anomaly_id.in_(ids),
            QueuedInvestigation.status.in_(("queued", "running")))).all()}
        found = {k: a for k, a in found.items() if a.id not in taken}
    return [found[s] for s in wanted if s in found]


def merge_spikes(session: Session, product_id: int | None, slugs: list[str],
                 by: str) -> dict:
    """Fold several spikes into ONE problem: the strongest leads, the others are
    named on its description and recorded as merged into it. The caller queues
    the lead. Needs at least two open spikes."""
    from echolens.cases import _headline
    from echolens.detector.incidents import note_related

    spikes = _open_spikes(session, product_id, slugs)
    if len(spikes) < 2:
        raise ValueError("Pick at least two new spikes to merge into one problem.")
    lead = max(spikes, key=lambda a: (float(a.z or 0.0), -spikes.index(a)))
    others = [a for a in spikes if a.id != lead.id]
    note_related(lead, others, _headline)
    title = _headline(lead)
    for o in others:
        session.add(TriageDecision(
            anomaly_id=o.id, decision="merge", merge_into_anomaly_id=lead.id,
            reason=f"Merged by {by} into one problem with “{title}”."))
        o.status = "merged"
    session.flush()
    return {"lead": lead.slug, "title": title, "merged": [o.slug for o in others],
            "skipped": [s for s in dict.fromkeys(slugs) if s not in {a.slug for a in spikes}]}


def dismiss_spikes(session: Session, product_id: int | None, slugs: list[str],
                   reason: str, by: str) -> dict:
    """Dismiss open spikes with a person's reason, recorded so the screen can
    always say who dismissed it and why."""
    reason = " ".join((reason or "").split())
    if not reason:
        raise ValueError("Say why — the reason is shown next to each dismissed spike.")
    spikes = _open_spikes(session, product_id, slugs)
    for a in spikes:
        session.add(TriageDecision(anomaly_id=a.id, decision="ignore",
                                   reason=f"{DISMISSED_BY}{by}: {reason}"))
        a.status = "ignored"
    session.flush()
    done = {a.slug for a in spikes}
    return {"dismissed": [a.slug for a in spikes],
            "skipped": [s for s in dict.fromkeys(slugs) if s not in done]}
