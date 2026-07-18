"""Collector framework (v1.0). Deterministic ingestion — NO LLM, no judgment.

A Collector fetches raw items from a source, normalizes them to corpus rows,
and upserts them idempotently (dedup by ext_id) while advancing a persisted
watermark so repeated runs only pull what's new. The network call is injected
(`fetch_fn`) so collectors are unit-testable offline; the default fetcher lazily
imports the third-party client only when actually run against the live source.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import CollectorState
from echolens.logging import get_logger

log = get_logger("collector")


@dataclass
class CollectResult:
    source: str
    identifier: str
    fetched: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    watermark: str | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None


class Collector(ABC):
    """Base class. Subclasses implement `source`, `fetch` (may be injected), and
    `ingest_item` (normalize + persist one raw item, returning True if inserted)."""

    source: str = "base"

    def __init__(self, identifier: str, product: str | None = None, fetch_fn=None):
        self.identifier = identifier          # package name / repo
        self.product = product or identifier
        self._fetch_fn = fetch_fn             # injectable for tests

    # ── watermark / health persistence ─────────────────────────────────

    def _state(self, session: Session) -> CollectorState:
        st = session.scalars(
            select(CollectorState).where(
                CollectorState.source == self.source,
                CollectorState.identifier == self.identifier,
            )
        ).first()
        if st is None:
            st = CollectorState(source=self.source, identifier=self.identifier,
                                product=self.product, status="idle")
            session.add(st)
            session.flush()
        return st

    # ── the run ─────────────────────────────────────────────────────────

    def run(self, session: Session, limit: int = 200) -> CollectResult:
        st = self._state(session)
        st.status = "running"
        st.last_run_at = datetime.now(timezone.utc)
        session.flush()
        result = CollectResult(source=self.source, identifier=self.identifier)
        try:
            raw = self.fetch(since=st.watermark, limit=limit)
            result.fetched = len(raw)
            newest = st.watermark
            for item in raw:
                inserted, wm = self.ingest_item(session, item)
                if inserted:
                    result.inserted += 1
                else:
                    result.skipped_duplicate += 1
                if wm and (newest is None or wm > newest):
                    newest = wm
            result.watermark = newest
            st.watermark = newest
            st.items_last_run = result.inserted
            st.status = "healthy"
            st.last_error = None
            log.info("collector_run", source=self.source, id=self.identifier,
                     fetched=result.fetched, inserted=result.inserted)
        except Exception as err:  # a broken source must not crash the app
            result.error = f"{type(err).__name__}: {err}"
            st.status = "error"
            st.last_error = result.error
            log.error("collector_failed", source=self.source, id=self.identifier, error=result.error)
        session.flush()
        return result

    # ── subclass hooks ──────────────────────────────────────────────────

    @abstractmethod
    def fetch(self, since: str | None, limit: int) -> list[dict]:
        """Return raw items newer than `since` (a watermark cursor)."""

    @abstractmethod
    def ingest_item(self, session: Session, item: dict) -> tuple[bool, str | None]:
        """Normalize + upsert one item. Return (inserted?, watermark_for_item)."""


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()
