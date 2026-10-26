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
    AnomalyEvent, CaseMerge, EvidenceRow, Finding, FindingDecision, FixWatch, Investigation, Product,
    QueuedInvestigation, Review, ReviewFeedback, TraceStep, TriageDecision)
from echolens.impact import severity
from echolens.textkit import clean_headline
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
    from echolens.impact import _GENERIC
    from echolens.textkit import tokenize

    # The signal names the theme. Finding prose also contains other hypotheses,
    # releases and generic words such as "update"; OR-matching those counted
    # almost the entire negative corpus as affected by several different cases.
    if anomaly is not None and anomaly.type == "theme_volume_surge":
        metric = re.split(r"\b(?:share|mentions|complaints|per week|on)\b",
                          anomaly.metric or "", maxsplit=1)[0]
        terms = [t for t in tokenize(metric) if t not in _GENERIC]
        if terms:
            return [" ".join(terms[:4])]
    if finding is not None:
        impact = (finding.json or {}).get("impact") or {}
        terms = [t for t in (impact.get("terms") or [])
                 if isinstance(t, str) and len(t) > 2 and t.lower() not in _GENERIC]
        if terms:
            from echolens.vocab import canonical_theme
            theme = canonical_theme(terms)
            return theme["terms"] if theme["is_family"] else terms[:4]
    if anomaly is not None:
        metric = (anomaly.metric or "").split(" share of")[0].split(" per week")[0]
        word = re.sub(r"[^a-z ]", " ", metric.lower()).strip()
        if len(word) > 2:
            return [word.split()[0]]
    return []


class _AffectedIndex:
    """One recent negative corpus, shared by every case in a list."""

    def __init__(self, session: Session, product: str | None, now: datetime,
                 texts: list[str] | None = None):
        from echolens.textkit import tokenize
        from echolens.vocab import _norm
        if texts is None:
            texts = list(session.scalars(select(Review.text).where(
                Review.product == product, Review.rating <= 2,
                Review.created_at > now - timedelta(days=7), Review.created_at <= now))) if product else []
        self.words = [{_norm(w) for w in tokenize(text)} for text in texts]

    def measure(self, impact: dict, terms: list[str]) -> dict:
        from echolens.impact import MIN_SHARE_DENOMINATOR
        from echolens.textkit import tokenize
        from echolens.vocab import _norm
        needles = [{_norm(w) for w in tokenize(term)} for term in terms]
        # Alternatives are ORed, but all words of a compound theme must match.
        # "sync crashes" must not count "sync drains my battery".
        count = sum(any(n and n <= row for n in needles) for row in self.words)
        measurable = len(self.words) >= MIN_SHARE_DENOMINATOR
        pct = round(100 * count / len(self.words), 1) if measurable else 0.0
        result = {**impact, "terms": terms, "affected_volume": count,
                  "recent_negatives": len(self.words), "affected_pct": pct}
        if measurable:
            result["measured"] = True
            result["impact_score"] = round(min(1.0, 0.5 * pct / 100 +
                0.3 * min(1.0, count / 40) +
                0.2 * min(1.0, (impact.get("rating_impact") or 0) / 0.6)), 3)
        return result


def affected_impact(session: Session, finding: Finding, anomaly: AnomalyEvent | None,
                    product: str | None, now: datetime | None = None) -> dict:
    """Read current, theme-specific share for old findings as well as new ones."""
    return _AffectedIndex(session, product, now or datetime.now(timezone.utc)).measure(
        (finding.json or {}).get("impact") or {}, _terms(finding, anomaly))


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
    if inv.status == "merged":
        return "merged", "Merged into another case; its evidence is linked as related."
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
    if inv.status == "failed":   # ended by the zombie watchdog; its note says why
        return NEEDS_HUMAN, ((inv.data_notes or [None])[-1]
                             or "The investigation stopped before it finished.")
    if inv.status == "insufficient_evidence":
        return NEEDS_HUMAN, "Not enough evidence to name a cause — your call on what to do."
    if inv.status == "needs_human":
        return NEEDS_HUMAN, "The evidence conflicts — this needs a human decision."
    if finding is None:
        return NEEDS_HUMAN, "This case ended without a finding."
    # v15: a reviewer struck evidence and the two-source rule no longer holds.
    # Said plainly, because "waiting for your review" would hide WHY it is back.
    if (finding.json or {}).get("needs_review"):
        return NEEDS_REVIEW, ("Evidence was rejected and the finding no longer has two "
                              "independent sources — it needs review again.")
    if finding.status == "approved":
        return RESOLVED, "You approved the finding; no verified fix yet."
    return NEEDS_REVIEW, "A finding is drafted and waiting for your review."


