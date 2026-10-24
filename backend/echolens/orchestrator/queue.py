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

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Investigation, LLMCall, QueuedInvestigation
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


# Shared by Settings and critical-case continuations. Product overrides layer
# over workspace settings; a displayed cap and an enforced cap must agree.
DEFAULT_MONTHLY_BUDGET = 25.0


def effective_limits(session: Session, product_id: int | None = None) -> dict:
    from echolens.config import BUDGET_TIERS, ORCHESTRATOR_DAILY_INVESTIGATIONS, ORCHESTRATOR_DAILY_COST_USD
    from echolens.db.models import Product, Setting
    row = session.get(Setting, "limits", populate_existing=True)
    defaults = {"daily_investigations": ORCHESTRATOR_DAILY_INVESTIGATIONS,
                "per_case_budget": BUDGET_TIERS["standard"].max_cost_usd,
                "per_case_wall_min": BUDGET_TIERS["standard"].max_wall_clock_s // 60,
                "daily_cost_budget": ORCHESTRATOR_DAILY_COST_USD,
                "monthly_budget": DEFAULT_MONTHLY_BUDGET}
    merged = {**defaults, **(row.value if row else {})}
    product = session.get(Product, product_id, populate_existing=True) if product_id is not None else None
    return {**merged, **(product.limits_json or {})} if product else merged


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


def _anomaly_for(session: Session, product_id: int | None, slug: str) -> AnomalyEvent | None:
    """The anomaly with this slug BELONGING TO THIS PRODUCT.

    Slugs are derived from complaint text, so two products with the same
    complaint ("battery-drain") legitimately share one. Looking a slug up
    without the product returned whichever row was created first, which meant a
    second product's theme resolved to the FIRST product's anomaly: the case
    was created under the wrong product and then 404'd on open, because the
    ownership check correctly refused a cross-product row.

    A NULL product_id on an existing row is treated as matching, so rows
    predating product scoping are still found rather than silently duplicated.
    """
    q = select(AnomalyEvent).where(AnomalyEvent.slug == slug)
    if product_id is not None:
        # `IN (id, NULL)` would NOT match a NULL row: in SQL, `NULL = NULL` is
        # unknown, not true, so IN silently skips it. A legacy unscoped row was
        # then invisible here and the caller tried to INSERT a duplicate slug,
        # which the unique index rejects. IS NULL has to be spelled out.
        q = q.where(or_(AnomalyEvent.product_id == product_id,
                        AnomalyEvent.product_id.is_(None)))
    # Prefer this product's own row over a legacy unscoped one.
    return session.scalars(
        q.order_by(AnomalyEvent.product_id.is_(None), AnomalyEvent.id.desc())
    ).first()


