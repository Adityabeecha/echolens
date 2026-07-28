"""Collector configuration + a run-all entry point.

Collectors are declared in `SourceConfig` rows (kept simple: an in-code default
list plus whatever CollectorState rows already exist). `run_all` executes each
enabled collector and returns per-source results — used by the CLI, the API,
and the scheduler.
"""
from __future__ import annotations

import threading
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

    def build(self) -> Collector:
        return _BUILDERS[self.source](self.identifier, self.product)


log = get_logger("collector.registry")

def configured_sources(session: Session) -> list[SourceConfig]:
    """Every enabled collector known to the DB (created via `add_source`)."""
    rows = session.scalars(select(CollectorState).where(CollectorState.enabled == True)).all()  # noqa: E712
    return [SourceConfig(r.source, r.identifier, r.product) for r in rows]


def add_source(session: Session, source: str, identifier: str, product: str | None = None) -> CollectorState:
    if source not in _BUILDERS:
        raise ValueError(f"unknown source '{source}' (have {list(_BUILDERS)})")
    existing = session.scalars(select(CollectorState).where(
        CollectorState.source == source, CollectorState.identifier == identifier)).first()
    if existing:
        existing.enabled = True
        existing.product = product or existing.product
        session.flush()
        return existing
    st = CollectorState(source=source, identifier=identifier, product=product or identifier,
                        status="idle", enabled=True)
    session.add(st)
    session.flush()
    return st


# One slow source must not stall the whole scheduled job. Each collector gets
# its own wall-clock ceiling; exceeding it is recorded as that collector's error
# and the rest still run.
COLLECTOR_TIMEOUT_S = 180


def _run_one(cfg: SourceConfig, session: Session, limit: int) -> CollectResult:
    """One collector, bounded by COLLECTOR_TIMEOUT_S.

    The timeout was declared and documented but never applied — `grep` found
    exactly one reference, the definition — so a hung HTTP call blocked every
    LATER collector indefinitely and the scheduled job never finished.

    A worker thread is the only portable way to bound a blocking socket call.
    The thread is a daemon, so a truly stuck one cannot keep the process alive;
    it is NOT killed, because interrupting a collector mid-write would leave a
    half-ingested page. It simply stops being waited on, and its source is
    recorded as errored so source_health surfaces it.

    The session is used only inside the worker, one collector at a time, so no
    two threads ever touch it concurrently.
    """
    box: dict = {}

    def work():
        try:
            box["result"] = cfg.build().run(session, limit=limit)
        except Exception as err:                      # construction or run
            box["error"] = f"{type(err).__name__}: {err}"

    th = threading.Thread(target=work, daemon=True,
                          name=f"collect-{cfg.source}-{cfg.identifier}")
    th.start()
    th.join(COLLECTOR_TIMEOUT_S)
    if th.is_alive():
        log.error("collector_timeout", source=cfg.source, id=cfg.identifier,
                  seconds=COLLECTOR_TIMEOUT_S)
        return CollectResult(
            source=cfg.source, identifier=cfg.identifier,
            error=f"timed out after {COLLECTOR_TIMEOUT_S}s")
    if "error" in box:
        log.error("collector_build_failed", source=cfg.source,
                  id=cfg.identifier, error=box["error"])
        return CollectResult(source=cfg.source, identifier=cfg.identifier,
                             error=box["error"])
    return box["result"]


def run_all(session: Session, limit: int = 200) -> list[CollectResult]:
    """Run every configured collector. One failure never stops the rest.

    Collector.run already catches its own exceptions, but a collector that
    raises during CONSTRUCTION (a bad identifier, a missing dependency) used to
    abort the whole scheduled job and leave every later source uncollected with
    no record of why. A collector that HANGS did the same thing more quietly —
    see _run_one.
    """
    return [_run_one(cfg, session, limit) for cfg in configured_sources(session)]


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
