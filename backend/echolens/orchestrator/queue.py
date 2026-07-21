"""The investigation queue — one place everything waiting to be investigated.

Before this, a theme card's "Investigate" button started a run immediately. That
fought the daily budget (the cap was checked in one place, manual starts in
another) and forced one-at-a-time clicking. Now selections become queue rows and
the orchestrator drains them:

* **anomalies and manual picks share one queue**, so the daily cap means what it
  says regardless of how the work arrived;
* **order is severity first, then the order you selected in** — a real SEV1
  spike outranks a theme you were curious about;
* **the excess is queued, never dropped**. Work beyond today's budget stays
  visible with a reason attached instead of vanishing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Investigation, QueuedInvestigation
from echolens.logging import get_logger
from echolens.timeutil import aware_utc

log = get_logger("orchestrator.queue")

# Lower sorts first. Anomalies are graded by severity; a manual pick sits below
# every real spike but above nothing at all.
PRIORITY_SEV1 = 10
PRIORITY_SEV2 = 20
PRIORITY_SEV3 = 40
PRIORITY_MANUAL = 60

LIVE_STATUSES = ("queued", "running")


def _severity_priority(anomaly: AnomalyEvent | None) -> int:
    if anomaly is None:
        return PRIORITY_MANUAL
    z = abs(anomaly.z or 0.0)
    if z >= 3:
        return PRIORITY_SEV1
    if z >= 2:
        return PRIORITY_SEV2
    return PRIORITY_SEV3


def open_case_for(session: Session, anomaly_id: int) -> Investigation | None:
    """An investigation already running or resolved for this anomaly."""
    return session.scalars(
        select(Investigation)
        .where(Investigation.anomaly_id == anomaly_id)
        .order_by(Investigation.id.desc())
    ).first()


def find_existing(session: Session, product_id: int | None, slug: str) -> dict | None:
    """Is this theme/anomaly already being handled?

    Selecting something that is already under investigation must show "already
    under investigation -> view case", never queue a duplicate.
    """
    anomaly = session.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == slug)).first()
    if anomaly is None:
        return None
    queued = session.scalars(
        select(QueuedInvestigation).where(
            QueuedInvestigation.anomaly_id == anomaly.id,
            QueuedInvestigation.status.in_(LIVE_STATUSES))
    ).first()
    if queued is not None:
        return {"reason": "queued", "queue_id": queued.id,
                "investigation_id": queued.investigation_id, "slug": slug}
    inv = open_case_for(session, anomaly.id)
    if inv is not None:
        return {"reason": "investigating" if inv.status == "running" else "investigated",
                "queue_id": None, "investigation_id": inv.id, "slug": slug}
    return None


def enqueue_theme(session: Session, *, product_id: int | None, slug: str, statement: str,
                  tier: str = "quick", selection_order: int = 0,
                  verbatims: list[str] | None = None) -> dict:
    """Queue a discovered theme, creating the same anomaly record a spike would.

    Manual work becomes a first-class AnomalyEvent (type "manual_theme") rather
    than a special case, so dedupe, triage, scoping and the archive all apply to
    it without a parallel code path.
    """
    existing = find_existing(session, product_id, slug)
    if existing is not None:
        return {"status": "already", **existing}

    anomaly = session.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == slug)).first()
    if anomaly is None:
        anomaly = AnomalyEvent(
            slug=slug, type="manual_theme", metric="theme volume",
            delta=0.0, z=0.0, window="90d",
            description=statement, status="pending", product_id=product_id)
        session.add(anomaly)
        session.flush()
    else:
        anomaly.status = "pending"

    row = QueuedInvestigation(
        product_id=product_id, anomaly_id=anomaly.id, status="queued",
        source="manual_theme", priority=PRIORITY_MANUAL,
        selection_order=selection_order, budget_tier=tier,
        title=statement or (anomaly.description or slug))
    session.add(row)
    session.flush()
    log.info("queued_theme", slug=slug, queue_id=row.id, product_id=product_id)
    return {"status": "queued", "queue_id": row.id, "slug": slug,
            "anomaly_id": anomaly.id, "investigation_id": None}


def enqueue_anomaly(session: Session, anomaly: AnomalyEvent, tier: str = "standard") -> dict:
    """Queue a detector-found anomaly through the same path as a manual pick."""
    existing = find_existing(session, anomaly.product_id, anomaly.slug or "")
    if existing is not None:
        return {"status": "already", **existing}
    row = QueuedInvestigation(
        product_id=anomaly.product_id, anomaly_id=anomaly.id, status="queued",
        source="anomaly", priority=_severity_priority(anomaly),
        selection_order=0, budget_tier=tier,
        title=anomaly.description or anomaly.metric or (anomaly.slug or ""))
    session.add(row)
    session.flush()
    return {"status": "queued", "queue_id": row.id, "slug": anomaly.slug,
            "anomaly_id": anomaly.id, "investigation_id": None}


def investigations_today(session: Session, product_id: int | None, as_of: datetime) -> int:
    """Cases created today. Bounded scan, then an exact date match in Python so
    it behaves the same on SQLite (naive) and Postgres (aware)."""
    cutoff = as_of.replace(tzinfo=None) - timedelta(days=2)
    stmt = select(Investigation).where(Investigation.created_at >= cutoff)
    if product_id is not None:
        stmt = stmt.where(Investigation.product_id == product_id)
    rows = session.scalars(stmt).all()
    return sum(1 for r in rows
               if r.created_at and aware_utc(r.created_at).date() == as_of.date())


def pending(session: Session, product_id: int | None = None) -> list[QueuedInvestigation]:
    """Everything still waiting, in the order it will actually run."""
    stmt = select(QueuedInvestigation).where(QueuedInvestigation.status == "queued")
    if product_id is not None:
        stmt = stmt.where(QueuedInvestigation.product_id == product_id)
    rows = session.scalars(stmt).all()
    return sorted(rows, key=lambda r: (r.priority, r.selection_order, r.id))


def queue_view(session: Session, product_id: int | None, daily_limit: int,
               as_of: datetime | None = None) -> dict:
    """The queue as the Case Feed shows it: position, what is running, and which
    items are past today's budget (with the reason, not silence)."""
    now = as_of or datetime.now(timezone.utc)
    used = investigations_today(session, product_id, now)
    remaining = max(0, daily_limit - used)

    running_stmt = select(QueuedInvestigation).where(QueuedInvestigation.status == "running")
    if product_id is not None:
        running_stmt = running_stmt.where(QueuedInvestigation.product_id == product_id)
    running = session.scalars(running_stmt).all()

    items = []
    for i, row in enumerate(pending(session, product_id)):
        beyond = i >= remaining
        items.append({
            "queue_id": row.id, "position": i + 1, "title": row.title,
            "source": row.source, "budget_tier": row.budget_tier,
            "anomaly_id": row.anomaly_id, "investigation_id": row.investigation_id,
            "status": "deferred" if beyond else "queued",
            "note": ("daily limit reached — runs tomorrow" if beyond else None),
        })
    return {
        "running": [{"queue_id": r.id, "title": r.title,
                     "investigation_id": r.investigation_id} for r in running],
        "queued": items,
        "used_today": used,
        "daily_limit": daily_limit,
        "remaining_today": remaining,
    }


