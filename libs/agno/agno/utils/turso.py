"""SQLAlchemy engine helper for Turso via the ``pyturso`` driver.

``pyturso`` (imported as ``turso``) is the Python binding for Turso Database — the
from-scratch, SQLite-compatible engine (formerly "Limbo"). It is DB-API 2.0
compatible and, with the ``sqlalchemy`` extra, ships an auto-registered SQLAlchemy
dialect (via entry points):

    - ``sqlite+turso://``   local database (sync)

Unlike the older libSQL driver, the Turso engine implements ``RETURNING`` natively,
so SQLAlchemy's ``INSERT ... RETURNING`` + ``COMMIT`` pattern works without any
autocommit workaround. Its ``set_isolation_level`` is a no-op (reports SERIALIZABLE).

Concurrency note: Turso is a single-writer, in-process engine (like SQLite) but,
being beta, it does not reliably honor a busy-timeout — concurrent connections
raise ``database is locked`` immediately instead of waiting. Unlike Postgres
(server-side MVCC) or stdlib ``sqlite3`` (default 5s busy-timeout that waits), we
therefore serialize access through a single connection so writes never contend.

This helper targets local Turso database files only.
"""

from pathlib import Path
from typing import Optional

try:
    import turso  # noqa: F401  (pyturso; registers the sqlite+turso SQLAlchemy dialect)

    from sqlalchemy.engine import Engine, create_engine
    from sqlalchemy.pool import StaticPool
except ImportError:
    raise ImportError('`pyturso` not installed. Please install using `pip install "pyturso[sqlalchemy]"`')


def _local_path(db_file: Optional[str]) -> str:
    """Resolve a local database path (creating parent dirs), or ':memory:'."""
    if db_file is None:
        return str(Path("./agno.db").resolve())
    if db_file == ":memory:":
        return ":memory:"
    path = Path(db_file).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def create_turso_engine(*, db_file: Optional[str] = None) -> Engine:
    """Build a SQLAlchemy engine for a local Turso (pyturso) database.

    Access is serialized through a single connection (see the module docstring):
    the Turso beta engine returns ``database is locked`` on concurrent connections
    rather than waiting, so a one-connection pool avoids write-lock contention. The
    connection is checked out exclusively, so it is never used concurrently across
    the server's worker threads.

    Args:
        db_file: Local database file path (``:memory:`` for in-memory). Defaults to ``./agno.db``.

    Returns:
        A configured SQLAlchemy ``Engine`` using the ``sqlite+turso`` dialect.
    """
    local = _local_path(db_file)

    if local == ":memory:":
        # A single shared connection keeps the in-memory database alive.
        return create_engine("sqlite+turso:///:memory:", poolclass=StaticPool)

    # One connection, checked out exclusively -> writes are serialized (no lock contention).
    return create_engine(f"sqlite+turso:///{local}", pool_size=1, max_overflow=0)
