"""The unified case list — one lifecycle, one vocabulary, one card.

Before this, the same case appeared on three screens under three different
names: the Case Feed called it "Pending triage", Product Health called it an
"open problem", the Archive called it "Insufficient evidence". Three surfaces
meant three chances to disagree about what a case *is*.

This module is the single answer. It derives ONE status per case from the four
tables that each hold a piece of the truth (investigation, finding, fix watch,
queue), using the eight words the UI is allowed to say:

    Queued · Running · Needs review · Needs human
    Resolved · Dismissed · Verified fixed · Regressed

Everything a card renders comes from here, so a case cannot look like one thing
on Today and another on Cases.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import (
    AnomalyEvent, Finding, FixWatch, Investigation, Product,
    QueuedInvestigation, Review, ReviewFeedback, TriageDecision)
from echolens.impact import severity
from echolens.timeutil import aware_utc

# ── the vocabulary ──────────────────────────────────────────────────────
# Every status the UI may show. Synonyms ("Pending triage", "Awaiting triage",
# "Open", "Investigating") are deliberately absent: a word that appears in one
# place and nowhere else is a word the user has to learn twice.
QUEUED = "queued"
RUNNING = "running"
NEEDS_REVIEW = "needs_review"
NEEDS_HUMAN = "needs_human"
RESOLVED = "resolved"
DISMISSED = "dismissed"
VERIFIED_FIXED = "verified_fixed"
REGRESSED = "regressed"

STATUSES = (QUEUED, RUNNING, NEEDS_REVIEW, NEEDS_HUMAN,
            RESOLVED, DISMISSED, VERIFIED_FIXED, REGRESSED)

# Which filter tab a status lands under. Every status has exactly one home —
# a tab that hides a case is worse than no tab at all.
TABS: dict[str, tuple[str, ...]] = {
    "needs-review": (NEEDS_REVIEW, NEEDS_HUMAN, REGRESSED),
    "running": (RUNNING,),
    "queued": (QUEUED,),
    "resolved": (RESOLVED, VERIFIED_FIXED),
    "dismissed": (DISMISSED,),
}

SPARK_WEEKS = 8
# Bound the corpus scan that builds per-case sparklines. Sparklines are garnish;
# they must never be the reason a page is slow.
SPARK_REVIEW_CAP = 4000


def _iterations(inv: Investigation) -> dict | None:
    """(done, cap) from the budget's "4/12", or None when it isn't recorded."""
    raw = (inv.budget_json or {}).get("iterations")
    if raw is None:
        return None
    try:
        done, cap = str(raw).split("/")
        return {"done": int(float(done)), "max": int(float(cap))}
    except (ValueError, TypeError):
        return None


def _age_days(when: datetime | None, now: datetime) -> int | None:
    if when is None:
        return None
    return max(0, (now - aware_utc(when)).days)


def _terms(finding: Finding | None, anomaly: AnomalyEvent | None) -> list[str]:
    """The words this case is about, for the complaint-volume sparkline."""
    if finding is not None:
        impact = (finding.json or {}).get("impact") or {}
        terms = [t for t in (impact.get("terms") or []) if isinstance(t, str) and len(t) > 2]
        if terms:
            return terms[:4]
    if anomaly is not None:
        metric = (anomaly.metric or "").split(" share of")[0].split(" per week")[0]
        word = re.sub(r"[^a-z ]", " ", metric.lower()).strip()
        if len(word) > 2:
            return [word.split()[0]]
    return []


class _SparkIndex:
    """Weekly negative-review counts per term, from one pass over the corpus.

    Built once per request rather than per case: twenty cases used to mean
    twenty LIKE queries, and a sparkline is not worth twenty round trips.
    """

    def __init__(self, session: Session, product: str | None, now: datetime):
        self.now = now
        self.start = now - timedelta(weeks=SPARK_WEEKS)
        stmt = (select(Review.text, Review.created_at)
                .where(Review.rating <= 2, Review.created_at >= self.start.replace(tzinfo=None))
                .order_by(Review.created_at.desc())
                .limit(SPARK_REVIEW_CAP))
        # No product means no corpus to draw from — NOT "every product's".
        # Unscoped, one product's sparklines were drawn from another's reviews.
        if product is None:
            self.rows = []
            return
        stmt = stmt.where(Review.product == product)
        rows = list(session.execute(stmt))
        # ORDER BY created_at DESC + LIMIT keeps the NEWEST rows, so on a busy
        # product the oldest weeks were cut entirely and their buckets read 0 —
        # drawing a dramatic rise from nothing that was purely an artifact of
        # the cap. If we hit the cap we cannot see the whole window, so we
        # refuse to draw rather than draw something false.
        self.truncated = len(rows) >= SPARK_REVIEW_CAP
        self.rows = [] if self.truncated else [
            (text.lower(), created) for text, created in rows if text and created]

    def series(self, terms: list[str]) -> list[int] | None:
        if not terms or not self.rows:
            return None
        # Word-boundary matching. Plain `n in text` meant "app" matched "happy"
        # and "apply", so a sparkline could be drawn almost entirely from
        # coincidental substrings.
        needles = [re.compile(r"\b" + re.escape(t.lower())) for t in terms if t]
        buckets = [0] * SPARK_WEEKS
        hit = False
        for text, created in self.rows:
            if not any(n.search(text) for n in needles):
                continue
            weeks_ago = int((self.now - aware_utc(created)).days // 7)
            if 0 <= weeks_ago < SPARK_WEEKS:
                buckets[SPARK_WEEKS - 1 - weeks_ago] += 1
                hit = True
        # No matches at all is not a flat line — it is no data. Say nothing
        # rather than draw a floor that looks like a measured zero.
        return buckets if hit else None


def derive_status(inv: Investigation, finding: Finding | None,
                  watch: FixWatch | None) -> tuple[str, str]:
    """(status, why) — the one place a case's state is decided.

    Order matters: verification outranks the investigation's own verdict,
    because "we shipped a fix and it came back" is the more recent truth.
    """
    if inv.status == "running":
        return RUNNING, "Investigating now."
    # A case the dedupe migration retired is not a live case. Without this branch
    # it fell through to NEEDS_REVIEW and a merged duplicate reappeared on the
    # action queue, while backlog/portfolio (which filter status == "resolved")
    # never showed it — two surfaces, two answers, the exact split this module
    # exists to prevent.
    if inv.status == "merged_duplicate":
        return DISMISSED, "Merged into another case covering the same signal."
    if watch is not None:
        if watch.status == "confirmed":
            return VERIFIED_FIXED, "A fix shipped and the complaints stopped."
        if watch.status == "regressed":
            return REGRESSED, "This was fixed once and has come back."
        if watch.status == "persists_reopened":
            return REGRESSED, "The fix shipped but the complaints continued."
        if watch.status == "inconclusive":
            return NEEDS_HUMAN, ("Complaints fell after the fix but not enough to call it "
                                 "fixed — your call on whether it worked.")
    if finding is not None and finding.status == "challenged":
        return DISMISSED, "You challenged this finding; it was re-opened as a new case."
    if inv.status == "budget_exhausted":
        return NEEDS_HUMAN, "Budget ran out before a cause cleared the evidence bar."
    if inv.status == "insufficient_evidence":
        return NEEDS_HUMAN, "Not enough evidence to name a cause — your call on what to do."
    if inv.status == "needs_human":
        return NEEDS_HUMAN, "The evidence conflicts — this needs a human decision."
    if finding is None:
        return NEEDS_HUMAN, "This case ended without a finding."
    if finding.status == "approved":
        return RESOLVED, "You approved the finding; no verified fix yet."
    return NEEDS_REVIEW, "A finding is drafted and waiting for your review."


def case_title(finding: Finding | None, anomaly: AnomalyEvent | None,
               queued_title: str | None = None) -> str:
    """A problem statement, never a metric name.

    The old feed used `anomaly.metric` as a title, so cases were called things
    like "battery share of negatives" — a column header, not a problem.
    """
    if finding is not None and (finding.summary or "").strip():
        return finding.summary.strip()
    if queued_title and queued_title.strip():
        return queued_title.strip()
    if anomaly is not None:
        return _headline(anomaly)
    return "Investigation in progress"


def _headline(a: AnomalyEvent) -> str:
    """Problem-statement headline for an anomaly, without the session the API's
    richer version needs. Kept deliberately close to it in wording."""
    metric = (a.metric or "").strip()
    if a.description and a.type in ("manual", "manual_theme"):
        return a.description.strip()
    if a.type == "regression":
        return f"Regression — “{metric}” came back after being fixed"
    if a.type == "fix_regression":
        return f"Fix didn't hold — “{metric}” complaints continue"
    if a.type == "theme_volume_surge":
        label = metric.split(" share of")[0].split(" on ")[0].strip() or "complaints"
        return f"{label[:1].upper()}{label[1:]} rising in your reviews"
    if a.type == "issue_velocity_surge":
        label = metric.split(" per week")[0].strip() or "issue reports"
        return f"{label[:1].upper()}{label[1:]} piling up on GitHub"
    if a.type == "rating_drop":
        return "Average rating is falling"
    if a.type == "negative_review_spike":
        return "1-star reviews are spiking"
    return (a.description or metric or "Signal detected").strip()


def case_rows(session: Session, product_id: int | None,
              as_of: datetime | None = None) -> list[dict]:
    """Every case for a product, newest first, in the shared card shape."""
    now = as_of or datetime.now(timezone.utc)
    product = session.get(Product, product_id) if product_id is not None else None
    spark = _SparkIndex(session, product.name if product else None, now)

    stmt = select(Investigation).order_by(Investigation.id.desc())
    if product_id is not None:
        stmt = stmt.where(Investigation.product_id == product_id)
    investigations = list(session.scalars(stmt).all())

    # Three bulk queries instead of three PER CASE. This was 4 SQL round trips
    # per case — 243 queries for 60 cases, on the two most-loaded screens in the
    # app (Today and Cases both call it).
    inv_ids = [i.id for i in investigations]
    latest_finding: dict[int, Finding] = {}
    latest_watch: dict[int, FixWatch] = {}
    anomalies: dict[int, AnomalyEvent] = {}
    if inv_ids:
        for f in session.scalars(select(Finding).where(
                Finding.investigation_id.in_(inv_ids)).order_by(Finding.id)).all():
            latest_finding[f.investigation_id] = f     # ascending: last wins
        for w in session.scalars(select(FixWatch).where(
                FixWatch.investigation_id.in_(inv_ids)).order_by(FixWatch.id)).all():
            latest_watch[w.investigation_id] = w
        a_ids = [i.anomaly_id for i in investigations if i.anomaly_id]
        if a_ids:
            for a in session.scalars(select(AnomalyEvent).where(
                    AnomalyEvent.id.in_(a_ids))).all():
                anomalies[a.id] = a

    rows: list[dict] = []
    for inv in investigations:
        finding = latest_finding.get(inv.id)
        watch = latest_watch.get(inv.id)
        anomaly = anomalies.get(inv.anomaly_id) if inv.anomaly_id else None
        status, why = derive_status(inv, finding, watch)

        fj = (finding.json or {}) if finding is not None else {}
        impact = fj.get("impact") or {}
        sev = severity(float(finding.confidence or 0.0), impact) if finding else None
        rows.append({
            "id": inv.id,
            "queue_id": None,
            "title": case_title(finding, anomaly),
            "status": status,
            "why": why,
            "severity": sev["band"] if sev else None,
            "severity_score": sev["score"] if sev else None,
            "confidence": round(float(finding.confidence), 2) if finding else None,
            "impact": None if not impact.get("affected_volume") else {
                "affected_pct": impact.get("affected_pct", 0.0),
                "affected_volume": impact.get("affected_volume", 0),
            },
            "opened_at": aware_utc(inv.created_at).isoformat() if inv.created_at else None,
            "age_days": _age_days(inv.created_at, now),
            "source": (anomaly.type if anomaly else None) or inv.opened_by,
            "opened_by": inv.opened_by,
            "iterations": _iterations(inv) if status == RUNNING else None,
            "paused": bool(inv.paused),
            "finding_id": finding.id if finding else None,
            "issue_url": watch.issue_url if watch else None,
            "issue_number": watch.issue_number if watch else None,
            "reopens_investigation_id": inv.reopens_investigation_id,
            "spark": spark.series(_terms(finding, anomaly)),
        })

    # Queued work is part of the same lifecycle, so it lives in the same list
    # rather than in a separate panel that only one screen knew about.
    q_stmt = select(QueuedInvestigation).where(QueuedInvestigation.status == "queued")
    if product_id is not None:
        q_stmt = q_stmt.where(QueuedInvestigation.product_id == product_id)
    pending_q = sorted(session.scalars(q_stmt).all(),
                       key=lambda r: (r.priority, r.selection_order, r.id))
    queued_rows: list[dict] = []
    for position, row in enumerate(pending_q, start=1):
        anomaly = session.get(AnomalyEvent, row.anomaly_id) if row.anomaly_id else None
        queued_rows.append({
            "id": None,
            "queue_id": row.id,
            "title": case_title(None, anomaly, row.title),
            "status": QUEUED,
            # A queued row has no investigation yet, so its card cannot be
            # opened. Say when it will be, rather than leaving a card that
            # silently does nothing when clicked.
            "why": row.note or (
                f"Queued — position {position}. Opens for live viewing once it starts."
                if position > 1 else
                "Queued — next to run. Opens for live viewing once it starts."),
            "severity": None, "severity_score": None, "confidence": None, "impact": None,
            "opened_at": aware_utc(row.created_at).isoformat() if row.created_at else None,
            "age_days": _age_days(row.created_at, now),
            "source": row.source,
            "opened_by": row.source,
            "iterations": None,
            "paused": False,
            "finding_id": None,
            "issue_url": None, "issue_number": None,
            "reopens_investigation_id": None,
            "position": position,
            "spark": spark.series(_terms(None, anomaly)),
        })
    # Queued work leads the list, IN QUEUE ORDER. This was built with
    # `rows.insert(0, ...)` inside the loop, so each insert pushed the previous
    # one down and the block rendered 3, 2, 1 — while each card's own label
    # correctly read "position 1", "position 2", "position 3". The list
    # contradicted itself.
    return queued_rows + rows


def signal_rows(session: Session, product_id: int | None,
                as_of: datetime | None = None) -> list[dict]:
    """Anomalies that have not become cases — the raw end of the pipeline.

    Deliberately separate from cases: a signal is something EchoLens noticed,
    a case is something it is accountable for. Mixing them is what made the old
    feed unreadable.
    """
    now = as_of or datetime.now(timezone.utc)
    stmt = select(AnomalyEvent).where(AnomalyEvent.merged_into_id.is_(None))
    if product_id is not None:
        stmt = stmt.where(AnomalyEvent.product_id == product_id)
    anomalies = list(session.scalars(stmt.order_by(AnomalyEvent.id.desc())).all())
    if not anomalies:
        return []

    # Three bulk lookups instead of three PER ANOMALY. On a product with a long
    # detection history this was the other half of the /cases N+1.
    a_ids = [a.id for a in anomalies]
    has_case = {
        i.anomaly_id for i in session.scalars(
            select(Investigation).where(Investigation.anomaly_id.in_(a_ids))).all()
    }
    committed = {
        q.anomaly_id for q in session.scalars(
            select(QueuedInvestigation).where(
                QueuedInvestigation.anomaly_id.in_(a_ids),
                QueuedInvestigation.status.in_(("queued", "running")))).all()
    }
    decisions: dict[int, TriageDecision] = {}
    for td_row in session.scalars(select(TriageDecision).where(
            TriageDecision.anomaly_id.in_(a_ids)).order_by(TriageDecision.id)).all():
        decisions[td_row.anomaly_id] = td_row      # ascending: last wins

    out = []
    for a in anomalies:
        if a.id in has_case:
            continue  # it grew into a case; it belongs in the case list
        if a.id in committed:
            continue  # already committed to
        td = decisions.get(a.id)
        dismissed = td is not None and td.decision in ("ignore", "merge")
        out.append({
            "slug": a.slug,
            "title": _headline(a),
            "type": a.type,
            "metric": a.metric,
            "z": a.z,
            "window": a.window,
            "age_days": _age_days(a.created_at, now),
            "dismissed": dismissed,
            "dismissed_reason": (td.reason if dismissed else None),
        })
    return out


def case_view(session: Session, product_id: int | None,
              as_of: datetime | None = None) -> dict:
    """Everything the Cases screen renders, plus the counts its tabs show."""
    product = session.get(Product, product_id) if product_id is not None else None
    cases = case_rows(session, product_id, as_of)
    signals = signal_rows(session, product_id, as_of)
    counts = {"all": len(cases)}
    for tab, statuses in TABS.items():
        counts[tab] = len([c for c in cases if c["status"] in statuses])
    return {
        "product": product.name if product else None,
        "product_id": product.id if product else None,
        "cases": cases,
        "signals": signals,
        "counts": counts,
    }


def case_history(session: Session, inv: Investigation) -> list[dict]:
    """The audit trail of a case: opened, challenged, re-opened, fixed, regressed.

    Human decisions were previously invisible after the fact — a challenge
    changed the case and left no record you could read back.
    """
    events: list[dict] = []

    def add(at, kind: str, text: str, case_id: int | None = None, note: str = ""):
        events.append({
            "at": aware_utc(at).isoformat() if at else None,
            "kind": kind, "text": text, "case_id": case_id, "note": note,
        })

    add(inv.created_at, "opened",
        f"Case opened {'by you' if inv.opened_by == 'manual' else 'from a detected signal'}.")
    if inv.reopens_investigation_id:
        add(inv.created_at, "reopen",
            f"Re-opened from case #{inv.reopens_investigation_id} after a challenge.",
            case_id=inv.reopens_investigation_id)

    findings = session.scalars(select(Finding).where(
        Finding.investigation_id == inv.id).order_by(Finding.id)).all()
    for f in findings:
        add(f.created_at, "finding", "A finding was drafted.")
        for fb in session.scalars(select(ReviewFeedback).where(
                ReviewFeedback.finding_id == f.id).order_by(ReviewFeedback.id)).all():
            if fb.action == "approve":
                add(fb.created_at, "approved", "You approved the finding.", note=fb.note or "")
            else:
                reason = (fb.reason or "").replace("_", " ")
                add(fb.created_at, "challenged",
                    f"You challenged the finding{f' — {reason}' if reason else ''}.",
                    note=fb.note or "")

    for w in session.scalars(select(FixWatch).where(
            FixWatch.investigation_id == inv.id).order_by(FixWatch.id)).all():
        add(w.created_at, "issue", f"Issue #{w.issue_number} opened in {w.repo}.")
        if w.fix_date:
            add(w.fix_date, "fix_shipped", "The fix shipped — watching for a change.")
        if w.status == "confirmed" and w.confirmed_at:
            add(w.confirmed_at, "verified", "Verified fixed — the complaints stopped.")
        elif w.status == "regressed":
            add(w.fix_date, "regressed", "Regressed — the complaints came back.")
        elif w.status == "persists_reopened":
            add(w.fix_date, "regressed", "The fix didn't hold — complaints continued.")

    # A re-opened child means this case's story continues elsewhere.
    child = session.scalars(select(Investigation).where(
        Investigation.reopens_investigation_id == inv.id).order_by(Investigation.id)).first()
    if child is not None:
        add(child.created_at, "reopen", f"Continued as case #{child.id}.", case_id=child.id)

    events.sort(key=lambda e: (e["at"] or ""))
    return events
