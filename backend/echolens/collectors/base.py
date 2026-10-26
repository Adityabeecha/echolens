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

from sqlalchemy import insert, select
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
    # Items that raised during ingest. Reported rather than silently dropped —
    # a run that skipped rows is not the same as one that had nothing to add.
    failed_items: int = 0
    watermark: str | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None and self.failed_items == 0


class Collector(ABC):
    """Base class. Subclasses implement `source`, `fetch` (may be injected), and
    `ingest_item` (normalize + persist one raw item, returning True if inserted)."""

    source: str = "base"

    def __init__(self, identifier: str, product: str | None = None, fetch_fn=None,
                 product_id: int | None = None):
        self.identifier = identifier          # package name / repo
        self.product = product or identifier
        self.product_id = product_id
        self._fetch_fn = fetch_fn             # injectable for tests
        self._known: dict[tuple, dict] = {}   # per-run dedup lookups, see existing()
        self._buffer: dict | None = None      # new rows of the batched page, see stage()

    # ── dedup lookups ───────────────────────────────────────────────────

    def existing(self, session: Session, model, key_col, keys, **filters):
        """The already-stored row for any of `keys`, or None.

        One query per (table, key) per run, then memory. Looking each item up
        separately cost a database round trip per item; over a remote pooled
        connection a 300-review backfill spent minutes on lookups alone.
        """
        if isinstance(keys, str):
            keys = [keys]
        cache_key = (model, key_col.key, tuple(sorted(filters.items())))
        rows = self._known.get(cache_key)
        if rows is None:
            stmt = select(model).where(model.product == self.product)
            for name, value in filters.items():
                stmt = stmt.where(getattr(model, name) == value)
            with session.no_autoflush:
                rows = {getattr(r, key_col.key): r for r in session.scalars(stmt).all()}
            self._known[cache_key] = rows
        for k in keys:
            if k in rows:
                return rows[k]
        return None

    def stage(self, session: Session, model, **fields) -> None:
        """Add a new row. During the batched page it is buffered and written with
        one bulk INSERT per table; on the item-by-item path it is a plain add.
        (The ORM inserts row by row when it must read back each new id, and
        nothing here needs them.)"""
        if self._buffer is not None:
            self._buffer.setdefault(model, []).append(fields)
        else:
            session.add(model(**fields))

    def remember(self, model, key_col, key, row, **filters) -> None:
        """Record a row added this run, so a repeat later in the page is a duplicate."""
        rows = self._known.get((model, key_col.key, tuple(sorted(filters.items()))))
        if rows is not None:
            rows[key] = row

    # ── watermark / health persistence ─────────────────────────────────

    def _state(self, session: Session) -> CollectorState:
        st = session.scalars(
            select(CollectorState).where(
                CollectorState.source == self.source,
                CollectorState.identifier == self.identifier,
                CollectorState.product == self.product,
            )
        ).first()
        if st is None:
            st = CollectorState(source=self.source, identifier=self.identifier,
                                product=self.product, product_id=self.product_id,
                                status="idle")
            session.add(st)
            session.flush()
        return st

    # ── the run ─────────────────────────────────────────────────────────

    def run(self, session: Session, limit: int = 200,
            prefetched: list[dict] | None = None) -> CollectResult:
        """Ingest one source, optionally using rows fetched concurrently.

        Network fetching is side-effect free with respect to the database, so
        registry.run_all can overlap it safely. Normal direct callers keep the
        original behavior by omitting ``prefetched``.
        """
        st = self._state(session)
        st.status = "running"
        st.last_run_at = datetime.now(timezone.utc)
        session.flush()
        result = CollectResult(source=self.source, identifier=self.identifier)
        try:
            # Keep all corpus writes behind a savepoint. A constraint failure
            # during the final flush used to escape this try block and leave the
            # caller's shared session unusable for every later collector.
            with session.begin_nested():
                raw = (prefetched if prefetched is not None
                       else self.fetch(since=st.watermark, limit=limit))
                result.fetched = len(raw)
                newest = st.watermark
                self._known = {}
                # Fast path: the whole page in one savepoint and one flush, so
                # inserts go out batched. Any failure (a malformed item, a
                # constraint) rolls back only this attempt and the careful
                # item-by-item path below takes over with identical results.
                fast = self._ingest_page(session, raw)
                if fast is not None:
                    raw = []
                    for inserted, wm in fast:
                        if inserted:
                            result.inserted += 1
                        else:
                            result.skipped_duplicate += 1
                        if wm and (newest is None or wm > newest):
                            newest = wm
                else:
                    self._known = {}
                # Commit the cursor only for a fully ingested page. Even sorted
                # rows can share a timestamp, and prefetched rows may arrive in
                # any order: a partial checkpoint could exclude a failed row.
                # Successful upserts remain persisted and are safe to replay.
                for item in raw:
                # One malformed item must not discard the whole page. The loop
                # was unguarded and the watermark assignment sat AFTER it, so an
                # exception on item 150 of 200 kept the 149 rows already added
                # while leaving the watermark unadvanced — and if the poison item
                # was deterministic (a malformed timestamp, say) every later run
                # re-fetched the same window forever and never got past it.
                    try:
                        # Flush each item while its own savepoint can discard a
                        # malformed/duplicate row without poisoning the page.
                        with session.begin_nested():
                            inserted, wm = self.ingest_item(session, item)
                            session.flush()
                    except Exception as err:
                        result.failed_items += 1
                        log.warning("collector_item_failed", source=self.source,
                                    id=self.identifier, error=f"{type(err).__name__}: {err}")
                        continue
                    if inserted:
                        result.inserted += 1
                    else:
                        result.skipped_duplicate += 1
                    if wm and (newest is None or wm > newest):
                        newest = wm
                if result.failed_items:
                    newest = st.watermark
                result.watermark = newest
                st.watermark = newest
                st.items_last_run = result.inserted
            # A run that dropped items is NOT healthy. source_health computes
            # `errored = status == "error"`, so marking this healthy meant a
            # collector failing on every item still read as fine and the
            # "findings disclose stale sources" guarantee never fired for it.
                st.status = "error" if result.failed_items else "healthy"
                st.last_error = (None if not result.failed_items else
                                 f"{result.failed_items} item(s) could not be ingested")
                session.flush()
                log.info("collector_run", source=self.source, id=self.identifier,
                         fetched=result.fetched, inserted=result.inserted)
        except Exception as err:  # a broken source must not crash the app
            result.error = f"{type(err).__name__}: {err}"
            st.status = "error"
            st.last_error = result.error
            log.error("collector_failed", source=self.source, id=self.identifier, error=result.error)
        # The failure status is outside the failed savepoint and is safe to
        # persist; if even this flush fails, let session_scope own the rollback.
        session.flush()
        return result

    def _ingest_page(self, session: Session, raw: list[dict]) -> list[tuple] | None:
        """All items in one savepoint and one flush; None if anything failed."""
        if not raw:
            return []
        self._buffer = {}
        try:
            with session.begin_nested():
                with session.no_autoflush:
                    outcomes = [self.ingest_item(session, item) for item in raw]
                for model, rows in self._buffer.items():
                    session.execute(insert(model), rows)
                session.flush()
            return outcomes
        except Exception as err:
            log.info("collector_batch_fallback", source=self.source, id=self.identifier,
                     error=f"{type(err).__name__}: {err}")
            return None
        finally:
            self._buffer = None

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
