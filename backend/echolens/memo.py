"""Small in-process caches for work that is expensive and rarely changes.

Two shapes, both bounded and both safe to lose (a restart just recomputes):

* `TTLCache` — key -> value for at most `ttl` seconds, at most `maxsize`
  entries (oldest evicted first). Thread-safe: request threads share it.
* `fingerprinted(...)` — recompute only when the data under it changed. The
  caller supplies a CHEAP fingerprint (one aggregate query: count, max id,
  newest timestamp) and the expensive function; while the fingerprint is the
  same the cached result is returned. A TTL caps how long a change the
  fingerprint cannot see (an edited row) can go unnoticed.

Per process, not shared: a second web worker or the investigation worker keeps
its own copy. Nothing here is a source of truth.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable

_MISSING = object()


class TTLCache:
    def __init__(self, ttl: float, maxsize: int = 1000, clock: Callable[[], float] = time.monotonic):
        self.ttl, self.maxsize, self._clock = ttl, maxsize, clock
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key: Hashable, default=None):
        with self._lock:
            item = self._data.get(key, _MISSING)
            if item is _MISSING or self._clock() - item[0] >= self.ttl:
                if item is not _MISSING:
                    del self._data[key]
                self.misses += 1
                return default
            self.hits += 1
            return item[1]

    def set(self, key: Hashable, value) -> None:
        with self._lock:
            self._data[key] = (self._clock(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def pop(self, key: Hashable) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


# One cache for every fingerprinted computation; keys are namespaced by caller.
_FINGERPRINTED = TTLCache(ttl=600, maxsize=256)


def db_token(bind) -> str:
    """A stable identity for a database engine (or a session's), so a cache
    never answers for a different database. `id()` alone is not enough: a
    garbage-collected engine's id is reused by the next one."""
    engine = getattr(bind, "get_bind", None)
    engine = engine() if callable(engine) else bind
    engine = getattr(engine, "engine", engine)
    token = getattr(engine, "_echolens_memo_token", None)
    if token is None:
        import uuid
        token = uuid.uuid4().hex
        try:
            engine._echolens_memo_token = token
        except AttributeError:
            return str(id(engine))
    return token


def fingerprinted(session, key: Hashable, fingerprint: Hashable, compute: Callable[[], Any]):
    """`compute()`'s result, reused while `fingerprint` is unchanged (≤10 min).
    Scoped to the session's database."""
    key = (db_token(session), key)
    hit = _FINGERPRINTED.get(key, _MISSING)
    if hit is not _MISSING and hit[0] == fingerprint:
        return hit[1]
    value = compute()
    _FINGERPRINTED.set(key, (fingerprint, value))
    return value


def clear_all() -> None:
    """Tests and admin tooling: forget everything."""
    _FINGERPRINTED.clear()


def review_fingerprint(session, product: str | None, since=None, min_rating: int | None = None,
                       max_rating: int | None = None) -> tuple:
    """(count, max id, newest, rating sum, translated count) of a product's
    reviews in a window — one aggregate query, the cheap stand-in for "did the
    corpus change". An edited review TEXT is not visible to it; the 10-minute
    TTL bounds that."""
    from sqlalchemy import func, select

    from echolens.db.models import Review

    stmt = select(func.count(Review.id), func.max(Review.id), func.max(Review.created_at),
                  func.sum(Review.rating), func.count(Review.text_en))
    if product is not None:
        stmt = stmt.where(Review.product == product)
    if since is not None:
        stmt = stmt.where(Review.created_at >= since)
    if min_rating is not None:
        stmt = stmt.where(Review.rating >= min_rating)
    if max_rating is not None:
        stmt = stmt.where(Review.rating <= max_rating)
    return tuple(str(v) for v in session.execute(stmt).one())
