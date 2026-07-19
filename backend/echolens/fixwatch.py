"""Closed-loop fix verification (v6.0) — "did the fix actually work?"

When a finding's GitHub issue closes, we open a monitoring window on the exact
complaint theme the finding was about and measure whether it actually went away.
Deterministic counting over the corpus; no LLM.

Lifecycle: link_issue → on_issue_closed → evaluate → (confirmed | reopened),
then check_regressions can later flip a confirmed fix back to regressed.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Finding, FixWatch, Investigation, Review
from echolens.detector.detect import reference_now
from echolens.impact import theme_terms
from echolens.timeutil import aware_utc
from echolens.tools._util import match_score

CONFIRM_DROP = 0.4    # post-fix rate ≤ 40% of baseline → the fix worked
PERSIST_KEEP = 0.6    # post-fix rate ≥ 60% of baseline at window end → it didn't
REGRESS_BACK = 0.8    # a confirmed theme back to ≥80% of baseline → regression
REGRESS_WINDOW = 7    # a regression is a RECENT re-spike, measured tight so it isn't diluted


def _terms_for(session: Session, finding: Finding) -> list[str]:
    inv = session.get(Investigation, finding.investigation_id)
    anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv else None
    return theme_terms(anomaly, finding.json or {})


def complaint_series(session: Session, terms: list[str], start: datetime, end: datetime) -> list[dict]:
    """Per-day count of negative reviews (≤2★) matching the theme in [start, end]."""
    rows = session.scalars(select(Review).where(Review.rating <= 2)).all()
    daily: dict = defaultdict(int)
    d = start.date()
    while d <= end.date():
        daily[d] = 0
        d += timedelta(days=1)
    for r in rows:
        day = aware_utc(r.created_at).date()
        if start.date() <= day <= end.date() and (not terms or match_score(r.text, terms) > 0):
            daily[day] += 1
    return [{"date": d.isoformat(), "count": daily[d]} for d in sorted(daily)]


def _rate(session: Session, terms: list[str], start: datetime, end: datetime) -> float:
    """Average daily matching-negative-review count over the window."""
    series = complaint_series(session, terms, start, end)
    return round(sum(s["count"] for s in series) / max(1, len(series)), 3)


def link_issue(session: Session, finding: Finding, repo: str, issue_number: int,
               issue_url: str = "") -> FixWatch:
    """Record the finding↔issue link at issue-creation time so the webhook can
    match a later 'closed' event back to this finding (idempotent)."""
    existing = session.scalars(select(FixWatch).where(
        FixWatch.repo == repo, FixWatch.issue_number == issue_number)).first()
    if existing:
        return existing
    inv = session.get(Investigation, finding.investigation_id)
    anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv else None
    watch = FixWatch(
        finding_id=finding.id, investigation_id=finding.investigation_id,
        repo=repo, issue_number=issue_number, issue_url=issue_url, status="issue_open",
        terms=_terms_for(session, finding), metric=(anomaly.metric if anomaly else ""),
    )
    session.add(watch)
    session.flush()
    return watch


def on_issue_closed(session: Session, repo: str, issue_number: int,
                    closed_at: datetime | None = None) -> FixWatch | None:
    """A GitHub issue closed → start the monitoring window and record the pre-fix
    baseline complaint rate."""
    watch = session.scalars(select(FixWatch).where(
        FixWatch.repo == repo, FixWatch.issue_number == issue_number)).first()
    if watch is None or watch.status not in ("issue_open",):
        return watch
    fix_date = aware_utc(closed_at) or reference_now(session)
    watch.fix_date = fix_date
    watch.status = "watching"
    watch.baseline_rate = _rate(session, watch.terms, fix_date - timedelta(days=watch.window_days), fix_date)
    session.flush()
    return watch


def before_after(session: Session, watch: FixWatch) -> dict:
    """The before/after complaint-rate chart data (the artifact a PM pastes into
    their review)."""
    if not watch.fix_date:
        return {}
    fix = aware_utc(watch.fix_date)
    w = timedelta(days=watch.window_days)
    pre = complaint_series(session, watch.terms, fix - w, fix)
    post = complaint_series(session, watch.terms, fix, fix + w)
    return {
        "fix_date": fix.date().isoformat(), "window_days": watch.window_days,
        "before": pre, "after": post,
        "before_rate": watch.baseline_rate, "after_rate": watch.post_rate,
        "metric": watch.metric, "terms": watch.terms,
    }


def evaluate(session: Session, as_of: datetime | None = None) -> list[dict]:
    """Advance every watching fix. Confirms fixes that worked and re-opens the
    ones that didn't — unprompted (this is what the scheduled job calls)."""
    now = aware_utc(as_of) or reference_now(session)
    out = []
    for watch in session.scalars(select(FixWatch).where(FixWatch.status == "watching")).all():
        fix = aware_utc(watch.fix_date)
        window_end = fix + timedelta(days=watch.window_days)
        post = _rate(session, watch.terms, fix, min(now, window_end))
        watch.post_rate = post
        base = watch.baseline_rate or 0.0
        window_over = now >= window_end
        result = "watching"
        if base > 0 and post <= base * CONFIRM_DROP:
            result = _confirm(session, watch)
        elif window_over and (base == 0 or post >= base * PERSIST_KEEP):
            result = _reopen(session, watch)
        elif window_over:  # elapsed, ambiguous improvement → still call it confirmed
            result = _confirm(session, watch)
        session.flush()
        out.append({"watch_id": watch.id, "finding_id": watch.finding_id,
                    "status": result, "baseline_rate": base, "post_rate": post})
    return out