def find_existing(session: Session, product_id: int | None, slug: str) -> dict | None:
    """Is this theme/anomaly already being handled, FOR THIS PRODUCT?

    Selecting something that is already under investigation must show "already
    under investigation -> view case", never queue a duplicate.
    """
    anomaly = _anomaly_for(session, product_id, slug)
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

    # Scoped to the product for the same reason as find_existing: an unscoped
    # slug lookup adopted another product's anomaly, so the investigation was
    # created against the wrong product_id and 404'd when opened.
    anomaly = _anomaly_for(session, product_id, slug)
    if anomaly is None:
        anomaly = AnomalyEvent(
            slug=slug, type="manual_theme", metric="theme volume",
            delta=0.0, z=0.0, window="90d",
            description=statement, status="pending", product_id=product_id)
        session.add(anomaly)
        session.flush()
    else:
        anomaly.status = "pending"
        # Claim a legacy unscoped row for this product rather than leaving a
        # NULL that no product-scoped query will ever match again.
        if anomaly.product_id is None and product_id is not None:
            anomaly.product_id = product_id
        session.flush()

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
    it behaves the same on SQLite (naive) and Postgres (aware).

    The cutoff matches the DIALECT rather than always being naive. Comparing a
    naive literal against a Postgres TIMESTAMPTZ column is ambiguous — the
    server applies its own timezone — and this deployment runs on Supabase, so
    the daily cap could behave differently in production than in the tests. The
    two-day margin means the SQL filter only has to be approximately right; the
    exact date match below is what decides. Getting it wrong would still have
    dropped rows near the boundary.
    """
    naive_column = session.bind is not None and session.bind.dialect.name == "sqlite"
    cutoff = (as_of.replace(tzinfo=None) if naive_column else as_of) - timedelta(days=2)
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


# A tier's typical cost needs a few real cases behind it before it means
# anything; below this the tier's cap is shown instead, labelled as such.
MIN_COST_SAMPLES = 3


def deferred_note(daily_limit: int) -> str:
    return f"Deferred: daily limit {daily_limit} reached; runs tomorrow"


def estimate_cost(session: Session, tier: str, product_id: int | None = None) -> dict:
    """What one more case at this tier is likely to cost — always an ESTIMATE.

    The median of what past cases at the same tier actually cost (LLM calls
    summed per case), when there are enough of them; otherwise the tier's
    configured ceiling, which is an upper bound rather than a typical figure,
    and says so.
    """
    from sqlalchemy import func

    from echolens.config import BUDGET_TIERS
    cap = BUDGET_TIERS.get(tier) or BUDGET_TIERS["standard"]
    stmt = (select(func.sum(LLMCall.cost))
            .join(Investigation, Investigation.id == LLMCall.investigation_id)
            .where(Investigation.budget_tier == tier,
                   Investigation.status != "running")
            .group_by(Investigation.id)
            .order_by(Investigation.id.desc())
            .limit(50))
    if product_id is not None:
        stmt = stmt.where(Investigation.product_id == product_id)
    costs = sorted(float(c or 0.0) for c in session.scalars(stmt).all())
    if len(costs) >= MIN_COST_SAMPLES:
        mid = len(costs) // 2
        median = costs[mid] if len(costs) % 2 else (costs[mid - 1] + costs[mid]) / 2
        return {"usd": round(median, 4), "basis": "median",
                "samples": len(costs), "tier": tier, "is_estimate": True}
    return {"usd": round(float(cap.max_cost_usd), 4), "basis": "tier_cap",
            "samples": len(costs), "tier": tier, "is_estimate": True}


def queue_view(session: Session, product_id: int | None, daily_limit: int,
               as_of: datetime | None = None) -> dict:
    """The queue as Today and Cases show it: position, what is running, and which
    items are past today's budget (with the reason, not silence)."""
    now = as_of or datetime.now(timezone.utc)
    used = investigations_today(session, product_id, now)
    remaining = max(0, daily_limit - used)
    estimates: dict[str, dict] = {}

    running_stmt = select(QueuedInvestigation).where(QueuedInvestigation.status == "running")
    if product_id is not None:
        running_stmt = running_stmt.where(QueuedInvestigation.product_id == product_id)
    running = session.scalars(running_stmt).all()

    items = []
    for i, row in enumerate(pending(session, product_id)):
        beyond = i >= remaining
        tier = row.budget_tier or "quick"
        if beyond and tier not in estimates:
            estimates[tier] = estimate_cost(session, tier, product_id)
        items.append({
            "queue_id": row.id, "position": i + 1, "title": row.title,
            "source": row.source, "budget_tier": row.budget_tier,
            "anomaly_id": row.anomaly_id, "investigation_id": row.investigation_id,
            "status": "deferred" if beyond else "queued",
            "note": (deferred_note(daily_limit) if beyond else None),
            "estimate": estimates.get(tier) if beyond else None,
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


# How long a claimed item may sit in 'running' before it is treated as
# abandoned. Longer than any tier's wall-clock budget, so a slow-but-alive
# investigation is never reclaimed out from under itself.
STALE_RUNNING_AFTER = timedelta(hours=2)


def requeue_abandoned(session: Session, product_id: int | None = None,
                      as_of: datetime | None = None) -> list[int]:
    """Return rows that were claimed but never finished to the queue.

    claim_next flips a row to 'running' and only finish() clears it, so a crash
    or a redeploy between the two left the row 'running' forever: excluded from
    pending() so it never ran again, and shown in queue_view's running list
    indefinitely. Investigation rows already had recover.resume_running for
    this; the queue had nothing.
    """
    now = as_of or datetime.now(timezone.utc)
    stmt = select(QueuedInvestigation).where(QueuedInvestigation.status == "running")
    if product_id is not None:
        stmt = stmt.where(QueuedInvestigation.product_id == product_id)
    freed: list[int] = []
    for row in session.scalars(stmt).all():
        started = aware_utc(row.started_at)
        if started is not None and (now - started) < STALE_RUNNING_AFTER:
            continue                      # still plausibly alive
        row.status = "queued"
        row.started_at = None
        freed.append(row.id)
        log.warning("requeued_abandoned", queue_id=row.id, product_id=row.product_id)
    if freed:
        session.flush()
    return freed


def claim_next(session: Session, product_id: int | None, daily_limit: int,
               as_of: datetime | None = None) -> QueuedInvestigation | None:
    """Take the next item to run, or None when the budget is spent.

    The claim is one conditional UPDATE (`status='queued'` -> `running`) whose
    row count says whether THIS caller won. Flipping the loaded object was only
    safe inside one process: two worker processes both read the row as queued,
    both set it running, and both ran it. Now the loser moves on to the next
    candidate. (Postgres and SQLite alike — no locking dialect needed.)
    """
    from sqlalchemy import update

    now = as_of or datetime.now(timezone.utc)
    # Reclaim anything a previous worker died holding, before deciding there is
    # nothing to run.
    requeue_abandoned(session, product_id, now)
    if investigations_today(session, product_id, now) >= daily_limit:
        return None
    for row in pending(session, product_id):
        res = session.execute(
            update(QueuedInvestigation)
            .where(QueuedInvestigation.id == row.id, QueuedInvestigation.status == "queued")
            .values(status="running", started_at=now)
            .execution_options(synchronize_session=False))
        if res.rowcount == 1:
            session.refresh(row)
            return row
    return None


def claim_override(session: Session, queue_id: int, *, user: str | None,
                   estimate_usd: float | None,
                   as_of: datetime | None = None) -> QueuedInvestigation | None:
    """"Investigate now anyway": claim ONE specific queued row past the cap.

    The bypass is per row and leaves a trail on it — who, when, and the
    estimate they were shown — so a day that ran over budget can be explained
    afterwards. Returns None when the row is no longer waiting (already
    running, finished or cancelled), so a double click cannot run it twice.
    """
    from sqlalchemy import update

    now = as_of or datetime.now(timezone.utc)
    row = session.get(QueuedInvestigation, queue_id)
    if row is None or row.status != "queued":
        return None
    # Conditional, like claim_next: a worker may be claiming this same row.
    res = session.execute(
        update(QueuedInvestigation)
        .where(QueuedInvestigation.id == queue_id, QueuedInvestigation.status == "queued")
        .values(status="running", started_at=now)
        .execution_options(synchronize_session=False))
    if res.rowcount != 1:
        return None
    session.refresh(row)
    row.override_by = user or "unknown"
    row.override_at = now
    row.override_estimate_usd = estimate_usd
    session.flush()
    log.info("queue_cap_override", queue_id=row.id, product_id=row.product_id,
             by=row.override_by, estimate_usd=estimate_usd)
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
