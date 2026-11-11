"""Alembic environment. Runs on the connection init_db hands over; from the
command line (`alembic revision`) it opens the configured database itself."""
from alembic import context

from echolens.db.models import Base

config = context.config
connection = config.attributes.get("connection")


def _run(conn) -> None:
    # render_as_batch: SQLite (local, tests) can only ALTER via table rebuilds.
    context.configure(connection=conn, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if connection is not None:
    _run(connection)
else:
    from echolens.db.session import get_engine
    with get_engine().connect() as conn:
        _run(conn)
