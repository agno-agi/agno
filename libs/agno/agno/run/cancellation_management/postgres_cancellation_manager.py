"""PostgreSQL-based run cancellation manager for multi-worker deployments."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Dict, Optional, Set

from agno.exceptions import RunCancelledException
from agno.run.cancellation_management.base import BaseRunCancellationManager
from agno.utils.log import logger

_sqlalchemy_available = True
_sqlalchemy_import_error: Optional[str] = None

try:
    from sqlalchemy import text
    from sqlalchemy.engine import Engine
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
    from sqlalchemy.orm import Session, sessionmaker
except ImportError:
    _sqlalchemy_available = False
    _sqlalchemy_import_error = "`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`"
    if TYPE_CHECKING:
        from sqlalchemy import text
        from sqlalchemy.engine import Engine
        from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
        from sqlalchemy.orm import Session, sessionmaker
    else:
        text = object
        Engine = object
        AsyncEngine = object
        AsyncSession = object
        async_sessionmaker = object
        Session = object
        sessionmaker = object

# TTL in seconds for caching a False (not-cancelled) result.
# True (cancelled) results are cached indefinitely — the flag never reverts.
_CACHE_TTL_SECONDS = 2.0

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL_TABLE = """
CREATE TABLE IF NOT EXISTS t_run_cancel (
    run_id     VARCHAR(64)  PRIMARY KEY,
    cancelled  SMALLINT     NOT NULL DEFAULT 0,
    parent_id  VARCHAR(64)  NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
)
"""
_DDL_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_t_run_cancel_parent_id ON t_run_cancel (parent_id) WHERE parent_id IS NOT NULL"
)

# ---------------------------------------------------------------------------
# SQL statements
# ---------------------------------------------------------------------------

_SQL_REGISTER = "INSERT INTO t_run_cancel (run_id, cancelled) VALUES (:run_id, 0) ON CONFLICT (run_id) DO NOTHING"
# xmax = 0  → fresh INSERT  (run was not previously registered)
# xmax != 0 → DO UPDATE fired (run already existed, i.e. was registered)
_SQL_CANCEL = (
    "INSERT INTO t_run_cancel (run_id, cancelled) "
    "VALUES (:run_id, 1) "
    "ON CONFLICT (run_id) DO UPDATE SET cancelled = 1 "
    "RETURNING (xmax = 0) AS is_inserted"
)
_SQL_IS_CANCELLED = "SELECT cancelled FROM t_run_cancel WHERE run_id = :run_id"
_SQL_DELETE = "DELETE FROM t_run_cancel WHERE run_id = :run_id"
_SQL_ALL_RUNS = "SELECT run_id, cancelled FROM t_run_cancel"
_SQL_REGISTER_MEMBER = (
    "INSERT INTO t_run_cancel (run_id, cancelled, parent_id) "
    "VALUES (:run_id, 0, :parent_id) "
    "ON CONFLICT (run_id) DO UPDATE SET parent_id = EXCLUDED.parent_id"
)
_SQL_GET_MEMBERS = "SELECT run_id FROM t_run_cancel WHERE parent_id = :parent_id"


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------


class _CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: bool, ttl: float) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl if not value else float("inf")

    def is_valid(self) -> bool:
        return time.monotonic() < self.expires_at


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class PostgresRunCancellationManager(BaseRunCancellationManager):
    """PostgreSQL-based cancellation manager for distributed, multi-worker deployments.

    Stores run cancellation state in a single ``t_run_cancel`` table so that any
    worker process can read and write cancellation flags without in-process state.

    An in-process cache reduces database round-trips for hot ``is_cancelled``
    check-points:

    * ``cancelled=True``  — cached indefinitely (the flag never reverts).
    * ``cancelled=False`` — cached for ``_CACHE_TTL_SECONDS`` seconds.

    Team cancel-cascade is supported via the ``parent_id`` column, which stores
    the team run's ``run_id`` on each member row.  No second table is needed::

        run_id (PK) | cancelled | parent_id   | created_at
        team-run-1  |     0     |    NULL     | ...   <- standalone / team run
        member-run-1|     0     |  team-run-1 | ...   <- member run

    Args:
        async_engine: Async SQLAlchemy engine used by all async methods.
        sync_engine:  Sync SQLAlchemy engine used by all sync methods.
                      Optional if only async methods are used.
    """

    def __init__(
        self,
        async_engine: AsyncEngine,
        sync_engine: Optional[Engine] = None,
    ) -> None:
        if not _sqlalchemy_available:
            raise ImportError(_sqlalchemy_import_error)
        super().__init__()
        self._async_engine = async_engine
        self._sync_engine = sync_engine
        self._async_session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
        self._sync_session_factory: Optional[sessionmaker] = (
            sessionmaker(sync_engine, class_=Session, expire_on_commit=False)  # type: ignore[call-overload]
            if sync_engine is not None
            else None
        )
        # Async in-process cache protected by an asyncio.Lock.
        self._cache: Dict[str, _CacheEntry] = {}
        self._cache_lock = asyncio.Lock()
        # Sync in-process cache protected by a threading.Lock.
        self._sync_cache: Dict[str, _CacheEntry] = {}
        self._sync_cache_lock = threading.Lock()

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _ensure_sync_session_factory(self) -> sessionmaker:
        if self._sync_session_factory is None:
            raise RuntimeError(
                "Sync engine not provided. Pass `sync_engine` to "
                "PostgresRunCancellationManager or use the async methods."
            )
        return self._sync_session_factory

    # -- async cache --

    async def _get_cache(self, run_id: str) -> Optional[bool]:
        async with self._cache_lock:
            entry = self._cache.get(run_id)
            if entry and entry.is_valid():
                return entry.value
            if entry:
                del self._cache[run_id]
            return None

    async def _set_cache(self, run_id: str, value: bool) -> None:
        async with self._cache_lock:
            self._cache[run_id] = _CacheEntry(value, _CACHE_TTL_SECONDS)

    async def _evict_cache(self, run_id: str) -> None:
        async with self._cache_lock:
            self._cache.pop(run_id, None)

    # -- sync cache --

    def _get_sync_cache(self, run_id: str) -> Optional[bool]:
        with self._sync_cache_lock:
            entry = self._sync_cache.get(run_id)
            if entry and entry.is_valid():
                return entry.value
            if entry:
                del self._sync_cache[run_id]
            return None

    def _set_sync_cache(self, run_id: str, value: bool) -> None:
        with self._sync_cache_lock:
            self._sync_cache[run_id] = _CacheEntry(value, _CACHE_TTL_SECONDS)

    def _evict_sync_cache(self, run_id: str) -> None:
        with self._sync_cache_lock:
            self._sync_cache.pop(run_id, None)

    # ---------------------------------------------------------------------------
    # Table creation (call once at application startup)
    # ---------------------------------------------------------------------------

    def create_table(self) -> None:
        """Create ``t_run_cancel`` and its index if they do not yet exist."""
        if self._sync_engine is not None:
            with self._sync_engine.begin() as conn:
                conn.execute(text(_DDL_TABLE))
                conn.execute(text(_DDL_INDEX))
        else:
            with self._async_engine.sync_engine.begin() as conn:  # type: ignore[attr-defined]
                conn.execute(text(_DDL_TABLE))
                conn.execute(text(_DDL_INDEX))

    async def acreate_table(self) -> None:
        """Create ``t_run_cancel`` and its index if they do not yet exist (async)."""
        async with self._async_engine.begin() as conn:
            await conn.execute(text(_DDL_TABLE))
            await conn.execute(text(_DDL_INDEX))

    # ---------------------------------------------------------------------------
    # register_run
    # ---------------------------------------------------------------------------

    def register_run(self, run_id: str) -> None:
        """Register a new run as not cancelled.

        Uses INSERT … ON CONFLICT DO NOTHING to preserve any existing
        cancellation intent (cancel-before-start support).
        """
        sf = self._ensure_sync_session_factory()
        with sf() as session:
            session.execute(text(_SQL_REGISTER), {"run_id": run_id})
            session.commit()

    async def aregister_run(self, run_id: str) -> None:
        """Register a new run as not cancelled (async version).

        Uses INSERT … ON CONFLICT DO NOTHING to preserve any existing
        cancellation intent (cancel-before-start support).
        """
        async with self._async_session_factory() as session:
            await session.execute(text(_SQL_REGISTER), {"run_id": run_id})
            await session.commit()

    # ---------------------------------------------------------------------------
    # cancel_run
    # ---------------------------------------------------------------------------

    def _log_cancel(self, run_id: str, was_registered: bool) -> None:
        if was_registered:
            logger.info(f"Run {run_id} marked for cancellation")
        else:
            logger.info(f"Run {run_id} not yet registered, storing cancellation intent")

    def cancel_run(self, run_id: str) -> bool:
        """Cancel a run by marking it as cancelled.

        Always stores cancellation intent, even for runs not yet registered
        (cancel-before-start support).

        Returns:
            bool: True if run was previously registered, False if storing
            cancellation intent for an unregistered run.
        """
        sf = self._ensure_sync_session_factory()
        with sf() as session:
            result = session.execute(text(_SQL_CANCEL), {"run_id": run_id})
            row = result.fetchone()
            session.commit()
        was_registered = not bool(row[0]) if row else False
        self._set_sync_cache(run_id, True)
        self._log_cancel(run_id, was_registered)
        return was_registered

    async def acancel_run(self, run_id: str) -> bool:
        """Cancel a run by marking it as cancelled (async version).

        Always stores cancellation intent, even for runs not yet registered
        (cancel-before-start support).

        Returns:
            bool: True if run was previously registered, False if storing
            cancellation intent for an unregistered run.
        """
        async with self._async_session_factory() as session:
            result = await session.execute(text(_SQL_CANCEL), {"run_id": run_id})
            row = result.fetchone()
            await session.commit()
        was_registered = not bool(row[0]) if row else False
        await self._set_cache(run_id, True)
        self._log_cancel(run_id, was_registered)
        return was_registered

    # ---------------------------------------------------------------------------
    # is_cancelled
    # ---------------------------------------------------------------------------

    def is_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled."""
        cached = self._get_sync_cache(run_id)
        if cached is not None:
            return cached
        sf = self._ensure_sync_session_factory()
        with sf() as session:
            result = session.execute(text(_SQL_IS_CANCELLED), {"run_id": run_id})
            row = result.fetchone()
        value = bool(row[0]) if row else False
        self._set_sync_cache(run_id, value)
        return value

    async def ais_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled (async version)."""
        cached = await self._get_cache(run_id)
        if cached is not None:
            return cached
        async with self._async_session_factory() as session:
            result = await session.execute(text(_SQL_IS_CANCELLED), {"run_id": run_id})
            row = result.fetchone()
        value = bool(row[0]) if row else False
        await self._set_cache(run_id, value)
        return value

    # ---------------------------------------------------------------------------
    # cleanup_run
    # ---------------------------------------------------------------------------

    def cleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes)."""
        self._evict_sync_cache(run_id)
        sf = self._ensure_sync_session_factory()
        with sf() as session:
            session.execute(text(_SQL_DELETE), {"run_id": run_id})
            session.commit()

    async def acleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes) (async version)."""
        await self._evict_cache(run_id)
        async with self._async_session_factory() as session:
            await session.execute(text(_SQL_DELETE), {"run_id": run_id})
            await session.commit()

    # ---------------------------------------------------------------------------
    # raise_if_cancelled
    # ---------------------------------------------------------------------------

    def raise_if_cancelled(self, run_id: str) -> None:
        """Check if a run should be cancelled and raise exception if so."""
        if self.is_cancelled(run_id):
            logger.info(f"Cancelling run {run_id}")
            raise RunCancelledException(f"Run {run_id} was cancelled")

    async def araise_if_cancelled(self, run_id: str) -> None:
        """Check if a run should be cancelled and raise exception if so (async version)."""
        if await self.ais_cancelled(run_id):
            logger.info(f"Cancelling run {run_id}")
            raise RunCancelledException(f"Run {run_id} was cancelled")

    # ---------------------------------------------------------------------------
    # get_active_runs
    # ---------------------------------------------------------------------------

    def get_active_runs(self) -> Dict[str, bool]:
        """Get all currently tracked runs and their cancellation status."""
        sf = self._ensure_sync_session_factory()
        with sf() as session:
            result = session.execute(text(_SQL_ALL_RUNS))
            return {row[0]: bool(row[1]) for row in result.fetchall()}

    async def aget_active_runs(self) -> Dict[str, bool]:
        """Get all currently tracked runs and their cancellation status (async version)."""
        async with self._async_session_factory() as session:
            result = await session.execute(text(_SQL_ALL_RUNS))
            return {row[0]: bool(row[1]) for row in result.fetchall()}

    # ---------------------------------------------------------------------------
    # Member-run tracking (team cancel-cascade)
    #
    # The parent_id column on each member row encodes the team → member mapping.
    # No separate table is needed.  When a member run finishes, its row is deleted
    # by acleanup_run (called from the agent's finally block), which removes both
    # the cancellation state and the parent reference in one DELETE.
    # ---------------------------------------------------------------------------

    def register_member_run(self, team_run_id: str, member_run_id: str) -> None:
        """Record that a member run belongs to a team run for cancel-cascade."""
        sf = self._ensure_sync_session_factory()
        with sf() as session:
            session.execute(
                text(_SQL_REGISTER_MEMBER),
                {"run_id": member_run_id, "parent_id": team_run_id},
            )
            session.commit()

    async def aregister_member_run(self, team_run_id: str, member_run_id: str) -> None:
        """Record that a member run belongs to a team run for cancel-cascade (async version)."""
        async with self._async_session_factory() as session:
            await session.execute(
                text(_SQL_REGISTER_MEMBER),
                {"run_id": member_run_id, "parent_id": team_run_id},
            )
            await session.commit()

    def get_member_run_ids(self, team_run_id: str) -> Set[str]:
        """Return the in-flight member run_ids of a team run."""
        sf = self._ensure_sync_session_factory()
        with sf() as session:
            result = session.execute(text(_SQL_GET_MEMBERS), {"parent_id": team_run_id})
            return {row[0] for row in result.fetchall()}

    async def aget_member_run_ids(self, team_run_id: str) -> Set[str]:
        """Return the in-flight member run_ids of a team run (async version)."""
        async with self._async_session_factory() as session:
            result = await session.execute(text(_SQL_GET_MEMBERS), {"parent_id": team_run_id})
            return {row[0] for row in result.fetchall()}

    def cleanup_member_runs(self, team_run_id: str) -> None:
        """Drop a team run's member mapping when the team run finishes.

        Member rows are deleted individually by each agent's ``cleanup_run``
        call (in the agent's finally block), so no additional work is needed here.
        """
        pass

    async def acleanup_member_runs(self, team_run_id: str) -> None:
        """Drop a team run's member mapping when the team run finishes (async version).

        Member rows are deleted individually by each agent's ``acleanup_run``
        call (in the agent's finally block), so no additional work is needed here.
        """
        pass
