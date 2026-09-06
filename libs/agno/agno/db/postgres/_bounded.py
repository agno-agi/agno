"""Dedicated bounded pools retaining configured PostgreSQL connection behavior."""

from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic
from weakref import WeakSet

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.pool import QueuePool
from sqlalchemy.util.queue import Queue

from agno.utils.bounded import WorkBudget

_connecting: ContextVar[bool] = ContextVar("agno_bounded_connect", default=False)
_configured: WeakSet = WeakSet()
_configuration_lock = Lock()
_checkout_budget: ContextVar = ContextVar("agno_checkout_budget", default=None)
_optional_checkout: ContextVar = ContextVar("agno_optional_checkout", default=None)


class ConnectionUnavailable(TimeoutError):
    """Optional work requires a new connection instead of a pooled connection."""


class _BudgetQueue(Queue):
    def get(self, block=True, timeout=None):
        budget = _checkout_budget.get()
        if block and budget is not None:
            remaining = budget.remaining()
            optional_deadline = _optional_checkout.get()
            if optional_deadline is not None:
                remaining = min(remaining, max(0, optional_deadline - monotonic()))
            timeout = remaining if timeout is None else min(timeout, remaining)
        return super().get(block, timeout)


class _BudgetPool(QueuePool):
    _queue_class = _BudgetQueue


@contextmanager
def optional_connection(budget: WorkBudget):
    """Bound optional pool waits; connection establishment stays on the primary path.

    A new connection's transport handshake cannot honor a subsecond SQL deadline.
    Callers can instead execute optional work serially on their existing snapshot.
    """
    token = _optional_checkout.set(monotonic() + 0.025)
    try:
        with primary_connection(budget):
            yield
    except PoolTimeout as exc:
        raise ConnectionUnavailable("optional_connection_unavailable") from exc
    finally:
        _optional_checkout.reset(token)


@contextmanager
def primary_connection(budget: WorkBudget):
    """Limit pool checkout to this operation's deadline without changing shared state."""
    token = _checkout_budget.set(budget)
    try:
        budget.remaining()
        yield
    finally:
        _checkout_budget.reset(token)


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
        if _optional_checkout.get() is not None:
            raise ConnectionUnavailable("optional_connection_unavailable")
        token = _connecting.set(True)
        try:
            # The original creator includes connect_args and credential listeners.
            return original_pool._invoke_creator(connection_record)
        finally:
            _connecting.reset(token)

    pool = _BudgetPool(
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
