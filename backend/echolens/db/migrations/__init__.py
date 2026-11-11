"""Schema migrations (Alembic), for changes `create_all` cannot make.

How the schema evolves:
  * a NEW table or a NEW nullable column: add it to models.py (plus, for a
    column on an existing table, a line in session._ADDITIVE_COLUMNS). No
    migration needed; startup creates it.
  * anything else (rename, drop, type change, new constraint, data fix): a
    migration here, so it runs once, in order, and can be reversed.

Write one with:
    cd backend && python -m alembic -c echolens/db/migrations/alembic.ini revision -m "rename x to y"
then fill in upgrade()/downgrade(). init_db applies pending ones on startup.

Databases created before migrations existed are stamped at the baseline (their
schema already matches it) and upgraded from there; a brand-new database is
built by create_all at the latest models and stamped at head.
"""
from __future__ import annotations

from pathlib import Path

DIR = Path(__file__).resolve().parent
BASELINE = "0001_baseline"


def _config(connection):
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", str(DIR))
    cfg.attributes["connection"] = connection
    return cfg


def apply(engine, existed_before: bool) -> None:
    """Bring the database to head. `existed_before`: the schema predates this
    startup's create_all, so it is at least the baseline but maybe no newer."""
    from alembic import command
    from alembic.runtime.migration import MigrationContext
    with engine.begin() as conn:
        cfg = _config(conn)
        if MigrationContext.configure(conn).get_current_revision() is None:
            command.stamp(cfg, BASELINE if existed_before else "head")
        command.upgrade(cfg, "head")