def _confirm(session: Session, watch: FixWatch) -> str:
    watch.status = "confirmed"
    watch.confirmed_at = reference_now(session)
    watch.chart_json = before_after(session, watch)
    return "confirmed"


def _reopen(session: Session, watch: FixWatch) -> str:
    """Fix shipped but the complaints continue → re-open with prior context."""
    watch.status = "persists_reopened"
    watch.chart_json = before_after(session, watch)
    orig = session.get(Investigation, watch.investigation_id)
    finding = session.get(Finding, watch.finding_id)
    note = (f"A fix was shipped (issue #{watch.issue_number} closed) but '{watch.metric}' "
            f"complaints persist (baseline {watch.baseline_rate} → {watch.post_rate}/day). "
            f"Prior cause: {finding.summary if finding else 'unknown'}. Re-investigate what the fix missed.")
    _start_followup(session, orig, note, slug=f"fix-persists-{watch.id}",
                    a_type="fix_regression", metric=watch.metric)
    return "persists_reopened"


def check_regressions(session: Session, as_of: datetime | None = None) -> list[dict]:
    """A previously-confirmed theme that re-spikes fires a regression anomaly
    linked to the original case (the investigator will start from prior context)."""
    now = aware_utc(as_of) or reference_now(session)
    out = []
    for watch in session.scalars(select(FixWatch).where(FixWatch.status == "confirmed")).all():
        recent = _rate(session, watch.terms, now - timedelta(days=REGRESS_WINDOW), now)
        base = watch.baseline_rate or 0.0
        if base > 0 and recent >= base * REGRESS_BACK:
            watch.status = "regressed"
            orig = session.get(Investigation, watch.investigation_id)
            finding = session.get(Finding, watch.finding_id)
            note = (f"REGRESSION: '{watch.metric}' was confirmed fixed but has re-spiked "
                    f"({recent}/day vs baseline {base}). Original cause: "
                    f"{finding.summary if finding else 'unknown'}. Investigate WHAT CHANGED since the fix.")
            ev = _start_followup(session, orig, note, slug=f"regression-{watch.id}",
                                 a_type="regression", metric=watch.metric)
            out.append({"watch_id": watch.id, "regression_anomaly": ev.slug, "recent_rate": recent})
    session.flush()
    return out


def _start_followup(session, orig_inv, note, slug, a_type, metric) -> AnomalyEvent:
    """Create a linked follow-up anomaly carrying prior context (dedup by slug)."""
    existing = session.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == slug)).first()
    if existing:
        return existing
    ev = AnomalyEvent(
        slug=slug, type=a_type, metric=metric, delta=0.0, z=0.0, window="follow-up",
        description=note, status="pending",
        parent_case_id=orig_inv.id if orig_inv else None,
    )
    session.add(ev)
    session.flush()
    return ev