def case_title(finding: Finding | None, anomaly: AnomalyEvent | None,
               queued_title: str | None = None) -> str:
    """A problem statement, never a metric name.

    The old feed used `anomaly.metric` as a title, so cases were called things
    like "battery share of negatives" — a column header, not a problem.
    """
    # Cleaned on read too: findings stored before headlines were cleaned at
    # write time still carry "[ev_001]" tags and "V3.2.0".
    if finding is not None and clean_headline(finding.summary):
        return clean_headline(finding.summary)
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


def merged_into(session: Session, case_id: int) -> int | None:
    """Canonical destination, including when a merge target was later merged too."""
    destination, seen = None, {case_id}
    while True:
        link = session.scalars(select(CaseMerge).where(CaseMerge.source_id == case_id)).first()
        if link is None or link.target_id in seen:
            return destination
        destination = case_id = link.target_id
        seen.add(case_id)


def merge_cases(session: Session, source: Investigation, target: Investigation,
                user_id: int | None = None) -> CaseMerge:
    if source.id == target.id:
        raise ValueError("A case cannot be merged into itself.")
    def product_id(inv):
        anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv.product_id is None and inv.anomaly_id else None
        return inv.product_id if inv.product_id is not None else anomaly.product_id if anomaly else None

    if product_id(source) != product_id(target):
        raise ValueError("Cases must belong to the same product.")
    # Lock in a stable order so simultaneous opposite merges cannot create a cycle.
    session.scalars(select(Investigation).where(Investigation.id.in_([source.id, target.id]))
                    .order_by(Investigation.id).with_for_update()
                    .execution_options(populate_existing=True)).all()
    existing = session.scalars(select(CaseMerge).where(CaseMerge.source_id == source.id)).first()
    if existing is not None:
        if existing.target_id == target.id:
            return existing
        raise ValueError("This case has already been merged.")
    from echolens.review import decision_hides, latest_decision
    for inv in (source, target):
        finding = session.scalars(select(Finding).where(
            Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
        watch = session.scalars(select(FixWatch).where(
            FixWatch.investigation_id == inv.id).order_by(FixWatch.id.desc())).first()
        status, _ = derive_status(inv, finding, watch)
        if status not in (NEEDS_REVIEW, NEEDS_HUMAN, RESOLVED, REGRESSED):
            raise ValueError("Only open, finished cases can be merged; wait for running work to finish.")
        if finding and decision_hides(latest_decision(session, finding.id)):
            raise ValueError("Only open cases can be merged.")
    link = CaseMerge(source_id=source.id, target_id=target.id, user_id=user_id)
    session.add(link)
    source.status = "merged"
    source.product_id = target.product_id = product_id(target)
    for watch in session.scalars(select(FixWatch).where(FixWatch.investigation_id == source.id)).all():
        watch.status = "merged"
    session.flush()
    return link


def related_evidence(session: Session, inv: Investigation) -> list[dict]:
    """Read linked duplicates' evidence without promoting it to this case's proof."""
    links = session.execute(select(CaseMerge.source_id, CaseMerge.target_id)
        .join(Investigation, Investigation.id == CaseMerge.source_id)
        .where(Investigation.product_id == inv.product_id)).all()
    related, frontier = set(), {inv.id}
    while frontier:
        children = {source for source, target in links if target in frontier} - related - {inv.id}
        related.update(children)
        frontier = children
    if not related:
        return []
    return [{"source_case_id": e.investigation_id, "id": e.eid, "source": e.source,
             "ref": e.ref, "snippet": e.snippet}
            for e in session.scalars(select(EvidenceRow).where(
                EvidenceRow.investigation_id.in_(related)).order_by(EvidenceRow.id)).all()]


def _intent_of(anomaly: AnomalyEvent | None) -> str | None:
    """A case opened from a users' request theme is a request; the rest carry
    no intent of their own (their stamp comes from the proof)."""
    return "feature_request" if anomaly is not None and (anomaly.slug or "").startswith("request-") else None


def case_rows(session: Session, product_id: int | None,
              as_of: datetime | None = None) -> list[dict]:
    """Every case for a product, newest first, in the shared card shape."""
    now = as_of or datetime.now(timezone.utc)
    product = session.get(Product, product_id) if product_id is not None else None
    spark = _SparkIndex(session, product.name if product else None, now)
    affected = _AffectedIndex(session, product.name if product else None, now)

    stmt = select(Investigation).where(Investigation.status != "merged",
        Investigation.id.not_in(select(CaseMerge.source_id))).order_by(Investigation.id.desc())
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

    # v15: the product decision in force on each case's finding, so Today can
    # drop parked / won't-fix work from "open problems" without a second fetch.
    from echolens.review import decision_dict, latest_decisions
    decisions = latest_decisions(session, [f.id for f in latest_finding.values()])

    rows: list[dict] = []
    for inv in investigations:
        finding = latest_finding.get(inv.id)
        watch = latest_watch.get(inv.id)
        anomaly = anomalies.get(inv.anomaly_id) if inv.anomaly_id else None
        status, why = derive_status(inv, finding, watch)

        fj = (finding.json or {}) if finding is not None else {}
        impact = affected.measure(fj.get("impact") or {}, _terms(finding, anomaly)) if finding else {}
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
            "decision": decision_dict(decisions.get(finding.id), now) if finding else None,
            "spark": spark.series(_terms(finding, anomaly)),
            # What the verdict stamp needs, from rows already loaded above.
            "support_level": fj.get("support_level") if finding else None,
            "needs_review": bool(fj.get("needs_review")) if finding else False,
            "fix_status": watch.status if watch else None,
            "intent": _intent_of(anomaly),
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
            "decision": None,
            "position": position,
            "spark": spark.series(_terms(None, anomaly)),
            "support_level": None, "needs_review": False, "fix_status": None,
            "intent": _intent_of(anomaly),
        })
    # Queued work leads the list, IN QUEUE ORDER. This was built with
    # `rows.insert(0, ...)` inside the loop, so each insert pushed the previous
    # one down and the block rendered 3, 2, 1 — while each card's own label
    # correctly read "position 1", "position 2", "position 3". The list
    # contradicted itself.
    all_rows = queued_rows + rows
    def decision_key(row):
        f = latest_finding.get(row.get("id"))
        fj = (f.json or {}) if f else {}
        supported = fj.get("support_level") == "supported" and not fj.get("needs_review")
        return (not supported, -(row.get("severity_score") or 0),
                -((row.get("impact") or {}).get("affected_pct") or 0),
                -datetime.fromisoformat(row["opened_at"]).timestamp() if row.get("opened_at") else 0,
                -(row.get("id") or 0))

    for rank, row in enumerate(sorted(all_rows, key=decision_key), start=1):
        row["decision_rank"] = rank
    return all_rows


