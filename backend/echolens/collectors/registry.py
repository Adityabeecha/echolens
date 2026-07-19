"""Collector configuration + a run-all entry point.

Collectors are declared in `SourceConfig` rows (kept simple: an in-code default
list plus whatever CollectorState rows already exist). `run_all` executes each
enabled collector and returns per-source results — used by the CLI, the API,
and the scheduler.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.collectors.base import Collector, CollectResult
from echolens.config import settings
from echolens.db.models import CollectorState
from echolens.collectors.github import GitHubCollector
from echolens.collectors.play_store import PlayStoreCollector

# Reddit was dropped as a live source: Reddit ended free API access in 2026.
# The search_reddit tool and Post corpus remain (filled via CSV/import later).
_BUILDERS = {
    "play_store": lambda ident, product: PlayStoreCollector(ident, product),
    "github": lambda ident, product: GitHubCollector(ident, product),
}


@dataclass
class SourceConfig:
    source: str
    identifier: str
    product: str | None = None

    def build(self) -> Collector:
        return _BUILDERS[self.source](self.identifier, self.product)


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


def run_all(session: Session, limit: int = 200) -> list[CollectResult]:
    results = []
    for cfg in configured_sources(session):
        results.append(cfg.build().run(session, limit=limit))
    return results


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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
        last = _aware(st.last_run_at)
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
