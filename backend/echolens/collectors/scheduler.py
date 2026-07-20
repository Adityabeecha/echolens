"""Collector scheduler (v1.0). APScheduler runs collectors on a cron interval
with per-collector health tracked in CollectorState. Optional — the app runs
fine without it (GitHub Actions cron is the free-tier alternative in prod).
"""
from __future__ import annotations

from echolens.config import settings
from echolens.db.session import session_scope
from echolens.logging import get_logger

log = get_logger("scheduler")

_scheduler = None


def _collect_job() -> None:
    from sqlalchemy import select

    from echolens.collectors.registry import run_all
    from echolens.db.models import Product
    from echolens.detector.detect import scan

    with session_scope() as session:
        results = run_all(session)
    # Collecting without scanning just piles up rows nobody looks at. Scan EVERY
    # product: since v8.0 an unscoped scan silently falls back to the first one.
    with session_scope() as session:
        for p in session.scalars(select(Product)).all():
            try:
                found = scan(session, product=p.name, product_id=p.id)
                log.info("scheduled_scan", product=p.name, anomalies=len(found))
            except Exception as err:  # one bad product must not stop the rest
                log.error("scheduled_scan_failed", product=p.name, error=str(err))
    healthy = sum(1 for r in results if r.ok)
    log.info("scheduled_collect", collectors=len(results), healthy=healthy,
             inserted=sum(r.inserted for r in results))


def start_scheduler(interval_hours: int | None = None):
    """Start a background scheduler that collects every N hours. Returns the
    scheduler (or None if APScheduler is unavailable)."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except Exception:  # pragma: no cover
        log.warning("apscheduler_unavailable")
        return None

    hours = interval_hours or settings.collector_interval_hours
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(_collect_job, IntervalTrigger(hours=hours),
                       id="collect", replace_existing=True, next_run_time=None)
    _scheduler.start()
    log.info("scheduler_started", interval_hours=hours)
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
