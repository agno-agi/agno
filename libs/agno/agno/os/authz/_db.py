"""Shared helper: reuse an agno database's SQLAlchemy engine.

Lets the managed-roles / user-directory / audit stores share the exact connection
(and pool) of the database you already pass to ``AgentOS(db=...)``, instead of
opening a second one against a duplicated ``db_url``.
"""

from typing import Any

# Raised/shown when a managed-roles component is used without a database. Managed
# roles must be persisted: an in-memory store can't stay consistent across the
# multiple workers/replicas an AgentOS deployment runs, so a DB is required.
NO_DB_MESSAGE = (
    "ManagedRoleStore requires a SQL database — managed roles must be persisted, "
    "and an in-memory store cannot stay consistent across multiple workers/replicas. "
    "Pass db=/db_url= to the store, or hand it to AgentOS via "
    "AuthorizationConfig(role_store=...) together with a SQL db on AgentOS so the "
    "store adopts it."
)


def engine_from_db(db: Any) -> Any:
    """Return the SQLAlchemy ``Engine`` backing an agno database object.

    agno's relational databases (``SqliteDb``, ``PostgresDb``, ...) expose their
    engine as ``.db_engine``. Anything with that attribute works.
    """
    engine = getattr(db, "db_engine", None)
    if engine is None:
        raise ValueError(
            "db= must be an agno database backed by SQLAlchemy (e.g. SqliteDb, "
            f"PostgresDb) exposing a .db_engine; got {type(db)!r}. "
            "Pass db_url=... instead if you want a separate connection."
        )
    return engine


def engine_from_url(db_url: str) -> Any:
    """Create a SQLAlchemy ``Engine`` from a URL. SQLite is configured for
    multi-threaded server use (``check_same_thread=False``) so a connection opened
    on one request thread can be reused on another — the same property AgentOS
    needs from any DB it serves decisions from."""
    import sqlalchemy as sa

    if db_url.startswith("sqlite"):
        return sa.create_engine(db_url, connect_args={"check_same_thread": False})
    return sa.create_engine(db_url)