def signal_rows(session: Session, product_id: int | None,
                as_of: datetime | None = None) -> list[dict]:
    """Anomalies that have not become cases — the raw end of the pipeline.

    Deliberately separate from cases: a signal is something EchoLens noticed,
    a case is something it is accountable for. Mixing them is what made the old
    feed unreadable.
    """
    now = as_of or datetime.now(timezone.utc)
    # A closed anomaly that never became a case is finished with (a spike a
    # rescan no longer finds, a cancelled theme): it is not something to pick.
    stmt = select(AnomalyEvent).where(AnomalyEvent.merged_into_id.is_(None),
                                      AnomalyEvent.status != "closed")
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
            "id": a.id,
            "slug": a.slug,
            "title": _headline(a),
            "type": a.type,
            "metric": a.metric,
            "z": a.z,
            "window": a.window,
            "age_days": _age_days(a.created_at, now),
            "dismissed": dismissed,
            "dismissed_reason": (td.reason if dismissed else None),
            "dismissed_decision": (td.decision if dismissed else None),
            "merge_into_anomaly_id": (td.merge_into_anomaly_id
                                      if dismissed and td.decision == "merge" else None),
            "window_start": aware_utc(a.window_start).isoformat() if a.window_start else None,
            "window_end": aware_utc(a.window_end).isoformat() if a.window_end else None,
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


def _decision_text(d: FindingDecision) -> str:
    if d.decision == "fix_now":
        return "Product decision: fix now."
    if d.decision == "park":
        until = aware_utc(d.revisit_by).date().isoformat() if d.revisit_by else None
        return f"Product decision: parked{f' until {until}' if until else ''}."
    if d.decision == "wont_fix":
        return "Product decision: won't fix."
    return "Product decision cleared."


