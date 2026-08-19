"""Collector configuration + a run-all entry point.

Collectors are declared in `SourceConfig` rows (kept simple: an in-code default
list plus whatever CollectorState rows already exist). `run_all` executes each
enabled collector and returns per-source results — used by the CLI, the API,
and the scheduler.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.logging import get_logger
from echolens.collectors.base import Collector, CollectResult
from echolens.config import settings
from echolens.db.models import CollectorState
from echolens.collectors.app_store import AppStoreCollector
from echolens.collectors.chrome_web_store import ChromeWebStoreCollector
from echolens.collectors.github import GitHubCollector
from echolens.collectors.github_extra import (
    GitHubActivityCollector, GitHubDiscussionsCollector)
from echolens.collectors.hacker_news import HackerNewsCollector
from echolens.collectors.play_store import PlayStoreCollector
from echolens.collectors.stack_overflow import StackOverflowCollector
from echolens.timeutil import aware_utc

# Reddit was dropped as a live source: Reddit ended free API access in 2026.
# The search_reddit tool and Post corpus remain (filled via CSV/import later).
_BUILDERS = {
    "play_store": lambda ident, product: PlayStoreCollector(ident, product),
    "app_store": lambda ident, product: AppStoreCollector(ident, product),
    "chrome_web_store": lambda ident, product: ChromeWebStoreCollector(ident, product),
    "github": lambda ident, product: GitHubCollector(ident, product),
    "github_discussions": lambda ident, product: GitHubDiscussionsCollector(ident, product),
    "github_activity": lambda ident, product: GitHubActivityCollector(ident, product),
    "hacker_news": lambda ident, product: HackerNewsCollector(ident, product),
    "stack_overflow": lambda ident, product: StackOverflowCollector(ident, product),
}

# Display name + what the identifier means, per source. Used by the connect
# form so it cannot drift from _BUILDERS.
SOURCE_INFO: dict[str, dict[str, str]] = {
    "play_store": {"label": "Play Store",
                   "hint": "package name, e.g. com.spotify.music"},
    "app_store": {"label": "App Store",
                  "hint": "numeric App Store id, e.g. 324684580"},
    "chrome_web_store": {"label": "Chrome Web Store",
                         "hint": "32-character extension id from the store URL"},
    "github": {"label": "GitHub Issues", "hint": "owner/repo"},
    "github_discussions": {"label": "GitHub Discussions",
                           "hint": "owner/repo — needs GITHUB_TOKEN"},
    "github_activity": {"label": "GitHub PRs & commits",
                        "hint": "owner/repo — timeline context, not counted as feedback"},
    "hacker_news": {"label": "Hacker News",
                    "hint": "search term, usually the product name"},
    "stack_overflow": {"label": "Stack Overflow",
                       "hint": "a tag like react-native, or a search phrase"},
}


@dataclass
class SourceConfig:
    source: str
    identifier: str
    product: str | None = None
    product_id: int | None = None
    state_id: int | None = None
    watermark: str | None = None

    def build(self) -> Collector:
        collector = _BUILDERS[self.source](self.identifier, self.product)
        collector.product_id = self.product_id
        return collector


log = get_logger("collector.registry")

def configured_sources(session: Session, product_id: int | None = None) -> list[SourceConfig]:
    """Every enabled collector known to the DB (created via `add_source`)."""
    stmt = select(CollectorState).where(CollectorState.enabled == True)  # noqa: E712
    if product_id is not None:
        stmt = stmt.where(CollectorState.product_id == product_id)
    rows = session.scalars(stmt).all()
    return [SourceConfig(r.source, r.identifier, r.product, r.product_id,
                         r.id, r.watermark) for r in rows]


def add_source(session: Session, source: str, identifier: str, product: str | None = None,
               product_id: int | None = None) -> CollectorState:
    if source not in _BUILDERS:
        raise ValueError(f"unknown source '{source}' (have {list(_BUILDERS)})")
    existing = session.scalars(select(CollectorState).where(
        CollectorState.source == source, CollectorState.identifier == identifier,
        CollectorState.product == (product or identifier))).first()
    if existing:
        existing.enabled = True
        existing.product = product or existing.product
        existing.product_id = product_id or existing.product_id
        session.flush()
        return existing
    st = CollectorState(source=source, identifier=identifier, product=product or identifier,
                        product_id=product_id, status="idle", enabled=True)
    session.add(st)
    session.flush()
    return st


# One slow source must not stall the whole scheduled job. Each collector gets
# its own wall-clock ceiling; exceeding it is recorded as that collector's error
# and the rest still run.
# Keep manual collection below common 30-second reverse-proxy ceilings. Initial
# onboarding uses an explicit longer timeout in its background worker.
COLLECTOR_TIMEOUT_S = 25
MAX_PARALLEL_FETCHES = 6


def _run_one(cfg: SourceConfig, session: Session, limit: int) -> CollectResult:
    """Compatibility wrapper for one bounded, safely prefetched source."""
    return _run_configs(session, [cfg], limit, COLLECTOR_TIMEOUT_S)[0]


def _state_for(session: Session, cfg: SourceConfig) -> CollectorState | None:
    if cfg.state_id is not None:
        return session.get(CollectorState, cfg.state_id)
    return session.scalars(select(CollectorState).where(
        CollectorState.source == cfg.source,
        CollectorState.identifier == cfg.identifier,
        CollectorState.product == cfg.product)).first()


def _run_configs(session: Session, configs: list[SourceConfig], limit: int,
                 timeout_s: float) -> list[CollectResult]:
    """Fetch concurrently, then ingest serially on the caller's DB session.

    Network waits dominate collection and are independent. SQLAlchemy sessions
    are not thread-safe, so only fetches overlap; every write remains ordered on
    this thread. The deadline covers the whole batch rather than each source.
    """
    if not configs:
        return []

    started = datetime.now(timezone.utc)
    for cfg in configs:
        state = _state_for(session, cfg)
        if state is not None:
            state.status = "running"
            state.last_run_at = started
    session.flush()

    slots = threading.Semaphore(max(1, min(MAX_PARALLEL_FETCHES, len(configs))))
    cancelled = threading.Event()
    lock = threading.Lock()
    fetched: dict[int, tuple[Collector | None, list[dict] | None, str | None, float]] = {}
    batch_started = time.monotonic()

    def fetch_one(index: int, cfg: SourceConfig) -> None:
        with slots:
            if cancelled.is_set():
                return
            source_started = time.monotonic()
            try:
                collector = cfg.build()
                rows = collector.fetch(since=cfg.watermark, limit=limit)
                payload = (collector, rows, None, time.monotonic() - source_started)
            except Exception as err:
                payload = (None, None, f"{type(err).__name__}: {err}",
                           time.monotonic() - source_started)
            with lock:
                fetched[index] = payload

    threads = [threading.Thread(
        target=fetch_one, args=(index, cfg), daemon=True,
        name=f"fetch-{cfg.source}-{cfg.identifier}")
        for index, cfg in enumerate(configs)]
    for thread in threads:
        thread.start()
    deadline = batch_started + timeout_s
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    cancelled.set()

    results: list[CollectResult] = []
    for index, cfg in enumerate(configs):
        payload = fetched.get(index)
        if payload is None:
            error = f"timed out after {timeout_s:g}s"
            log.error("collector_timeout", source=cfg.source, id=cfg.identifier,
                      seconds=timeout_s)
            result = CollectResult(source=cfg.source, identifier=cfg.identifier,
                                   error=error, duration_s=round(timeout_s, 3))
        else:
            collector, rows, error, fetch_duration = payload
            if error is not None or collector is None or rows is None:
                result = CollectResult(source=cfg.source, identifier=cfg.identifier,
                                       error=error or "collector fetch failed",
                                       duration_s=round(fetch_duration, 3))
                log.error("collector_fetch_failed", source=cfg.source,
                          id=cfg.identifier, error=result.error)
            else:
                ingest_started = time.monotonic()
                result = collector.run(session, limit=limit, prefetched=rows)
                result.duration_s = round(
                    fetch_duration + time.monotonic() - ingest_started, 3)

        if result.error is not None:
            state = _state_for(session, cfg)
            if state is not None:
                state.status = "error"
                state.last_error = result.error
                state.items_last_run = 0
        results.append(result)
    session.flush()
    return results


def run_all(session: Session, limit: int = 100,
            product_id: int | None = None,
            timeout_s: float | None = None) -> list[CollectResult]:
    """Run every configured collector. One failure never stops the rest.

    Collector.run already catches its own exceptions, but a collector that
    raises during CONSTRUCTION (a bad identifier, a missing dependency) used to
    abort the whole scheduled job and leave every later source uncollected with
    no record of why. A collector that HANGS did the same thing more quietly —
    see _run_one.
    """
    return _run_configs(
        session, configured_sources(session, product_id=product_id), limit,
        COLLECTOR_TIMEOUT_S if timeout_s is None else timeout_s)


def run_one(session: Session, cfg: SourceConfig, limit: int = 100,
            timeout_s: float | None = None) -> CollectResult:
    """Run a manually retried source with the same bounded fetch path."""
    return _run_configs(
        session, [cfg], limit,
        COLLECTOR_TIMEOUT_S if timeout_s is None else timeout_s)[0]


def source_health(session: Session, product: str | None = None) -> list[dict]:
    """One health record per enabled collector, with a v3.0 staleness verdict: a
    source is STALE if it errored or hasn't pulled in over 2× the collection
    interval. Findings disclose stale sources so a conclusion is never presented
    as if every source was available (real-data honesty)."""
    now = datetime.now(timezone.utc)
    ttl = timedelta(hours=max(1, settings.collector_interval_hours) * 2)
    out: list[dict] = []
    q = select(CollectorState).where(CollectorState.enabled == True)  # noqa: E712
    if product:
        q = q.where(CollectorState.product == product)
    for st in session.scalars(q).all():
        last = aware_utc(st.last_run_at)
        errored = st.status == "error"
        overdue = last is not None and (now - last) > ttl
        stale = errored or overdue
        out.append({
            "source": st.source, "identifier": st.identifier, "product": st.product,
            "status": st.status, "items_last_run": st.items_last_run,
            "last_run_at": last.isoformat() if last else None,
            "last_error": st.last_error,
            "stale": stale,
            "stale_since": last.date().isoformat() if (overdue and last) else None,
            "never_collected": last is None,
        })
    return out
