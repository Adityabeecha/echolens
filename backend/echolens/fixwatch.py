"""Closed-loop fix verification (v6.0) — "did the fix actually work?"

When a finding's GitHub issue closes, we open a monitoring window on the exact
complaint theme the finding was about and measure whether it actually went away.
Deterministic counting over the corpus; no LLM.

Lifecycle: link_issue → on_issue_closed → [waiting_for_release →] evaluate →
(confirmed | reopened), then check_regressions can later flip a confirmed fix
back to regressed.

Version-aware: a mobile fix reaches users days after the issue closes, so when a
watch carries a `fixed_in_version` the post-fix window opens at the first review
on that version (or a later one), not at issue close.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Finding, FixWatch, Investigation, Review
from echolens.detector.detect import reference_now
from echolens.impact import theme_terms
from echolens.textkit import parse_version
from echolens.timeutil import aware_utc
from echolens.tools._util import match_score

CONFIRM_DROP = 0.4    # post-fix rate ≤ 40% of baseline → the fix worked
PERSIST_KEEP = 0.6    # post-fix rate ≥ 60% of baseline at window end → it didn't
REGRESS_BACK = 0.8    # a confirmed theme back to ≥80% of baseline → regression
REGRESS_WINDOW = 7    # a regression is a RECENT re-spike, measured tight so it isn't diluted

WAITING = "waiting_for_release"
RELEASE_MIN_REVIEWS = 10   # reviews on the fixed version before the window opens...
RELEASE_MIN_DAYS = 7       # ...or this many days after its first sighting

_FIXED_IN_RE = re.compile(
    r"\b(?:fixed|released|shipped|resolved|landed)\s+(?:in|with|by|on)\s+"
    r"(?:app\s+)?(?:version\s+|release\s+)?v?(\d+(?:\.\d+){1,2})", re.I)


def parse_fixed_version(*texts: str | None) -> str | None:
    """'fixed in v3.2.1' / 'released in 3.2' in an issue title/body/comment →
    '3.2.1'. First match wins; None when nothing says which version carries the fix."""
    for t in texts:
        m = _FIXED_IN_RE.search(t or "")
        if m:
            return m.group(1)
    return None


# The statuses a watch stops at, and the only ones that have a chart: _confirm,
# _inconclusive and _reopen each write chart_json, and nothing else does.
TERMINAL_FIX_STATUSES = frozenset({"confirmed", "inconclusive",
                                   "persists_reopened", "regressed"})


def _terms_for(session: Session, finding: Finding) -> list[str]:
    inv = session.get(Investigation, finding.investigation_id)
    anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv else None
    return theme_terms(anomaly, finding.json or {})


def product_name_of(session: Session, product_id: int | None) -> str | None:
    """The corpus label for a product id (rows are stamped with Product.name)."""
    if product_id is None:
        return None
    from echolens.db.models import Product
    p = session.get(Product, product_id)
    return p.name if p is not None else None


def complaint_series(session: Session, terms: list[str], start: datetime, end: datetime,
                     product: str | None = None) -> list[dict]:
    """Per-day count of negative reviews (≤2★) matching the theme in [start, end].

    `product` is not optional in spirit: unscoped, another product's complaints
    counted toward THIS product's fix, so a fix that genuinely worked failed to
    confirm and could even be flagged as a regression. Callers pass the watch's
    own product.

    The date range is filtered in SQL, not Python — this used to load every
    negative review ever recorded on each call, once per watch.
    """
    stmt = select(Review).where(Review.rating <= 2,
                                Review.created_at >= start, Review.created_at <= end)
    if product:
        stmt = stmt.where(Review.product == product)
    rows = session.scalars(stmt).all()
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


def _was_observed(session: Session, start: datetime, end: datetime,
                  product: str | None = None) -> bool:
    """Was anything actually WATCHING this product during [start, end]?

    A window is observable only if some enabled collector for the product ran
    at or after `start` and is not currently errored. Anything else means we
    were not looking, whatever the review count says.
    """
    from echolens.db.models import CollectorState
    stmt = select(CollectorState).where(CollectorState.enabled == True)  # noqa: E712
    if product:
        stmt = stmt.where(CollectorState.product == product)
    for st in session.scalars(stmt).all():
        if st.status == "error":
            continue
        last = aware_utc(st.last_run_at)
        if last is not None and last >= start:
            return True
    return False


def _rate(session: Session, terms: list[str], start: datetime, end: datetime,
          product: str | None = None) -> float | None:
    """Average daily matching-negative-review count, or None when unobservable.

    Returns None rather than 0.0 when the window was never watched. The two are
    completely different claims — "we watched and saw no complaints" versus "we
    have not watched yet" — and collapsing them into 0.0 is what lets a stalled
    collector read as a verified fix.

    The emptiness of `series` cannot answer that question: complaint_series
    pre-fills every calendar day with 0, so it is never empty for a valid range
    and the old `if not series` check could never fire. Liveness has to be read
    from the collectors themselves.
    """
    if not _was_observed(session, start, end, product):
        return None
    series = complaint_series(session, terms, start, end, product)
    if not series:
        return None
    return round(sum(s["count"] for s in series) / len(series), 3)


# A fix cannot be judged on a window shorter than this: complaints arrive with a
# lag, so "no complaints yet" two days after the fix means nothing.
MIN_OBSERVATION_DAYS = 5


def link_issue(session: Session, finding: Finding, repo: str, issue_number: int,
               issue_url: str = "") -> FixWatch:
    """Record the finding↔issue link at issue-creation time so the webhook can
    match a later 'closed' event back to this finding (idempotent)."""
    existing = session.scalars(select(FixWatch).where(
        FixWatch.repo == repo, FixWatch.issue_number == issue_number,
        FixWatch.investigation_id == finding.investigation_id)).first()
    if existing:
        return existing
    inv = session.get(Investigation, finding.investigation_id)
    anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv else None
    watch = FixWatch(
        finding_id=finding.id, investigation_id=finding.investigation_id,
        repo=repo, issue_number=issue_number, issue_url=issue_url, status="issue_open",
        terms=_terms_for(session, finding), metric=(anomaly.metric if anomaly else ""),
        product_id=(inv.product_id if inv else None),
    )
    session.add(watch)
    session.flush()
    return watch


def on_issue_closed(session: Session, repo: str, issue_number: int,
                    closed_at: datetime | None = None,
                    payload_text: str = "") -> FixWatch | None:
    """A GitHub issue closed → start the monitoring window and record the pre-fix
    baseline complaint rate. If the closing text names the fixed version
    ('fixed in v3.2.1') and none was set by hand, the watch waits for that
    version to reach users before the window opens."""
    watch = session.scalars(select(FixWatch).where(
        FixWatch.repo == repo, FixWatch.issue_number == issue_number)).first()
    if watch is None or watch.status not in ("issue_open",):
        return watch
    product = product_name_of(session, watch.product_id)
    fix_date = aware_utc(closed_at) or reference_now(session, product)
    if not watch.fixed_in_version:
        watch.fixed_in_version = parse_fixed_version(payload_text)
    watch.fix_date = fix_date
    if watch.fixed_in_version:
        watch.status = WAITING
        session.flush()
        _advance_waiting(session, watch, fix_date)   # it may already be live
        return watch
    watch.status = "watching"
    watch.baseline_rate = _rate(session, watch.terms,
                                fix_date - timedelta(days=watch.window_days), fix_date, product)
    session.flush()
    return watch


def release_state(session: Session, watch: FixWatch, now: datetime | None = None) -> dict:
    """Has the fixed version reached users? Counts reviews on that version or a
    later one (textkit.parse_version ordering), scoped to the watch's product.

    state: 'none' (no version set) | 'not_seen' | 'rolling_out' (seen, not yet
    enough) | 'live' (>= RELEASE_MIN_REVIEWS reviews, or RELEASE_MIN_DAYS since
    first sighting)."""
    target = parse_version(watch.fixed_in_version)
    base = {"fixed_in_version": watch.fixed_in_version, "state": "none", "first_seen": None,
            "review_count": 0, "needed_reviews": RELEASE_MIN_REVIEWS,
            "needed_days": RELEASE_MIN_DAYS}
    if target is None:
        return base
    product = product_name_of(session, watch.product_id)
    stmt = select(Review.version, Review.created_at).where(Review.version.is_not(None))
    if product:
        stmt = stmt.where(Review.product == product)
    seen = []
    for ver, at in session.execute(stmt).all():
        pv = parse_version(ver)
        if pv is not None and pv >= target:
            seen.append(aware_utc(at))
    if not seen:
        return {**base, "state": "not_seen"}
    first = min(seen)
    now = aware_utc(now) or reference_now(session, product)
    live = len(seen) >= RELEASE_MIN_REVIEWS or (now - first) >= timedelta(days=RELEASE_MIN_DAYS)
    return {**base, "state": "live" if live else "rolling_out",
            "first_seen": first.isoformat(), "review_count": len(seen)}


def _advance_waiting(session: Session, watch: FixWatch, now: datetime | None = None) -> dict:
    """Open the post-fix window if the fixed version is live; otherwise stay waiting."""
    info = release_state(session, watch, now)
    if info["state"] == "live":
        first = aware_utc(datetime.fromisoformat(info["first_seen"]))
        product = product_name_of(session, watch.product_id)
        watch.fix_date = first
        watch.release_seen_at = first
        watch.status = "watching"
        watch.post_rate = None
        watch.baseline_rate = _rate(session, watch.terms,
                                    first - timedelta(days=watch.window_days), first, product)
        session.flush()
    return info


def set_fixed_version(session: Session, watch: FixWatch, version: str | None) -> dict:
    """Reviewer sets (or clears) the version that carries the fix. Raises
    ValueError on an unparseable version. A watch still in progress is re-keyed
    to the release; a finished one only records the version (its verdict stands)."""
    version = (version or "").strip().lstrip("vV") or None
    if version is not None and parse_version(version) is None:
        raise ValueError("not a version number")
    watch.fixed_in_version = version
    if watch.status in ("watching", WAITING):
        watch.release_seen_at = None
        watch.post_rate = None
        if version:
            watch.status = WAITING
            session.flush()
            _advance_waiting(session, watch)
        elif watch.status == WAITING:
            # Back to the plain issue-close window.
            product = product_name_of(session, watch.product_id)
            watch.status = "watching"
            fix = aware_utc(watch.fix_date)
            if fix is not None:
                watch.baseline_rate = _rate(session, watch.terms,
                                            fix - timedelta(days=watch.window_days), fix, product)
    session.flush()
    return release_state(session, watch)


def before_after(session: Session, watch: FixWatch) -> dict:
    """The before/after complaint-rate chart data (the artifact a PM pastes into
    their review)."""
    if not watch.fix_date:
        return {}
    fix = aware_utc(watch.fix_date)
    w = timedelta(days=watch.window_days)
    product = product_name_of(session, watch.product_id)
    pre = complaint_series(session, watch.terms, fix - w, fix, product)
    post = complaint_series(session, watch.terms, fix, fix + w, product)
    return {
        "fix_date": fix.date().isoformat(), "window_days": watch.window_days,
        "before": pre, "after": post,
        "before_rate": watch.baseline_rate, "after_rate": watch.post_rate,
        "metric": watch.metric, "terms": watch.terms,
        # Why the window starts where it does: a release sighting, or issue close.
        "fixed_in_version": watch.fixed_in_version,
        "window_start": "first_review_on_fixed_version" if watch.release_seen_at else "issue_closed",
    }


def evaluate(session: Session, as_of: datetime | None = None,
             product_id: int | None = None) -> list[dict]:
    """Advance every watching fix. Confirms fixes that worked and re-opens the
    ones that didn't — unprompted (this is what the scheduled job calls)."""
    out = []
    w_stmt = select(FixWatch).where(FixWatch.status == WAITING)
    if product_id is not None:
        w_stmt = w_stmt.where(FixWatch.product_id == product_id)
    for watch in session.scalars(w_stmt).all():
        info = _advance_waiting(session, watch, as_of)
        if watch.status == WAITING:
            out.append({"watch_id": watch.id, "finding_id": watch.finding_id,
                        "status": WAITING, "fixed_in_version": watch.fixed_in_version,
                        "why": f"waiting for v{watch.fixed_in_version} to reach users "
                               f"({info['review_count']}/{RELEASE_MIN_REVIEWS} reviews)"})
    stmt = select(FixWatch).where(FixWatch.status == "watching")
    if product_id is not None:
        stmt = stmt.where(FixWatch.product_id == product_id)
    for watch in session.scalars(stmt).all():
        product = product_name_of(session, watch.product_id)
        now = aware_utc(as_of) or reference_now(session, product)
        fix = aware_utc(watch.fix_date)
        window_end = fix + timedelta(days=watch.window_days)
        observed_end = min(now, window_end)
        observed_days = (observed_end - fix).days
        post = _rate(session, watch.terms, fix, observed_end, product)
        watch.post_rate = post
        base = watch.baseline_rate or 0.0
        window_over = now >= window_end
        result = "watching"

        # Nothing can be concluded without a real observation window. `post` is
        # None when the window is empty (a stalled collector can make `now`
        # EARLIER than the fix date, which used to produce 0.0 and read as a
        # perfect fix), and a window shorter than MIN_OBSERVATION_DAYS has not
        # given complaints time to arrive.
        if post is None or observed_days < MIN_OBSERVATION_DAYS:
            out.append({"watch_id": watch.id, "finding_id": watch.finding_id,
                        "status": "watching", "baseline_rate": base, "post_rate": post,
                        "why": "not enough post-fix data to judge yet"})
            continue

        if base > 0 and post <= base * CONFIRM_DROP:
            result = _confirm(session, watch)
        elif window_over and (base == 0 or post >= base * PERSIST_KEEP):
            result = _reopen(session, watch)
        elif window_over:
            # The 40–60% band: better, but not the "complaints stopped" the UI
            # claims a confirmed fix means. Escalate to a human instead of
            # silently banking it as verified — a false confirmation here is
            # mined by the brain and patterns as ground truth.
            result = _inconclusive(session, watch)
        session.flush()
        out.append({"watch_id": watch.id, "finding_id": watch.finding_id,
                    "status": result, "baseline_rate": base, "post_rate": post})
    return out


