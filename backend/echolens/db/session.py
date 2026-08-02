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
    ("investigations", "data_notes", "JSON"),
    ("review_feedback", "user_id", "INTEGER"),
    ("review_feedback", "reason", "VARCHAR"),
    ("reviews", "product", "VARCHAR"),
    ("issues", "product", "VARCHAR"),
    ("issues", "labels", "JSON"),
    ("issues", "embedding", "JSON"),
    ("posts", "product", "VARCHAR"),
    ("posts", "embedding", "JSON"),
    ("releases", "product", "VARCHAR"),
    ("anomaly_events", "parent_case_id", "INTEGER"),
    # v8.0 product scoping
    ("anomaly_events", "product_id", "INTEGER"),
    ("anomaly_events", "window_start", "TIMESTAMP"),
    ("anomaly_events", "window_end", "TIMESTAMP"),
    ("anomaly_events", "merged_into_id", "INTEGER"),
    ("knowledge_edges", "graded_case_ids", "JSON"),
    ("investigations", "product_id", "INTEGER"),
    ("findings", "product_id", "INTEGER"),
    ("fix_watches", "product_id", "INTEGER"),
    ("collector_state", "product_id", "INTEGER"),
    ("users", "last_active_product_id", "INTEGER"),
    # v9.0 portfolio
    ("investigations", "seeded_from_pattern", "JSON"),
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
    _migrate_product_scoped_external_ids(engine)
    # v8.0: create Products from existing bindings and scope legacy rows (idempotent).
    try:
        from echolens.db.migrate import backfill_products
        with sessionmaker(bind=engine, expire_on_commit=False)() as s:
            backfill_products(s)
            s.commit()
    except Exception as err:  # never block startup on the backfill — but never hide it
        # A failed backfill leaves rows with product_id NULL, which every
        # `WHERE product_id = ?` filter then hides while they remain reachable by
        # direct id. Silently invisible data is worse than a loud failure.
        from echolens.logging import get_logger
        get_logger("db").error("product_backfill_failed", error=str(err))


_SCOPED_EXT_ID_TABLES = {
    "reviews": "uq_reviews_ext_product",
    "posts": "uq_posts_ext_product",
    "feedback_entries": "uq_feedback_entries_ext_product",
}


def _migrate_product_scoped_external_ids(engine) -> None:
    """Replace legacy global ext_id uniqueness with (ext_id, product).

    Fresh databases get the composite constraints from the ORM metadata. This
    migration preserves populated SQLite/Postgres installations created before
    that correction; create_all() cannot alter an existing constraint.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table_name, constraint_name in _SCOPED_EXT_ID_TABLES.items():
        if table_name not in tables:
            continue
        uniques = inspector.get_unique_constraints(table_name)
        legacy = [u for u in uniques if u.get("column_names") == ["ext_id"]]
        composite = any(u.get("column_names") == ["ext_id", "product"] for u in uniques)
        if not legacy and composite:
            continue
        if engine.dialect.name == "sqlite":
            _rebuild_sqlite_scoped_ext_id_table(engine, table_name)
            inspector = inspect(engine)
            continue
        with engine.begin() as conn:
            for unique in legacy:
                name = unique.get("name")
                if name:
                    conn.execute(text(
                        f'ALTER TABLE "{table_name}" DROP CONSTRAINT "{name}"'))
            if not composite:
                conn.execute(text(
                    f'ALTER TABLE "{table_name}" ADD CONSTRAINT "{constraint_name}" '
                    'UNIQUE (ext_id, product)'))


def _rebuild_sqlite_scoped_ext_id_table(engine, table_name: str) -> None:
    """SQLite cannot drop a UNIQUE constraint, so rebuild one corpus table."""
    table = Base.metadata.tables[table_name]
    legacy_name = f"{table_name}__global_ext_id"
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.commit()
        transaction = conn.begin()
        try:
            # Named indexes retain their names after ALTER TABLE RENAME and
            # would collide with the indexes SQLAlchemy creates on the new row.
            for row in conn.exec_driver_sql(f'PRAGMA index_list("{table_name}")'):
                index_name = row[1]
                if not index_name.startswith("sqlite_autoindex"):
                    conn.exec_driver_sql(f'DROP INDEX "{index_name}"')
            conn.exec_driver_sql(
                f'ALTER TABLE "{table_name}" RENAME TO "{legacy_name}"')
            table.create(conn)
            columns = ", ".join(f'"{c.name}"' for c in table.columns)
            conn.exec_driver_sql(
                f'INSERT INTO "{table_name}" ({columns}) '
                f'SELECT {columns} FROM "{legacy_name}"')
            conn.exec_driver_sql(f'DROP TABLE "{legacy_name}"')
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
        finally:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.commit()


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
