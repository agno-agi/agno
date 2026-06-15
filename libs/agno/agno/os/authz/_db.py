"""Shared helper: reuse an agno database's SQLAlchemy engine.

Lets the managed-roles / user-directory / audit stores share the exact connection
(and pool) of the database you already pass to ``AgentOS(db=...)``, instead of
opening a second one against a duplicated ``db_url``.
"""

from typing import Any


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