def cancel(session: Session, queue_id: int) -> bool:
    """Drop a queued item. Running work is left alone — cancelling mid-flight
    would leave a half-written case behind."""
    row = session.get(QueuedInvestigation, queue_id)
    if row is None or row.status != "queued":
        return False
    row.status = "cancelled"
    row.finished_at = datetime.now(timezone.utc)
    anomaly = session.get(AnomalyEvent, row.anomaly_id) if row.anomaly_id else None
    if anomaly is not None and anomaly.type == "manual_theme" and anomaly.status == "pending":
        anomaly.status = "closed"  # a theme nobody investigated shouldn't linger
    session.flush()
    return True


def claim_next(session: Session, product_id: int | None, daily_limit: int,
               as_of: datetime | None = None) -> QueuedInvestigation | None:
    """Take the next item to run, or None when the budget is spent.

    Claiming flips the row to 'running' inside the caller's transaction, so two
    workers cannot pick up the same item.
    """
    now = as_of or datetime.now(timezone.utc)
    if investigations_today(session, product_id, now) >= daily_limit:
        return None
    queue = pending(session, product_id)
    if not queue:
        return None
    row = queue[0]
    row.status = "running"
    row.started_at = now
    session.flush()
    return row


def finish(session: Session, queue_id: int, investigation_id: int | None,
           ok: bool = True) -> None:
    row = session.get(QueuedInvestigation, queue_id)
    if row is None:
        return
    row.status = "done" if ok else "failed"
    row.investigation_id = investigation_id
    row.finished_at = datetime.now(timezone.utc)
    session.flush()
