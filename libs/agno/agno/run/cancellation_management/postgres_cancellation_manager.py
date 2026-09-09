"""PostgreSQL cancellation intent shared by independently running workers."""

from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

from sqlalchemy import text

from agno.db.postgres import PostgresDb
from agno.exceptions import RunCancelledException
from agno.run.cancellation_management.base import BaseRunCancellationManager
from agno.utils.bounded import BoundedWorkers, WorkBudget
from agno.utils.log import log_warning

_WORKERS = BoundedWorkers(8, "postgres-cancellation")


@dataclass
class _LocalRun:
    cancelled: bool
    expires_at: float


class PostgresRunCancellationManager(BaseRunCancellationManager):
    """Opt-in cancellation using an existing synchronous ``PostgresDb``.

    Call ``setup()`` or ``asetup()`` before installing this manager with
    ``set_cancellation_manager`` in each worker. Use the same namespace on every
    replica. This also covers foreground runs, which have no queue ticket.

    Checkpoints use a local cache and refresh locally registered runs in batches
    at most once per ``poll_interval`` (default 0.5 seconds). Remote cancellation
    is observed at the first checkpoint after that interval and a database read;
    this does not interrupt an uncooperative blocking tool or provider request.
    There is no background task to shut down. PostgreSQL remains authoritative.

    Set ``ttl_seconds`` longer than the longest possible run or queue wait.
    Expired intent is ignored and bounded sweeps run during writes. Registration
    and cancellation failures raise; read/cleanup failures log and retain known
    cancellation without failing an otherwise healthy run. Quotas and ownership
    checks belong at the API boundary, before calling ``cancel_run``.

    The supplied database owns its engine. This manager never disposes it.
    """

    def __init__(self, db: PostgresDb, *, namespace: str, poll_interval: float = 0.5, ttl_seconds: float = 86400):
        if not isinstance(db, PostgresDb):
            raise ValueError("PostgresRunCancellationManager requires PostgresDb")
        if not isinstance(namespace, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", namespace):
            raise ValueError("A stable cancellation namespace is required")
        if any(isinstance(v, bool) or not math.isfinite(v) or v <= 0 for v in (poll_interval, ttl_seconds)):
            raise ValueError("Cancellation intervals must be finite and positive")
        self.engine, self.namespace = db.db_engine, namespace
        self.poll_interval, self.ttl_seconds = poll_interval, ttl_seconds
        self._lock = threading.Lock()
        self._local: Dict[str, _LocalRun] = {}
        self._next_poll = 0.0
        self._ready = False

    @staticmethod
    def _timeout(conn: Any, budget: WorkBudget) -> None:
        conn.execute(
            text("SELECT set_config('statement_timeout', :ms, true), set_config('lock_timeout', :ms, true)"),
            {"ms": str(max(1, int(min(2.5, budget.remaining()) * 1000)))},
        )

    def _setup(self, *, budget: WorkBudget) -> None:
        with self.engine.begin() as conn:
            self._timeout(conn, budget)
            conn.execute(text("SELECT pg_advisory_xact_lock(7148274142894)"))
            conn.execute(
                text("""CREATE TABLE IF NOT EXISTS public.agno_run_cancellations (
                namespace text NOT NULL, run_id text NOT NULL, cancelled boolean NOT NULL,
                expires_at timestamptz NOT NULL, PRIMARY KEY(namespace, run_id))""")
            )
            conn.execute(
                text("""CREATE INDEX IF NOT EXISTS agno_run_cancellations_expiry
                ON public.agno_run_cancellations(expires_at)""")
            )
            conn.execute(
                text("""CREATE TABLE IF NOT EXISTS public.agno_run_cancellation_members (
                namespace text NOT NULL, team_run_id text NOT NULL, member_run_id text NOT NULL,
                expires_at timestamptz NOT NULL, PRIMARY KEY(namespace, team_run_id, member_run_id))""")
            )
            conn.execute(
                text("""CREATE INDEX IF NOT EXISTS agno_run_cancellation_members_expiry
                ON public.agno_run_cancellation_members(expires_at)""")
            )
        self._ready = True

    def setup(self) -> None:
        """Create the shared tables under a transaction-scoped setup lock."""
        _WORKERS.run_sync(self._setup, seconds=3)

    async def asetup(self) -> None:
        """Create the shared tables without blocking the event loop."""
        await _WORKERS.run(self._setup, seconds=3)

    def _args(self, run_id: Optional[str] = None) -> dict:
        if not self._ready:
            raise ValueError("Call setup() or asetup() before using PostgreSQL cancellation")
        if run_id is not None and (not isinstance(run_id, str) or not run_id or len(run_id.encode()) > 256):
            raise ValueError("run_id must contain 1 to 256 UTF-8 bytes")
        return {"namespace": self.namespace, "run_id": run_id, "ttl": self.ttl_seconds}

    @staticmethod
    def _sweep(conn: Any) -> None:
        # Fixed identifiers; each sweep has bounded lock and row work.
        for table in ("agno_run_cancellations", "agno_run_cancellation_members"):
            conn.execute(
                text(f"""WITH stale AS (SELECT ctid FROM public.{table}
                WHERE expires_at <= now() ORDER BY expires_at LIMIT 100 FOR UPDATE SKIP LOCKED)
                DELETE FROM public.{table} WHERE ctid IN (SELECT ctid FROM stale)""")
            )

    def _write(self, run_id: str, cancelled: bool, *, budget: WorkBudget) -> bool:
        args = self._args(run_id)
        with self.engine.begin() as conn:
            self._timeout(conn, budget)
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": self.namespace + ":" + run_id}
            )
            existed = (
                conn.execute(
                    text("""SELECT cancelled FROM public.agno_run_cancellations
                WHERE namespace=:namespace AND run_id=:run_id AND expires_at>now()"""),
                    args,
                ).first()
                is not None
            )
            row = conn.execute(
                text("""INSERT INTO public.agno_run_cancellations AS r
                (namespace, run_id, cancelled, expires_at)
                VALUES (:namespace, :run_id, :cancelled, now()+:ttl*interval '1 second')
                ON CONFLICT(namespace, run_id) DO UPDATE SET
                cancelled=CASE WHEN r.expires_at>now() THEN r.cancelled OR EXCLUDED.cancelled ELSE EXCLUDED.cancelled END,
                expires_at=CASE WHEN r.expires_at>now() AND NOT :cancelled THEN r.expires_at ELSE EXCLUDED.expires_at END
                RETURNING cancelled, extract(epoch FROM expires_at-now())"""),
                {**args, "cancelled": cancelled},
            ).one()
            self._sweep(conn)
        with self._lock:
            now = time.monotonic()
            self._local = {key: state for key, state in self._local.items() if state.expires_at > now}
            if not cancelled or run_id in self._local:
                self._local[run_id] = _LocalRun(bool(row[0]), time.monotonic() + float(row[1]))
        return existed

    def register_run(self, run_id: str) -> None:
        _WORKERS.run_sync(self._write, run_id, False, seconds=3)

    async def aregister_run(self, run_id: str) -> None:
        await _WORKERS.run(self._write, run_id, False, seconds=3)

    def cancel_run(self, run_id: str) -> bool:
        return _WORKERS.run_sync(self._write, run_id, True, seconds=3)

    async def acancel_run(self, run_id: str) -> bool:
        return await _WORKERS.run(self._write, run_id, True, seconds=3)

    def _cached(self, run_id: str) -> Optional[bool]:
        self._args(run_id)
        with self._lock:
            state = self._local.get(run_id)
            if state is not None and state.expires_at > time.monotonic():
                if state.cancelled or self._next_poll > time.monotonic():
                    return state.cancelled
        return None

    def _poll(self, run_id: str, *, budget: WorkBudget) -> bool:
        args = self._args(run_id)
        with self._lock:
            now = time.monotonic()
            self._local = {key: value for key, value in self._local.items() if value.expires_at > now}
            if run_id in self._local and now < self._next_poll:
                return self._local[run_id].cancelled
            self._next_poll = now + self.poll_interval
            snapshot = dict(self._local)
        ids = list(set(snapshot) | {run_id})
        states = {}
        try:
            with self.engine.begin() as conn:
                self._timeout(conn, budget)
                for offset in range(0, len(ids), 500):
                    rows = conn.execute(
                        text("""SELECT run_id, cancelled FROM public.agno_run_cancellations
                        WHERE namespace=:namespace AND run_id=ANY(:ids) AND expires_at>now()"""),
                        {**args, "ids": ids[offset : offset + 500]},
                    )
                    states.update({row[0]: row[1] for row in rows})
            with self._lock:
                for key, state in snapshot.items():
                    if self._local.get(key) is state:
                        state.cancelled = state.cancelled or states.get(key, False)
                return states.get(run_id, False) or bool(self._local.get(run_id) and self._local[run_id].cancelled)
        except Exception:
            return self._read_unavailable(run_id)

    def _read_unavailable(self, run_id: str) -> bool:
        log_warning("PostgreSQL cancellation read unavailable")
        with self._lock:
            return bool(self._local.get(run_id) and self._local[run_id].cancelled)

    def is_cancelled(self, run_id: str) -> bool:
        cached = self._cached(run_id)
        if cached is not None:
            return cached
        try:
            return _WORKERS.run_sync(self._poll, run_id, seconds=3)
        except Exception:
            return self._read_unavailable(run_id)

    async def ais_cancelled(self, run_id: str) -> bool:
        cached = self._cached(run_id)
        if cached is not None:
            return cached
        try:
            return await _WORKERS.run(self._poll, run_id, seconds=3)
        except Exception:
            return self._read_unavailable(run_id)

    def raise_if_cancelled(self, run_id: str) -> None:
        if self.is_cancelled(run_id):
            raise RunCancelledException(f"Run {run_id} was cancelled")

    async def araise_if_cancelled(self, run_id: str) -> None:
        if await self.ais_cancelled(run_id):
            raise RunCancelledException(f"Run {run_id} was cancelled")

    def _cleanup(self, run_id: str, *, members: bool = False, budget: WorkBudget) -> None:
        args = self._args(run_id)
        if not members:
            with self._lock:
                self._local.pop(run_id, None)
        try:
            with self.engine.begin() as conn:
                self._timeout(conn, budget)
                query = (
                    "DELETE FROM public.agno_run_cancellation_members WHERE namespace=:namespace AND team_run_id=:run_id"
                    if members
                    else "DELETE FROM public.agno_run_cancellations WHERE namespace=:namespace AND run_id=:run_id"
                )
                conn.execute(text(query), args)
        except Exception:
            log_warning("PostgreSQL cancellation cleanup unavailable; entries will expire")

    def _forget(self, run_id: str) -> None:
        self._args(run_id)
        with self._lock:
            self._local.pop(run_id, None)

    def cleanup_run(self, run_id: str) -> None:
        self._forget(run_id)
        try:
            _WORKERS.run_sync(self._cleanup, run_id, seconds=3)
        except Exception:
            log_warning("PostgreSQL cancellation cleanup unavailable; entries will expire")

    async def acleanup_run(self, run_id: str) -> None:
        self._forget(run_id)
        try:
            await _WORKERS.run(self._cleanup, run_id, seconds=3)
        except Exception:
            log_warning("PostgreSQL cancellation cleanup unavailable; entries will expire")

    def _active(self, *, budget: WorkBudget) -> Dict[str, bool]:
        with self.engine.begin() as conn:
            self._timeout(conn, budget)
            return dict(
                conn.execute(
                    text("""SELECT run_id, cancelled FROM public.agno_run_cancellations
                WHERE namespace=:namespace AND expires_at>now()"""),
                    self._args(),
                )
                .tuples()
                .all()
            )

    def get_active_runs(self) -> Dict[str, bool]:
        return _WORKERS.run_sync(self._active, seconds=3)

    async def aget_active_runs(self) -> Dict[str, bool]:
        return await _WORKERS.run(self._active, seconds=3)

    def _member(self, team_run_id: str, member_run_id: Optional[str] = None, *, budget: WorkBudget) -> Set[str]:
        args = self._args(team_run_id)
        with self.engine.begin() as conn:
            self._timeout(conn, budget)
            if member_run_id is not None:
                self._args(member_run_id)
                conn.execute(
                    text("""INSERT INTO public.agno_run_cancellation_members
                    (namespace, team_run_id, member_run_id, expires_at)
                    VALUES (:namespace, :run_id, :member, now()+:ttl*interval '1 second')
                    ON CONFLICT(namespace, team_run_id, member_run_id) DO UPDATE SET expires_at=EXCLUDED.expires_at"""),
                    {**args, "member": member_run_id},
                )
                self._sweep(conn)
                return set()
            return set(
                conn.execute(
                    text("""SELECT member_run_id FROM public.agno_run_cancellation_members
                WHERE namespace=:namespace AND team_run_id=:run_id AND expires_at>now()"""),
                    args,
                ).scalars()
            )

    def register_member_run(self, team_run_id: str, member_run_id: str) -> None:
        _WORKERS.run_sync(self._member, team_run_id, member_run_id, seconds=3)

    async def aregister_member_run(self, team_run_id: str, member_run_id: str) -> None:
        await _WORKERS.run(self._member, team_run_id, member_run_id, seconds=3)

    def get_member_run_ids(self, team_run_id: str) -> Set[str]:
        return _WORKERS.run_sync(self._member, team_run_id, seconds=3)

    async def aget_member_run_ids(self, team_run_id: str) -> Set[str]:
        return await _WORKERS.run(self._member, team_run_id, seconds=3)

    def cleanup_member_runs(self, team_run_id: str) -> None:
        self._args(team_run_id)
        try:
            _WORKERS.run_sync(self._cleanup, team_run_id, members=True, seconds=3)
        except Exception:
            log_warning("PostgreSQL member cancellation cleanup unavailable; entries will expire")

    async def acleanup_member_runs(self, team_run_id: str) -> None:
        self._args(team_run_id)
        try:
            await _WORKERS.run(self._cleanup, team_run_id, members=True, seconds=3)
        except Exception:
            log_warning("PostgreSQL member cancellation cleanup unavailable; entries will expire")
