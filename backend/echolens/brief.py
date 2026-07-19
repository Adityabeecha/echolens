"""The weekly brief (v7.0) — the artifact that keeps EchoLens open on Monday.

Five cited lines: new problems by impact, fixes verified, regressions, and ONE
"what to fix next" ranked by severity × volume × persistence × (1 − resolution
rate). Every claim points at a case. Sent unprompted by the scheduled job.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Finding, FixWatch, Investigation
from echolens.impact import severity
from echolens.timeutil import aware_utc


def _recent(dt, since) -> bool:
    dt = aware_utc(dt)
    return dt is not None and dt >= since


def _resolution_rate(session: Session) -> float:
    resolved = session.scalars(select(Investigation).where(Investigation.status == "resolved")).all()
    confirmed = [w for w in session.scalars(select(FixWatch)).all() if w.status == "confirmed"]
    return round(len(confirmed) / len(resolved), 3) if resolved else 0.0


def _fix_next(session: Session, resolution_rate: float, now) -> dict | None:
    """Rank open problems by severity × volume × persistence × (1 − resolution)."""
    confirmed = {w.investigation_id for w in session.scalars(select(FixWatch)).all() if w.status == "confirmed"}
    best, best_score = None, -1.0
    for inv in session.scalars(select(Investigation).where(Investigation.status == "resolved")).all():
        if inv.id in confirmed:
            continue
        f = session.scalars(select(Finding).where(
            Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
        if f is None:
            continue
        impact = (f.json or {}).get("impact", {})
        sev = severity(float(f.confidence or 0.0), impact)["score"]
        volume = impact.get("affected_volume", 0) or 0
        persistence = max(1, (now - (aware_utc(inv.created_at) or now)).days)
        score = sev * (volume + 1) * persistence * (1 - resolution_rate)
        if score > best_score:
            best, best_score = (f, inv), score
    if best is None:
        return None
    f, inv = best
    return {"investigation_id": inv.id, "summary": f.summary, "score": round(best_score, 2)}


def weekly_brief(session: Session, as_of: datetime | None = None) -> dict:
    now = as_of or datetime.now(timezone.utc)
    since = now - timedelta(days=7)

    new_problems = []
    for inv in session.scalars(select(Investigation).where(Investigation.status == "resolved")).all():
        if not _recent(inv.created_at, since):
            continue
        f = session.scalars(select(Finding).where(
            Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
        if f is not None:
            impact = (f.json or {}).get("impact", {})
            new_problems.append({"investigation_id": inv.id, "summary": f.summary,
                                 "impact_score": impact.get("impact_score", 0.0)})
    new_problems.sort(key=lambda p: -p["impact_score"])

    fixes_verified = [{"investigation_id": w.investigation_id, "metric": w.metric}
                      for w in session.scalars(select(FixWatch)).all()
                      if w.status == "confirmed" and _recent(w.confirmed_at, since)]
    regressions = [{"slug": a.slug, "parent_case_id": a.parent_case_id}
                   for a in session.scalars(select(AnomalyEvent).where(
                       AnomalyEvent.type == "regression")).all() if _recent(a.created_at, since)]

    rate = _resolution_rate(session)
    fix_next = _fix_next(session, rate, now)

    # chronic themes (context for the brief)
    from echolens.themes import theme_lifecycle
    chronic = [t for t in theme_lifecycle(session, now) if t["status"] == "chronic"]

    lines = [
        f"This week: {len(new_problems)} new problem(s), {len(fixes_verified)} fix(es) verified, "
        f"{len(regressions)} regression(s). Resolution rate {int(rate*100)}%.",
    ]
    for p in new_problems[:2]:
        lines.append(f"• New: {p['summary']} (case #{p['investigation_id']}).")
    if chronic:
        lines.append(f"• Chronic: “{chronic[0]['label']}” unresolved {chronic[0]['age_days']}d "
                     f"(case #{chronic[0]['cases'][0]}).")
    if fix_next:
        lines.append(f"→ Fix next: {fix_next['summary']} (case #{fix_next['investigation_id']}).")

    return {
        "generated": now.date().isoformat(),
        "resolution_rate": rate,
        "new_problems": new_problems,
        "fixes_verified": fixes_verified,
        "regressions": regressions,
        "chronic_themes": chronic,
        "fix_next": fix_next,
        "lines": lines[:5],
    }
