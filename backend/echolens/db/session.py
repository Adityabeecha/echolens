from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from echolens.config import settings
from echolens.db.models import Base

_engine = None
_SessionLocal: sessionmaker | None = None

# Additive columns introduced after the first schema was created. create_all()
# makes new *tables* but never ALTERs existing ones, so we add these by hand.
# Nullable-only, so it is safe and idempotent on a populated dev database.
_ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    ("investigations", "reopens_investigation_id", "INTEGER"),
    ("investigations", "checkpoint_json", "JSON"),
    ("review_feedback", "user_id", "INTEGER"),
    ("reviews", "product", "VARCHAR"),
    ("issues", "product", "VARCHAR"),
    ("issues", "labels", "JSON"),
    ("issues", "embedding", "JSON"),
    ("posts", "product", "VARCHAR"),
    ("posts", "embedding", "JSON"),
    ("releases", "product", "VARCHAR"),
]


def get_engine(db_url: str | None = None):
    global _engine, _SessionLocal
    if _engine is None or db_url is not None:
        url = db_url or settings.echolens_db_url
        # SQLite needs check_same_thread=False so the API's background
        # investigation thread can share the engine.
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        _engine = create_engine(url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_db(db_url: str | None = None) -> None:
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl_type in _ADDITIVE_COLUMNS:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl_type}'))


@contextmanager
def session_scope(db_url: str | None = None) -> Iterator[Session]:
    get_engine(db_url)
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
