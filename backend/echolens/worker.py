"""The investigation worker — `echolens worker`, a second process.

Investigations used to run only as daemon threads inside the web process. A
redeploy, a free-tier OOM kill or one slow request then took the case with it
and left it "running" forever. With RUN_INVESTIGATIONS_IN_WEB=false the API
just records the work (a `worker_jobs` row, or the existing investigation
queue) and this process does it.

Claiming is safe with more than one worker:

* a job is taken with one conditional UPDATE (`status='queued'` -> `running`)
  whose row count says who won; on Postgres the candidate is also selected
  with FOR UPDATE SKIP LOCKED so two workers do not even contend for one row;
* queue rows go through orchestrator/queue.claim_next, which claims the same
  way.

A worker never resumes an interrupted case on its own startup — two workers
starting together would both resume it. The zombie watchdog ends such a case
after 15 minutes without progress and returns its signal to the queue.
"""
from __future__ import annotations

import os
import socket
import time
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from echolens.db.models import Investigation, QueuedInvestigation, Setting, WorkerJob
from echolens.logging import get_logger

log = get_logger("worker")

HEARTBEAT_KEY = "worker_heartbeat"
POLL_SECONDS = 5.0
WATCHDOG_EVERY_SECONDS = 60.0


def worker_name() -> str:
    return f"{socket.gethostname()[:40]}:{os.getpid()}"


def enqueue_job(session: Session, kind: str, args: list) -> WorkerJob:
    job = WorkerJob(kind=kind, args=list(args), status="queued")
    session.add(job)
    session.flush()
    log.info("job_enqueued", job_id=job.id, kind=kind)
    return job


def claim_job(session: Session, worker: str) -> WorkerJob | None:
    """Take the oldest queued job, or None. The caller commits right away so
    the claim is visible to every other worker."""
    candidates = session.scalars(
        select(WorkerJob.id).where(WorkerJob.status == "queued").order_by(WorkerJob.id)
        .limit(5).with_for_update(skip_locked=True)).all()
    for job_id in candidates:
        res = session.execute(
            update(WorkerJob).where(WorkerJob.id == job_id, WorkerJob.status == "queued")
            .values(status="running", claimed_by=worker,
                    claimed_at=datetime.now(timezone.utc))
            .execution_options(synchronize_session=False))
        if res.rowcount == 1:
            job = session.get(WorkerJob, job_id)
            session.refresh(job)
            return job
    return None


def finish_job(session: Session, job_id: int, ok: bool, error: str | None = None) -> None:
    job = session.get(WorkerJob, job_id)
    if job is None:
        return
    job.status = "done" if ok else "failed"
    job.error = (error or None) and error[:500]
    job.finished_at = datetime.now(timezone.utc)
    session.flush()


def heartbeat(session: Session, worker: str) -> None:
    key = f"{HEARTBEAT_KEY}:{worker}"[:64]
    row = session.get(Setting, key)
    value = {"worker": worker, "at": datetime.now(timezone.utc).isoformat()}
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.flush()


def worker_status(session: Session) -> dict:
    """For /health: jobs waiting, and when a worker was last seen."""
    from sqlalchemy import func
    queued = session.scalar(select(func.count(WorkerJob.id)).where(
        WorkerJob.status == "queued")) or 0
    beats = session.scalars(select(Setting).where(
        Setting.key.like(f"{HEARTBEAT_KEY}:%"))).all()
    seen = max(((b.value or {}).get("at") for b in beats if isinstance(b.value, dict)),
               default=None, key=lambda x: x or "")
    return {"jobs_queued": int(queued), "worker_last_seen": seen}


def _run_job(job_id: int, kind: str, args: list) -> None:
    from echolens.api.app import _job_targets
    from echolens.db.session import session_scope
    target = _job_targets().get(kind)
    ok, error = True, None
    try:
        if target is None:
            raise ValueError(f"unknown job kind {kind!r}")
        target(*args)
    except Exception as err:  # one bad job must not stop the worker
        ok, error = False, f"{type(err).__name__}: {err}"
        log.error("job_failed", job_id=job_id, kind=kind, error=error)
    with session_scope() as session:
        finish_job(session, job_id, ok, error)


def _queued_products(session: Session) -> list[int | None]:
    return list(session.scalars(select(QueuedInvestigation.product_id).where(
        QueuedInvestigation.status == "queued").distinct()).all())


def reap_jobs(session: Session) -> int:
    """Close running jobs whose case is no longer running (the watchdog, or the
    case itself, ended it) — a worker that died mid-job leaves its row behind."""
    n = 0
    for job in session.scalars(select(WorkerJob).where(WorkerJob.status == "running")).all():
        args = list(job.args or [])
        if job.kind == "slack_challenge":
            continue                          # its argument is a finding, not a case
        inv_id = (args[1] if len(args) > 1 else None) if job.kind == "claimed" else (
            args[0] if args else None)
        inv = session.get(Investigation, inv_id) if isinstance(inv_id, int) else None
        if inv is not None and inv.status == "failed":
            finish_job(session, job.id, False, "case ended by the watchdog")
            n += 1
    return n


def run_once(worker: str) -> str | None:
    """Do one unit of work. Returns what was done, or None when idle."""
    from echolens.db.session import session_scope
    with session_scope() as session:
        heartbeat(session, worker)
        job = claim_job(session, worker)
        claimed = (job.id, job.kind, list(job.args or [])) if job else None
    if claimed:
        _run_job(*claimed)
        return f"job:{claimed[1]}"
    from echolens.api.app import _drain_one
    with session_scope() as session:
        products = _queued_products(session)
    for pid in products:
        if _drain_one(pid):
            return "queue"
    return None


def watchdog_pass() -> list[int]:
    """The worker's periodic housekeeping: end zombie cases, close the jobs
    they held, and recompute stale "All products" rows so /portfolio rarely
    has to."""
    from echolens.db.session import session_scope
    from echolens.investigator.recover import end_zombies
    from echolens.portfolio import refresh_summaries, stale_products
    with session_scope() as session:
        ended = end_zombies(session)
        reap_jobs(session)
    with session_scope() as session:
        refresh_summaries(session, stale_products(session))
    return ended


def run_worker(worker: str | None = None, poll_s: float = POLL_SECONDS,
               max_iterations: int | None = None, sleep=time.sleep) -> int:
    """Loop until killed (or `max_iterations`, for tests). Returns units done."""
    worker = worker or worker_name()
    log.info("worker_started", worker=worker)
    done = 0
    last_watchdog = 0.0
    i = 0
    while max_iterations is None or i < max_iterations:
        i += 1
        if time.monotonic() - last_watchdog >= WATCHDOG_EVERY_SECONDS:
            try:
                watchdog_pass()
            except Exception as err:
                log.error("watchdog_failed", error=str(err))
            last_watchdog = time.monotonic()
        try:
            did = run_once(worker)
        except Exception as err:  # a DB blip must not end the process
            log.error("worker_iteration_failed", error=str(err))
            did = None
        if did:
            done += 1
            continue
        sleep(poll_s)
    return done