def _confirm(session: Session, watch: FixWatch) -> str:
    watch.status = "confirmed"
    watch.confirmed_at = reference_now(session, product_name_of(session, watch.product_id))
    watch.chart_json = before_after(session, watch)
    session.flush()
    # v12: a confirmed fix is a new data point for the product's knowledge brain.
    # Re-mine the edges so the learned map stays current without a manual step.
    try:
        from echolens.brain import rebuild
        rebuild(session, watch.product_id)
    except Exception as err:  # learning must never block a fix confirmation
        from echolens.logging import get_logger
        get_logger("fixwatch").warning("brain_rebuild_failed", error=str(err))
    return "confirmed"


def _inconclusive(session: Session, watch: FixWatch) -> str:
    """The window elapsed and complaints fell, but not far enough to call it fixed.

    Previously this band was recorded as "confirmed" outright, so a complaint
    rate still at 59% of baseline was banked as a verified fix — then mined by
    the brain as proof that a cause→fix pair works. A partial improvement is a
    real result, but it is a human's call, not the machine's.
    """
    watch.status = "inconclusive"
    watch.chart_json = before_after(session, watch)
    session.flush()
    return "inconclusive"


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


def check_regressions(session: Session, as_of: datetime | None = None,
                      product_id: int | None = None) -> list[dict]:
    """A previously-confirmed theme that re-spikes fires a regression anomaly
    linked to the original case (the investigator will start from prior context)."""
    out = []
    stmt = select(FixWatch).where(FixWatch.status == "confirmed")
    if product_id is not None:
        stmt = stmt.where(FixWatch.product_id == product_id)
    for watch in session.scalars(stmt).all():
        product = product_name_of(session, watch.product_id)
        now = aware_utc(as_of) or reference_now(session, product)
        recent = _rate(session, watch.terms, now - timedelta(days=REGRESS_WINDOW), now, product)
        base = watch.baseline_rate or 0.0
        # `recent is None` means the window was unobservable, not that complaints
        # are absent — never declare a regression (or its absence) from no data.
        if recent is not None and base > 0 and recent >= base * REGRESS_BACK:
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
        product_id=(orig_inv.product_id if orig_inv else None),
    )
    session.add(ev)
    session.flush()
    return ev