def case_history(session: Session, inv: Investigation) -> list[dict]:
    """The audit trail of a case: opened, challenged, re-opened, fixed, regressed.

    Human decisions were previously invisible after the fact — a challenge
    changed the case and left no record you could read back.
    """
    events: list[dict] = []

    def add(at, kind: str, text: str, case_id: int | None = None, note: str = "",
            by: str | None = None):
        events.append({
            "at": aware_utc(at).isoformat() if at else None,
            "kind": kind, "text": text, "case_id": case_id, "note": note, "by": by,
        })

    add(inv.created_at, "opened",
        f"Case opened {'by you' if inv.opened_by == 'manual' else 'from a detected signal'}.")
    from echolens.db.models import User
    for link in session.scalars(select(CaseMerge).where(
            (CaseMerge.source_id == inv.id) | (CaseMerge.target_id == inv.id))).all():
        author = session.get(User, link.user_id) if link.user_id else None
        destination = link.target_id if link.source_id == inv.id else link.source_id
        text = (f"Merged into case #{link.target_id}; evidence linked as related."
                if link.source_id == inv.id else
                f"Case #{link.source_id} merged here; its evidence is linked as related, not additional proof.")
        add(link.created_at, "merged", text, case_id=destination,
            by=author.email if author else None)
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
            elif fb.action == "reject_evidence":
                eid, _, why = (fb.note or "").partition(":")
                add(fb.created_at, "evidence_rejected",
                    f"You rejected evidence {eid.strip()} as not supporting the finding.",
                    note=why.strip())
            elif fb.action == "edit_rec":
                add(fb.created_at, "rec_edited",
                    f"You corrected recommendation {fb.note or ''}".strip() + ".")
            else:
                reason = (fb.reason or "").replace("_", " ")
                add(fb.created_at, "challenged",
                    f"You challenged the finding{f' — {reason}' if reason else ''}.",
                    note=fb.note or "")
                if fb.actual_cause:
                    events[-1]["actual_cause"] = fb.actual_cause
        if (f.json or {}).get("needs_review"):
            nr = f.json["needs_review"]
            at = nr.get("at")
            try:  # stored as ISO text inside the finding's JSON
                at = datetime.fromisoformat(at) if isinstance(at, str) else None
            except ValueError:
                at = None
            add(at, "needs_review", nr.get("reason", "The finding needs review again."))
        decisions = session.scalars(select(FindingDecision).where(
            FindingDecision.finding_id == f.id).order_by(FindingDecision.id)).all()
        # Who decided: the user is stored with every decision, so say so.
        from echolens.db.models import User
        ids = {d.user_id for d in decisions if d.user_id}
        emails = ({u.id: u.email for u in session.scalars(
            select(User).where(User.id.in_(ids))).all()} if ids else {})
        for d in decisions:
            add(d.created_at, "decision", _decision_text(d), note=d.reason or "",
                by=emails.get(d.user_id))

    for w in session.scalars(select(FixWatch).where(
            FixWatch.investigation_id == inv.id).order_by(FixWatch.id)).all():
        if w.issue_number:
            add(w.created_at, "issue", f"Issue #{w.issue_number} opened in {w.repo}.")
        if w.shipped_at or w.fix_date:
            add(w.shipped_at or w.fix_date, "fix_shipped", "The fix shipped — watching for a change.",
                note=w.shipped_note or "")
        if w.status == "confirmed" and w.confirmed_at:
            add(w.confirmed_at, "verified", "Verified fixed — the complaints stopped.")
        elif w.status == "regressed":
            add(w.fix_date, "regressed", "Regressed — the complaints came back.")
        elif w.status == "persists_reopened":
            add(w.fix_date, "regressed", "The fix didn't hold — complaints continued.")

    from echolens.investigator.recover import MAX_HUMAN_EXTENSIONS
    for ext in inv.extensions_json or []:
        try:  # stored as ISO text inside the JSON list
            at = datetime.fromisoformat(ext["at"]) if isinstance(ext.get("at"), str) else None
        except ValueError:
            at = None
        add(at, "extended",
            f"Given +{ext.get('steps', 5)} steps (extension {ext.get('n', '?')} "
            f"of {MAX_HUMAN_EXTENSIONS}).", by=ext.get("by"))

    # The zombie watchdog's stop, from the FAIL step it wrote into the trace.
    for step in session.scalars(select(TraceStep).where(
            TraceStep.investigation_id == inv.id, TraceStep.kind == "FAIL")).all():
        if (step.content_json or {}).get("code") == "watchdog":
            add(step.created_at, "stopped", step.content_json.get("text", "Stopped."))

    # A re-opened child means this case's story continues elsewhere.
    child = session.scalars(select(Investigation).where(
        Investigation.reopens_investigation_id == inv.id).order_by(Investigation.id)).first()
    if child is not None:
        add(child.created_at, "reopen", f"Continued as case #{child.id}.", case_id=child.id)

    events.sort(key=lambda e: (e["at"] or ""))
    return events
