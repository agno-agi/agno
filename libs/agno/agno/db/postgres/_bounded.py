"""Dedicated bounded pools retaining configured PostgreSQL connection behavior."""

from contextvars import ContextVar
from threading import Lock
from weakref import WeakSet

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

_connecting: ContextVar[bool] = ContextVar("agno_bounded_connect", default=False)
_configured: WeakSet = WeakSet()
_configuration_lock = Lock()


def bounded_engine(source: Engine, *, capacity: int) -> Engine:
    """Copy pool capacity while preserving connect_args and existing credential hooks.

    SQLAlchemy's default creator retains its original connection configuration.
    Arbitrary custom creators must remain outside these deadline-controlled paths.
    """
    if source.dialect.name != "postgresql" or source.dialect.driver not in ("psycopg", "psycopg2"):
        raise ValueError("Bounded PostgreSQL operations require the psycopg or psycopg2 driver")
    creator = source.pool._creator
    if getattr(creator, "__module__", None) != "sqlalchemy.engine.create":
        raise ValueError("Bounded PostgreSQL pools require connect_args or do_connect hooks, not custom creators")
    with _configuration_lock:
        if source not in _configured:

            def connect(dialect, connection_record, args, params):
                if _connecting.get():
                    bounded = dict(params)
                    bounded["connect_timeout"] = 3
                    options = bounded.get("options", "")
                    bounded["options"] = options + " -c statement_timeout=30000 -c lock_timeout=30000"
                    return dialect.connect(*args, **bounded)
                return None

            event.listen(source, "do_connect", connect)
            _configured.add(source)
    original_pool = source.pool

    def create(connection_record):
        token = _connecting.set(True)
        try:
            # The original creator includes connect_args and credential listeners.
            return original_pool._invoke_creator(connection_record)
        finally:
            _connecting.reset(token)

    pool = QueuePool(
        create,
        pool_size=capacity,
        max_overflow=0,
        timeout=3,
        pre_ping=True,
        recycle=300,
        _dispatch=source.pool.dispatch,
        dialect=source.dialect,
    )
    return create_engine(source.url, pool=pool)
