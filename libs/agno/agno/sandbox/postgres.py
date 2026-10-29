"""Postgres ownership and atomic publication of sandbox recovery boundaries.

The coordinator owns this store. No database credentials belong inside compute.
A staged execution result or uploaded object alone never completes a service run.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypeVar, Union
from uuid import uuid4

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.exceptions import SchemaMismatchError, SessionBusyError
from agno.sandbox.base import SandboxError, SandboxHandle, _sync
from agno.sandbox.checkpoint import CheckpointRef
from agno.sandbox.protocol import NATIVE_SESSION_KEYS
from agno.utils.log import log_warning
from agno.utils.string import sanitize_postgres_strings

try:
    from sqlalchemy import Float, Table, func, select, text, update
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.engine import Connection
    from sqlalchemy.exc import IntegrityError
except ImportError:
    raise ImportError("Sandbox coordination requires sqlalchemy and a PostgreSQL driver")

_T = TypeVar("_T")

# Service run statuses no sandbox turn may reopen or overwrite. REGENERATED marks a
# completed run superseded by /continue?regenerate=true.
_FINISHED = ("COMPLETED", "CANCELLED", "ERROR", "REGENERATED")

# Fields the runtime produces; service-owned identity, input and lineage stay as stored.
_RUNTIME_RUN_FIELDS = frozenset(
    (
        "content",
        "content_type",
        "reasoning_content",
        "reasoning_steps",
        "reasoning_messages",
        "model",
        "model_provider",
        "model_provider_data",
        "messages",
        "metrics",
        "compaction",
        "tools",
        "images",
        "videos",
        "audio",
        "files",
        "response_audio",
        "citations",
        "references",
        "followups",
        "events",
        "status",
        "cancellation_stage",
        "last_checkpoint_at_message_index",
    )
)


def _retained(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The checkpoints a binding keeps, oldest first; a binding from before retention keeps its current one."""
    kept = record.get("retained_checkpoints")
    if kept is None:
        kept = [record["checkpoint"]] if record.get("checkpoint") else []
    return list(kept)


def _retire(record: Dict[str, Any], *references: Optional[Dict[str, Any]]) -> None:
    """Queue checkpoints for deletion from the store, never one the binding still keeps."""
    kept = [*_retained(record), record.get("checkpoint")]
    retired = list(record.get("retired_checkpoints") or [])
    for reference in references:
        if reference and reference not in kept and reference not in retired:
            retired.append(reference)
    record["retired_checkpoints"] = retired


async def _drain(task: "asyncio.Future[Any]") -> None:
    """Wait for a shielded task through any further cancellation, so it cannot finish after the caller left."""
    while not task.done():
        try:
            await asyncio.wait([task])
        except asyncio.CancelledError:
            continue
    if not task.cancelled():
        task.exception()  # Retrieved: the caller is raising CancelledError instead.


async def _settled(awaitable: Awaitable[_T], undo: Optional[Callable[[_T], Awaitable[None]]] = None) -> _T:
    """Await work that keeps running when cancelled, such as a worker thread, before cancellation propagates.

    The work may still complete after the cancellation request, and its result is then
    lost to the caller. ``undo`` reverses that completed result before the cancellation
    propagates, so a cancelled caller never leaves behind state it does not know about.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await _drain(task)
        if undo is not None and not task.cancelled() and task.exception() is None:
            reversal = asyncio.ensure_future(undo(task.result()))
            await _drain(reversal)
            if not reversal.cancelled() and reversal.exception() is not None:
                log_warning(f"Could not undo a cancelled sandbox store operation: {reversal.exception()}")
        raise


class SandboxLeaseLost(SandboxError):
    """The caller no longer owns this session or queue attempt."""


class SandboxSessionBusy(SessionBusyError, SandboxError):
    def __init__(self, run_id: str) -> None:
        super().__init__("A sandbox session already has an active run; wait or reconcile that run", run_id=run_id)


class SandboxRunFinished(SandboxError):
    def __init__(self, run: Dict[str, Any]) -> None:
        self.run = run
        super().__init__("This service run is already terminal; return its persisted result")


@dataclass(frozen=True)
class SandboxLease:
    agent_id: str
    session_id: str
    user_id: Optional[str]
    run_id: str
    epoch: int
    owner: str = field(repr=False)
    queue_attempt: Optional[int] = None
    # Unique per binding row, so a lease for a deleted session never matches its recreation
    incarnation: Optional[str] = field(default=None, repr=False)


@dataclass(frozen=True)
class SandboxState:
    lease: SandboxLease
    expires_at: datetime
    record: Dict[str, Any] = field(repr=False)


class _SandboxStore:
    """Session leases and finalization on the same database as service run history.

    Tables live in the agent's PostgresDb (``sandbox_table`` names the lease
    table) and are created on first use. Async methods support both Postgres
    adapters; synchronous methods require PostgresDb. Compute cleanup is
    acknowledged only after the coordinator confirms it through the provider.
    This store cannot independently prove a remote machine has stopped.
    """

    sessions: Table
    runs: Table
    bindings: Table

    def __init__(self, db: Union[PostgresDb, AsyncPostgresDb]) -> None:
        if not isinstance(db, (PostgresDb, AsyncPostgresDb)):
            raise TypeError("Sandbox coordination requires PostgresDb or AsyncPostgresDb")
        self.db = db
        self.namespace = db.db_schema + "." + db.session_table_name
        self._tables_ready = False

    def _sync(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if isinstance(self.db, AsyncPostgresDb):
            raise TypeError("Use async sandbox store methods with AsyncPostgresDb")
        return _sync(function(*args, **kwargs))

    async def _table(self, table_type: str, table_name: str, create: bool = True) -> Optional[Table]:
        """The table, created on first use; None when ``create`` is off and it does not exist."""
        db = self.db

        async def lookup(create_if_missing: bool) -> Optional[Table]:
            if isinstance(db, AsyncPostgresDb):
                return await db._get_table(table_type, create_table_if_not_found=create_if_missing)
            return await _settled(
                asyncio.to_thread(db._get_table, table_type, create_table_if_not_found=create_if_missing)
            )

        try:
            try:
                table = await lookup(create)
            except Exception as exc:
                # Another process may have won the first CREATE TABLE (reported as a duplicate table,
                # a duplicate catalog row, or the table's row type already existing); read back what it created.
                cause = getattr(exc, "orig", exc)
                if getattr(cause, "sqlstate", getattr(cause, "pgcode", None)) not in ("42P07", "23505", "42710"):
                    raise
                db._invalidate_table_cache(table_name)
                table = await lookup(False)
        except SchemaMismatchError as exc:
            if table_type != "sandbox_bindings":
                raise
            # A bindings table missing columns, ours or another replica's, is as unusable as one
            # with the wrong keys: same remedy.
            raise SandboxError(
                f"Sandbox table {self.db.db_schema}.{table_name} does not have the columns this version expects; "
                "drop or rename that table, or pass PostgresDb(sandbox_table=...) to create a new one"
            ) from exc
        if table is None and create:
            raise SandboxError(f"Sandbox coordination could not create the {table_type} table")
        return table

    async def _ensure_tables(self, create: bool = True) -> None:
        """Create the tables on first use and validate the bindings table's shape.

        With ``create`` off, a deployment that provisions its own tables is only validated:
        a table that does not exist yet is left for first use, which creates it as before.
        """
        if self._tables_ready:
            return
        # Creation is idempotent, so concurrent first calls need no lock.
        sessions = await self._table("sessions", self.db.session_table_name, create)
        runs = await self._table("runs", self.db.runs_table_name, create)
        bindings = await self._table("sandbox_bindings", self.db.sandbox_table_name, create)
        if sessions is None or runs is None or bindings is None:
            return
        self.sessions, self.runs, self.bindings = sessions, runs, bindings

        def qualified(table: Table) -> str:
            # Reflection can leave a same-schema reference unqualified.
            return (table.schema or self.db.db_schema) + "." + table.name

        def refuse(reason: str) -> None:
            # A table from another build of this package or a different session table: say what to do.
            raise SandboxError(
                f"Sandbox table {qualified(self.bindings)} {reason}; drop or rename that table, "
                "or pass PostgresDb(sandbox_table=...) to create a new one"
            )

        owners = {qualified(key.column.table) for key in self.bindings.c.session_id.foreign_keys}
        if owners != {qualified(self.sessions)}:
            refuse(
                f"belongs to session table {', '.join(sorted(owners)) or 'none'}, not {qualified(self.sessions)}; "
                "give each session table its own sandbox_table"
            )
        if {qualified(key.column.table) for key in self.bindings.c.run_id.foreign_keys} != {qualified(self.runs)}:
            refuse(f"does not reference run table {qualified(self.runs)}")
        # Without cascade, deleting the run an active turn holds is refused instead of dropping its binding.
        if {(key.ondelete or "NO ACTION").upper() for key in self.bindings.c.run_id.foreign_keys} - {
            "NO ACTION",
            "RESTRICT",
        }:
            refuse("must not cascade deletes from the run table")
        # Deleting a session must remove its binding with it: an idle binding outlives every turn, and a
        # recreated session must start from a fresh one.
        if {(key.ondelete or "").upper() for key in self.bindings.c.session_id.foreign_keys} != {"CASCADE"}:
            refuse("must cascade deletes from the session table")
        # The claim's ON CONFLICT relies on this key; without it two first claims could both own a session.
        if {column.name for column in self.bindings.primary_key.columns} != {"namespace", "session_id"}:
            refuse("must have the primary key (namespace, session_id)")
        self._tables_ready = True

    async def _transaction(
        self, operation: Callable[[Connection], _T], undo: Optional[Callable[[_T], Awaitable[None]]] = None
    ) -> _T:
        """Run ``operation`` in one transaction; ``undo`` reverses a commit the cancelled caller never saw."""
        await self._ensure_tables()
        db = self.db
        if isinstance(db, AsyncPostgresDb):

            async def transact_async() -> _T:
                async with db.db_engine.begin() as connection:
                    return await connection.run_sync(operation)

            # A cancellation that lands while the commit is in flight would hide whether it happened.
            return await _settled(transact_async(), undo)

        def transact() -> _T:
            with db.db_engine.begin() as connection:
                return operation(connection)

        # Cancelling to_thread leaves the thread running; wait so a cancelled call never commits later.
        return await _settled(asyncio.to_thread(transact), undo)

    @staticmethod
    def _json(value: Any) -> Any:
        value = sanitize_postgres_strings(json.loads(json.dumps(value, allow_nan=False)))
        if len(json.dumps(value).encode()) > 16 * 1024 * 1024:
            raise ValueError("Sandbox coordination metadata exceeds 16 MiB")
        return value

    def _key(self, session_id: str) -> Any:
        return (self.bindings.c.namespace == self.namespace) & (self.bindings.c.session_id == session_id)

    def _service_run(self, connection: Connection, lease: SandboxLease, *, lock: bool = True) -> Any:
        query = select(self.runs).where(self.runs.c.run_id == lease.run_id)
        row = connection.execute(query.with_for_update() if lock else query).mappings().one_or_none()
        if (
            row is None
            or row["session_id"] != lease.session_id
            or row["agent_id"] != lease.agent_id
            or row["user_id"] != lease.user_id
        ):
            raise SandboxLeaseLost("Service run ownership does not match the sandbox lease")
        if row["run_data"].get("queue_attempt") != lease.queue_attempt:
            raise SandboxLeaseLost("A different queue attempt owns this service run")
        # Keep the core adapter's run -> session lock order.
        query = select(self.sessions).where(self.sessions.c.session_id == lease.session_id)
        # KEY SHARE keeps the session from being deleted or re-keyed without waiting on ordinary
        # session writes; a commit's own session update takes its row lock when it writes.
        if lock:
            query = query.with_for_update(read=True, key_share=True)
        session = connection.execute(query).mappings().one_or_none()
        if session is None or session["agent_id"] != lease.agent_id or session["user_id"] != lease.user_id:
            raise SandboxLeaseLost("Service session ownership does not match the sandbox lease")
        return row, session

    def _hold_session(self, connection: Connection, session_id: str) -> None:
        # Taken before the binding. A concurrent session delete then waits for this transaction instead of
        # cascading into rows it holds, a deadlock; KEY SHARE does not block ordinary session writes.
        connection.execute(
            select(self.sessions.c.session_id)
            .where(self.sessions.c.session_id == session_id)
            # read=True is what makes this FOR KEY SHARE; key_share alone renders FOR NO KEY UPDATE.
            .with_for_update(read=True, key_share=True)
        )

    def _lock_run(self, connection: Connection, run_id: str) -> None:
        # Session, then run, then binding: a run delete locks the run and then checks the bindings
        # referencing it, so locking the binding first could deadlock with it.
        connection.execute(select(self.runs.c.run_id).where(self.runs.c.run_id == run_id).with_for_update())

    def _locked(self, connection: Connection, lease: SandboxLease) -> Any:
        self._hold_session(connection, lease.session_id)
        self._lock_run(connection, lease.run_id)
        row = (
            connection.execute(select(self.bindings).where(self._key(lease.session_id)).with_for_update())
            .mappings()
            .one_or_none()
        )
        now: datetime = connection.execute(select(func.clock_timestamp())).scalar_one()
        if (
            row is None
            or (row["agent_id"], row["user_id"], row["run_id"], row["epoch"], row["owner"], row["queue_attempt"])
            != (lease.agent_id, lease.user_id, lease.run_id, lease.epoch, lease.owner, lease.queue_attempt)
            or row["record"].get("incarnation") != lease.incarnation
            or row["expires_at"] is None
            or row["expires_at"] <= now
        ):
            raise SandboxLeaseLost("Sandbox session lease expired or was fenced by another owner")
        self._service_run(connection, lease)
        return row

    def _state(self, row: Any) -> SandboxState:
        return SandboxState(
            SandboxLease(
                row["agent_id"],
                row["session_id"],
                row["user_id"],
                row["run_id"],
                row["epoch"],
                row["owner"],
                row["queue_attempt"],
                row["record"].get("incarnation"),
            ),
            row["expires_at"],
            self._json(row["record"]),
        )

    def _write_record(
        self, connection: Connection, lease: SandboxLease, record: Dict[str, Any], *, extend: bool = False
    ) -> SandboxState:
        values: Dict[str, Any] = {"record": self._json(record)}
        if extend:
            # Only for a writer that held the binding row lock throughout, so nobody else could own it.
            now: datetime = connection.execute(select(func.clock_timestamp())).scalar_one()
            values["expires_at"] = now + timedelta(seconds=record.get("lease_seconds", 60))
        row = (
            connection.execute(
                update(self.bindings).where(self._key(lease.session_id)).values(**values).returning(self.bindings)
            )
            .mappings()
            .one()
        )
        return self._state(row)

    async def aclaim(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: Optional[str],
        run_id: str,
        owner: str,
        queue_attempt: Optional[int] = None,
        lease_seconds: float = 60,
        prepared_run: Optional[Dict[str, Any]] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ) -> SandboxState:
        """Own the session for ``run_id``; always continue with the returned state's lease.

        Re-claiming after the lease expired bumps the epoch, which fences every
        earlier lease object, the caller's own included. An unfinished run keeps
        the session even after its lease expires: other run ids get
        SandboxSessionBusy until someone re-claims that run id and stops or
        finishes it, so a coordinator needs a reaper for abandoned runs.
        """
        for value in (agent_id, session_id, run_id, owner, *(() if user_id is None else (user_id,))):
            if not isinstance(value, str) or not value or "\x00" in value or len(value) > 512:
                raise ValueError("Sandbox lease identities must be nonempty bounded strings")
        if queue_attempt is not None and (type(queue_attempt) is not int or queue_attempt < 1):
            raise ValueError("Queue attempt must be a positive integer")
        if not math.isfinite(lease_seconds) or not 0 < lease_seconds <= 3600:
            raise ValueError("Lease duration must be between 0 and 3600 seconds")

        prepared: Optional[Dict[str, Any]] = None
        if prepared_run is not None:
            prepared = self._json(prepared_run)
            if (
                prepared.get("agent_id"),
                prepared.get("session_id"),
                prepared.get("user_id"),
                prepared.get("run_id"),
                prepared.get("queue_attempt"),
            ) != (agent_id, session_id, user_id, run_id, queue_attempt):
                raise ValueError("Prepared run does not match the requested lease")
        opened_turn = False
        reused_lease = False

        def claim(connection: Connection) -> SandboxState:
            nonlocal opened_turn, reused_lease
            if prepared is not None:
                # A new session needs its row before it can be held; inserting it locks no existing row.
                self._insert_session(connection, prepared, session_metadata)
            self._hold_session(connection, session_id)
            if prepared is not None:
                # Session, then run, then binding: the prepared run is written and locked before the binding.
                self._prepare_service_run(connection, prepared)
            self._lock_run(connection, run_id)
            try:
                connection.execute(
                    insert(self.bindings)
                    .values(
                        namespace=self.namespace,
                        session_id=session_id,
                        agent_id=agent_id,
                        user_id=user_id,
                        epoch=0,
                        record={
                            "phase": "idle",
                            # Random so a recreated session never reuses a deleted one's container
                            # names; 52 bits so JSON readers keep it exact.
                            "generation": uuid4().int >> 76,
                            "checkpoint": None,
                            "incarnation": uuid4().hex,
                        },
                    )
                    .on_conflict_do_nothing()
                )
            except IntegrityError as error:
                # The binding's foreign key: the service session does not exist.
                raise SandboxLeaseLost("Service session ownership does not match the sandbox lease") from error
            row = (
                connection.execute(select(self.bindings).where(self._key(session_id)).with_for_update())
                .mappings()
                .one()
            )
            if row["agent_id"] != agent_id or row["user_id"] != user_id:
                raise SandboxLeaseLost("Sandbox session ownership is immutable")
            candidate = SandboxLease(agent_id, session_id, user_id, run_id, row["epoch"], owner, queue_attempt)
            run, _ = self._service_run(connection, candidate)
            if row["epoch"] == 0:
                # A first binding on a session with finished runs has no checkpoint to continue from.
                historical = connection.execute(
                    select(self.runs.c.run_id)
                    .where(
                        (self.runs.c.session_id == session_id)
                        & (self.runs.c.run_id != run_id)
                        & self.runs.c.status.in_(_FINISHED)
                        & func.coalesce(
                            self.runs.c.run_data["metadata"]["sandbox"]["never_executed"].as_boolean(), False
                        ).is_(False)
                    )
                    .limit(1)
                ).first()
                if historical is not None:
                    raise SandboxError(
                        "Existing conversation has no sandbox checkpoint; start a new session or migrate explicitly"
                    )
            record = dict(row["record"])
            now: datetime = connection.execute(select(func.clock_timestamp())).scalar_one()
            active = record["phase"] != "idle"
            # A retryable failure this binding recorded for an earlier queue attempt of this run: the
            # queue's next attempt runs the turn again instead of reading back the stored error.
            failed = record.get("retryable_failure") or {}
            reopen = (
                not active
                and str(run["status"]).upper() == "ERROR"
                and (run["run_data"].get("metadata") or {}).get("retryable") is True
                and failed.get("run_id") == run_id
                and queue_attempt is not None
                and failed.get("queue_attempt") is not None
                and queue_attempt > failed["queue_attempt"]
            )
            if reopen:
                reopened = {**run["run_data"], "status": "RUNNING", "content": None}
                reopened["metadata"] = {
                    key: value for key, value in (reopened.get("metadata") or {}).items() if key != "retryable"
                }
                connection.execute(
                    update(self.runs)
                    .where(self.runs.c.run_id == run_id)
                    .values(status="RUNNING", run_data=self._json(reopened), updated_at=int(time.time()))
                )
            elif not active and str(run["status"]).upper() in _FINISHED:
                raise SandboxRunFinished(dict(run["run_data"]))
            if not active and str(run["status"]).upper() == "PAUSED":
                # A paused run waits for its continuation; executing it again would discard that state.
                raise SandboxError("A paused run must be continued, not started again in a sandbox")
            if not active:
                # Starting a turn on an idle session, first or later: another run that is running or
                # paused outside the sandbox would execute alongside it. Queued (PENDING) runs wait for
                # the binding instead.
                running = connection.execute(
                    select(self.runs.c.run_id)
                    .where(
                        (self.runs.c.session_id == session_id)
                        & (self.runs.c.run_id != run_id)
                        & self.runs.c.status.in_(["RUNNING", "PAUSED"])
                    )
                    .limit(1)
                ).first()
                if running is not None:
                    raise SandboxSessionBusy(running[0])
            if active and row["run_id"] != run_id:
                raise SandboxSessionBusy(row["run_id"])
            newer_attempt = (
                queue_attempt is not None and row["queue_attempt"] is not None and queue_attempt > row["queue_attempt"]
            )
            same_owner = row["owner"] == owner and row["queue_attempt"] == queue_attempt
            lease_alive = row["expires_at"] is not None and row["expires_at"] > now
            if active and lease_alive and not same_owner and not newer_attempt:
                raise SandboxSessionBusy(row["run_id"])
            # The same owner re-claiming a live lease gets that lease back rather than a new one.
            reused_lease = active and same_owner and lease_alive
            epoch = row["epoch"] if reused_lease else row["epoch"] + 1
            opened_turn = not active
            if not active:
                _retire(record, record.get("staged_checkpoint"))
                # A computer kept warm by the last commit stays with its generation; the coordinator
                # decides whether it is still usable. Otherwise the turn gets a fresh generation.
                warm = (
                    record.get("warm_until") is not None
                    and record.get("computer") is not None
                    and not record.get("computer_stopped")
                )
                record.update(
                    phase="executing",
                    generation=record["generation"] if warm else record["generation"] + 1,
                    computer=record["computer"] if warm else None,
                    computer_stopped=False,
                    stopped_ref=None,
                    stop_status=None,
                    stop_reason=None,
                    stop_retryable=False,
                    execution_id=uuid4().hex,
                    result=None,
                    staged_checkpoint=None,
                    staged_identity=None,
                    request_hash=None,
                    run_metadata=None,
                    retryable_failure=None,
                )
            if active and str(run["status"]).upper() in _FINISHED:
                # Finished elsewhere while this turn was active: retire its compute and release the session.
                record.update(
                    phase="stopping",
                    stop_status="CANCELLED" if str(run["status"]).upper() == "CANCELLED" else "ERROR",
                    stop_reason="Service run was finished elsewhere",
                )
                if record.get("computer") is None:
                    record["computer_stopped"] = True
            record["lease_seconds"] = lease_seconds
            updated = (
                connection.execute(
                    update(self.bindings)
                    .where(self._key(session_id))
                    .values(
                        epoch=epoch,
                        owner=owner,
                        run_id=run_id,
                        queue_attempt=queue_attempt,
                        expires_at=now + timedelta(seconds=lease_seconds),
                        record=record,
                    )
                    .returning(self.bindings)
                )
                .mappings()
                .one()
            )
            return self._state(updated)

        async def abandon(state: SandboxState) -> None:
            # The caller was cancelled after the claim committed, so nobody holds the lease it
            # returned. Release it now instead of leaving the session busy until it expires. A
            # turn this claim opened goes back to idle, since nothing ran; a re-claimed turn keeps
            # its run, so the abandoned-run rule still applies to it.
            def release(connection: Connection) -> None:
                if reused_lease:
                    # The original caller still holds this lease and is still running its turn.
                    return
                try:
                    row = self._locked(connection, state.lease)
                except SandboxLeaseLost:
                    return
                record = dict(row["record"])
                if opened_turn:
                    record.update(phase="idle", result=None, staged_checkpoint=None)
                connection.execute(
                    update(self.bindings)
                    .where(self._key(session_id))
                    .values(
                        owner=None,
                        run_id=None if opened_turn else row["run_id"],
                        queue_attempt=None,
                        expires_at=None,
                        record=record,
                    )
                )

            await self._transaction(release)

        return await self._transaction(claim, undo=abandon)

    def claim(self, **kwargs: Any) -> SandboxState:
        return self._sync(self.aclaim, **kwargs)

    async def aget(self, lease: SandboxLease) -> SandboxState:
        return await self._transaction(lambda connection: self._state(self._locked(connection, lease)))

    def get(self, lease: SandboxLease) -> SandboxState:
        return self._sync(self.aget, lease)

    async def arenew(self, lease: SandboxLease, *, lease_seconds: float = 60) -> SandboxState:
        if not math.isfinite(lease_seconds) or not 0 < lease_seconds <= 3600:
            raise ValueError("Lease duration must be between 0 and 3600 seconds")

        def renew(connection: Connection) -> SandboxState:
            record = dict(self._locked(connection, lease)["record"])
            record["lease_seconds"] = lease_seconds
            now: datetime = connection.execute(select(func.clock_timestamp())).scalar_one()
            row = (
                connection.execute(
                    update(self.bindings)
                    .where(self._key(lease.session_id))
                    .values(expires_at=now + timedelta(seconds=lease_seconds), record=self._json(record))
                    .returning(self.bindings)
                )
                .mappings()
                .one()
            )
            return self._state(row)

        return await self._transaction(renew)

    def renew(self, lease: SandboxLease, *, lease_seconds: float = 60) -> SandboxState:
        return self._sync(self.arenew, lease, lease_seconds=lease_seconds)

    async def aset_computer(self, lease: SandboxLease, computer: SandboxHandle) -> SandboxState:
        def bind(connection: Connection) -> SandboxState:
            record = dict(self._locked(connection, lease)["record"])
            if record["phase"] != "executing" or (computer.agent_id, computer.session_id, computer.generation) != (
                lease.agent_id,
                lease.session_id,
                record["generation"],
            ):
                raise SandboxError("Computer does not match the active session generation")
            serialized = asdict(computer)
            if record.get("computer") is not None and record["computer"] != serialized:
                raise SandboxError("A different computer is already bound to this generation")
            record["computer"] = serialized
            return self._write_record(connection, lease, record)

        return await self._transaction(bind)

    def set_computer(self, lease: SandboxLease, computer: SandboxHandle) -> SandboxState:
        return self._sync(self.aset_computer, lease, computer)

    async def astage_result(self, lease: SandboxLease, result: Dict[str, Any]) -> SandboxState:
        result = self._json(result)
        run, session = result.get("run", {}), result.get("session", {})
        if (
            run.get("run_id"),
            run.get("session_id"),
            run.get("agent_id"),
            run.get("user_id"),
            session.get("session_id"),
            session.get("user_id"),
        ) != (lease.run_id, lease.session_id, lease.agent_id, lease.user_id, lease.session_id, lease.user_id):
            raise SandboxError("Execution result identity does not match its lease")
        if run.get("status") not in ("COMPLETED", "ERROR", "CANCELLED"):
            raise SandboxError("Runtime result must describe a terminal execution")

        def stage(connection: Connection) -> SandboxState:
            record = dict(self._locked(connection, lease)["record"])
            if record.get("result") is not None:
                if record["result"] != result:
                    raise SandboxError("An execution result is immutable once staged")
                return self._state(self._locked(connection, lease))
            if record["phase"] != "executing" or record.get("computer") is None:
                raise SandboxError("Execution must have a bound computer before staging its result")
            record.update(phase="finalizing", result=result)
            return self._write_record(connection, lease, record)

        return await self._transaction(stage)

    def stage_result(self, lease: SandboxLease, result: Dict[str, Any]) -> SandboxState:
        return self._sync(self.astage_result, lease, result)

    async def astage_checkpoint(self, lease: SandboxLease, checkpoint: CheckpointRef) -> SandboxState:
        def stage(connection: Connection) -> SandboxState:
            row = self._locked(connection, lease)
            record = dict(row["record"])
            if record["phase"] != "finalizing" or record.get("result") is None:
                raise SandboxError("Checkpoint staging requires a retained execution result")
            value = asdict(checkpoint)
            if record.get("staged_checkpoint") is not None and record["staged_checkpoint"] != value:
                raise SandboxError("A staged checkpoint is immutable; reconcile its acknowledgement")
            record["staged_checkpoint"] = value
            return self._write_record(connection, lease, record)

        return await self._transaction(stage)

    def stage_checkpoint(self, lease: SandboxLease, checkpoint: CheckpointRef) -> SandboxState:
        return self._sync(self.astage_checkpoint, lease, checkpoint)

    async def aconfirm_stopped(self, lease: SandboxLease, provider_ref: str) -> SandboxState:
        """Record provider-confirmed shutdown, never a caller's assumption after a timeout."""

        def stopped(connection: Connection) -> SandboxState:
            row = self._locked(connection, lease)
            record = dict(row["record"])
            computer = record.get("computer")
            if computer is None or computer["provider_ref"] != provider_ref:
                if record.get("stopped_ref") == provider_ref:
                    return self._state(row)
                raise SandboxError("Shutdown acknowledgement does not match the bound computer")
            if record["phase"] not in ("finalizing", "stopping"):
                raise SandboxError("Persist a shutdown intent before retiring compute")
            if record["phase"] == "finalizing" and record.get("staged_checkpoint") is None:
                raise SandboxError("Persist a recovery checkpoint before retiring finalized execution")
            record.update(computer=None, computer_stopped=True, stopped_ref=provider_ref)
            return self._write_record(connection, lease, record)

        return await self._transaction(stopped)

    def confirm_stopped(self, lease: SandboxLease, provider_ref: str) -> SandboxState:
        return self._sync(self.aconfirm_stopped, lease, provider_ref)

    async def acommit(
        self,
        lease: SandboxLease,
        *,
        keep_computer_until: Optional[float] = None,
        retain_checkpoints: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Publish the staged result and checkpoint with the run, atomically.

        Raises SandboxRunFinished if another writer finished the run first. Cleanup is
        already confirmed by then, so the session is released before raising: the stored
        outcome stands and the previous checkpoint stays the recovery point.

        ``keep_computer_until`` keeps the turn's computer bound to the session, paused or
        idle, so the next turn may resume it instead of restoring the checkpoint. The
        checkpoint is still the recovery point; the computer is only a shortcut to it.

        ``retain_checkpoints`` bounds how many committed checkpoints the session keeps;
        older ones are queued in ``retired_checkpoints`` for the coordinator to delete.
        """

        def commit(connection: Connection) -> Tuple[bool, Dict[str, Any]]:
            row = self._locked(connection, lease)
            record = dict(row["record"])
            cleaned_up = record.get("computer_stopped") or (
                keep_computer_until is not None and record.get("computer") is not None
            )
            if record["phase"] != "finalizing" or not record.get("staged_checkpoint") or not cleaned_up:
                raise SandboxError("Durable completion requires staged recovery bytes and confirmed compute cleanup")
            previous_run, session = self._service_run(connection, lease)
            if str(previous_run["status"]).upper() in _FINISHED:
                _retire(record, record.get("staged_checkpoint"))
                record.update(phase="idle", result=None, staged_checkpoint=None, warm_until=None)
                connection.execute(
                    update(self.bindings)
                    .where(self._key(lease.session_id))
                    .values(owner=None, run_id=None, queue_attempt=None, expires_at=None, record=record)
                )
                return False, dict(previous_run["run_data"])
            result = record["result"]
            run = dict(previous_run["run_data"])
            run.update({key: value for key, value in result["run"].items() if key in _RUNTIME_RUN_FIELDS})
            run["queue_attempt"] = lease.queue_attempt
            native_metadata = result["run"].get("metadata") or {}
            run["metadata"] = {
                **(previous_run["run_data"].get("metadata") or {}),
                **(record.get("run_metadata") or {}),
                **{
                    key: native_metadata[key]
                    for key in ("warnings", "attempts", "retryable", "error_type")
                    if key in native_metadata
                },
                "sandbox": {
                    "native_metadata": native_metadata,
                    "epoch": lease.epoch,
                    "generation": record["generation"],
                    # Whether the turn ran on the computer kept warm by the previous turn.
                    "resumed": bool(record.get("resumed")),
                    "checkpoint": record["staged_checkpoint"],
                    "execution_id": record["execution_id"],
                    **({"repository": result["repository"]} if result.get("repository") is not None else {}),
                },
            }
            self._retire_native_hitl(run)
            session_data = dict(session["session_data"] or {})
            session_data["sandbox"] = {
                "native": result["session"].get("session_data") or {},
                "checkpoint": record["staged_checkpoint"],
                "run_id": lease.run_id,
                "epoch": lease.epoch,
            }
            connection.execute(
                update(self.runs)
                .where(self.runs.c.run_id == lease.run_id)
                .values(status=run["status"], run_data=self._json(run), updated_at=int(time.time()))
            )
            connection.execute(
                update(self.sessions)
                .where(self.sessions.c.session_id == lease.session_id)
                .values(session_data=self._json(session_data), updated_at=int(time.time()))
            )
            native = result["session"].get("session_data") or {}
            kept = [*_retained(record), record["staged_checkpoint"]]
            dropped = kept[:-retain_checkpoints] if retain_checkpoints is not None else []
            record.update(
                phase="idle",
                checkpoint=record["staged_checkpoint"],
                retained_checkpoints=kept[len(dropped) :],
                # Native conversation ids the checkpoint holds; the next turn requires exactly these.
                native={key: native[key] for key in NATIVE_SESSION_KEYS.values() if native.get(key)},
                checkpoint_identity=record.get("staged_identity"),
                last_run_id=lease.run_id,
                result=None,
                staged_checkpoint=None,
                warm_until=keep_computer_until,
            )
            _retire(record, *dropped)
            connection.execute(
                update(self.bindings)
                .where(self._key(lease.session_id))
                .values(owner=None, run_id=None, queue_attempt=None, expires_at=None, record=record)
            )
            return True, run

        # Raised outside the transaction, so the release above commits.
        published, run = await self._transaction(commit)
        if not published:
            raise SandboxRunFinished(run)
        return run

    def commit(
        self,
        lease: SandboxLease,
        *,
        keep_computer_until: Optional[float] = None,
        retain_checkpoints: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self._sync(
            self.acommit, lease, keep_computer_until=keep_computer_until, retain_checkpoints=retain_checkpoints
        )

    async def abegin_stop(
        self, lease: SandboxLease, *, status: str, reason: str, retryable: bool = False
    ) -> SandboxState:
        """Fence cancellation/failure before destroying compute; takeover only reconciles it."""
        if status not in ("ERROR", "CANCELLED") or not isinstance(reason, str) or len(reason) > 8192:
            raise ValueError("Shutdown requires a bounded error or cancellation reason")

        def begin(connection: Connection) -> SandboxState:
            row = self._locked(connection, lease)
            record = dict(row["record"])
            if record["phase"] == "stopping":
                return self._state(row)
            if record["phase"] not in ("executing", "finalizing"):
                raise SandboxError("Only an active execution can be stopped")
            record.update(phase="stopping", stop_status=status, stop_reason=reason, stop_retryable=retryable)
            if record.get("computer") is None:
                record["computer_stopped"] = True
            return self._write_record(connection, lease, record)

        return await self._transaction(begin)

    def begin_stop(self, lease: SandboxLease, *, status: str, reason: str, retryable: bool = False) -> SandboxState:
        return self._sync(self.abegin_stop, lease, status=status, reason=reason, retryable=retryable)

    async def afinish_stop(self, lease: SandboxLease) -> Dict[str, Any]:
        """Release the session after confirmed cleanup, keeping the previous recovery boundary.

        Records the stop on the run unless another writer already finished it.
        """

        def finish(connection: Connection) -> Dict[str, Any]:
            record = dict(self._locked(connection, lease)["record"])
            if record["phase"] != "stopping" or not record.get("computer_stopped"):
                raise SandboxError("Stop completion requires confirmed compute cleanup")
            previous_run, _ = self._service_run(connection, lease)
            run = dict(previous_run["run_data"])
            # A run another writer already finished keeps its stored outcome; the binding is still
            # released so the session is not left busy. The previous checkpoint stays the recovery point.
            if str(previous_run["status"]).upper() not in _FINISHED:
                staged = (record.get("result") or {}).get("run") or {}
                for key in ("tools", "messages", "metrics"):
                    if key in staged:
                        run[key] = staged[key]
                run["status"] = record["stop_status"]
                if run["status"] == "CANCELLED" and not run.get("cancellation_stage"):
                    from agno.run.base import CancellationStage

                    run["cancellation_stage"] = CancellationStage.executing.value
                # Like core run termination: the reason fills content only when there is none.
                if not run.get("content"):
                    run["content"] = record["stop_reason"]
                sandbox = {
                    "native_metadata": staged.get("metadata") or {},
                    "recovery_run_id": record.get("last_run_id"),
                    "workspace_rolled_back": True,
                    "epoch": lease.epoch,
                    "execution_id": record["execution_id"],
                    "stop_reason": record["stop_reason"],
                }
                if staged.get("content") is not None:
                    sandbox["runtime_content"] = staged["content"]
                run["metadata"] = {
                    **(run.get("metadata") or {}),
                    **(record.get("run_metadata") or {}),
                    "retryable": record.get("stop_retryable", False),
                    "sandbox": sandbox,
                }
                self._retire_native_hitl(run)
                connection.execute(
                    update(self.runs)
                    .where(self.runs.c.run_id == lease.run_id)
                    .values(status=run["status"], run_data=self._json(run), updated_at=int(time.time()))
                )
                if record.get("stop_retryable"):
                    # Lets the queue's next attempt of this run reopen it.
                    record["retryable_failure"] = {"run_id": lease.run_id, "queue_attempt": lease.queue_attempt}
            # A stopped turn never publishes its staged checkpoint.
            _retire(record, record.get("staged_checkpoint"))
            record.update(phase="idle", result=None, staged_checkpoint=None, warm_until=None)
            connection.execute(
                update(self.bindings)
                .where(self._key(lease.session_id))
                .values(owner=None, run_id=None, queue_attempt=None, expires_at=None, record=record)
            )
            return run

        return await self._transaction(finish)

    def finish_stop(self, lease: SandboxLease) -> Dict[str, Any]:
        return self._sync(self.afinish_stop, lease)

    def _prepare_service_run(self, connection: Connection, value: Dict[str, Any]) -> None:
        if value.get("status") not in ("PENDING", "RUNNING"):
            raise ValueError("A prepared sandbox run cannot be terminal")
        for key in ("run_id", "session_id", "agent_id"):
            if not isinstance(value.get(key), str) or not value[key] or len(value[key]) > 256:
                raise ValueError("Sandbox runs require bounded service identities")
        # The lock core run saves take, so a concurrent save cannot pick the same index. Taken before the
        # run row, in core's order: holding the row while waiting for it would deadlock a core save.
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('agno_run_index'), hashtext(:sid))"),
            {"sid": value["session_id"]},
        )
        self._insert_session(connection, value)
        connection.execute(
            insert(self.runs)
            .values(
                run_id=value["run_id"],
                session_id=value["session_id"],
                agent_id=value["agent_id"],
                user_id=value.get("user_id"),
                run_type="agent",
                status=value["status"],
                run_data=value,
                created_at=value.get("created_at", int(time.time())),
            )
            .on_conflict_do_nothing()
        )
        attempt = value.get("queue_attempt")
        if value["status"] == "PENDING":
            # A worker may already have claimed the accepted run; keep its attempt.
            existing: Dict[str, Any] = connection.execute(
                select(self.runs.c.run_data).where(self.runs.c.run_id == value["run_id"]).with_for_update()
            ).scalar_one()
            attempt = existing.get("queue_attempt")
        lease = SandboxLease(
            value["agent_id"],
            value["session_id"],
            value.get("user_id"),
            value["run_id"],
            0,
            "prepare",
            attempt,
        )
        row, _ = self._service_run(connection, lease)
        if row["run_data"].get("input") != value.get("input"):
            raise SandboxError("Run identity already exists with different input")
        if row["run_index"] is None:
            index: int = connection.execute(
                select(func.coalesce(func.max(self.runs.c.run_index), -1) + 1).where(
                    self.runs.c.session_id == value["session_id"]
                )
            ).scalar_one()
            connection.execute(update(self.runs).where(self.runs.c.run_id == value["run_id"]).values(run_index=index))

    def _insert_session(
        self, connection: Connection, value: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Create the session row if it is missing; an existing row, and its metadata, is left as it is."""
        connection.execute(
            insert(self.sessions)
            .values(
                session_id=value["session_id"],
                agent_id=value["agent_id"],
                user_id=value.get("user_id"),
                session_type="agent",
                created_at=int(time.time()),
                session_data={},
                **({"metadata": self._json(metadata)} if metadata else {}),
            )
            .on_conflict_do_nothing()
        )

    @staticmethod
    def _retire_native_hitl(run: Dict[str, Any]) -> None:
        """A finished or stopped turn leaves no native permission request pending."""
        from agno.agents._hitl import KEY

        native = (run.get("metadata") or {}).get(KEY)
        if native is None:
            return
        run["metadata"][KEY] = {**native, "pending": []}
        run["requirements"] = []

    async def _anative_hitl_event(self, lease: SandboxLease, event: Dict[str, Any]) -> None:
        """Record a native permission request, or its answer, on the run under execution fencing.

        The paused run is what the chat confirms and what a continuation decides; the decision lands on
        the same row, which the coordinator reads to deliver it to the runtime.
        """
        from agno.agents._hitl import KEY

        def publish(connection: Connection) -> None:
            binding = self._locked(connection, lease)
            service, _ = self._service_run(connection, lease)
            if str(service["status"]).upper() in _FINISHED:
                raise SandboxLeaseLost("Native execution already finished")
            run = dict(service["run_data"])
            metadata = dict(run.get("metadata") or {})
            state = dict(metadata.get(KEY) or {})
            requests = dict(state.get("requests") or {})
            pending = list(state.get("pending") or [])
            decisions = dict(state.get("decisions") or {})
            requirements = {
                r["tool_execution"]["tool_call_id"]: r for r in run.get("requirements") or [] if r.get("tool_execution")
            }
            if event["event"] == "RunPaused":
                request = dict(event["external_agent_request"])
                tool_call_id = request["tool_call_id"]
                state["owner"] = request["owner"]
                # A reclaim replays the runtime's events: an already answered request does not pause again.
                if tool_call_id not in decisions:
                    requests[tool_call_id] = {
                        "digest": request["digest"],
                        "native": request["native"],
                        "expires_at": request["expires_at"],
                        "execution_id": binding["record"]["execution_id"],
                        "generation": binding["record"]["computer"]["generation"],
                    }
                    if tool_call_id not in pending:
                        pending.append(tool_call_id)
                    requirements[tool_call_id] = request["requirement"]
                    run["tools"] = event.get("tools") or [r["tool_execution"] for r in requirements.values()]
                    if event.get("content") is not None:
                        run["content"] = event["content"]
            else:
                tool_call_id = event.get("external_agent_request_id")
                pending = [value for value in pending if value != tool_call_id]
            run["requirements"] = [requirements[key] for key in pending if key in requirements]
            state.update(requests=requests, pending=pending, decisions=decisions)
            state["execution_id"] = binding["record"]["execution_id"]
            metadata[KEY] = state
            run.update(metadata=metadata, status="PAUSED" if pending else "RUNNING")
            connection.execute(
                self.runs.update()
                .where(self.runs.c.run_id == lease.run_id)
                .values(
                    status=run["status"],
                    run_data=self._json(run),
                    updated_at=int(time.time()),
                )
            )

        await self._transaction(publish)

    async def _apublish_events(self, run: Dict[str, Any], events: list[Dict[str, Any]]) -> None:
        """Attach transport indices without rewriting a committed recovery boundary."""

        def publish(connection: Connection) -> None:
            row = (
                connection.execute(select(self.runs).where(self.runs.c.run_id == run["run_id"]).with_for_update())
                .mappings()
                .first()
            )
            if row is None:
                raise SandboxLeaseLost("Run disappeared before event retention")
            previous = dict(row["run_data"])
            identity = (run.get("metadata") or {}).get("sandbox") or {}
            stored_identity = (previous.get("metadata") or {}).get("sandbox") or {}
            if (
                any(
                    previous.get(key) != run.get(key)
                    for key in ("run_id", "session_id", "agent_id", "user_id", "queue_attempt", "status")
                )
                or not identity.get("execution_id")
                or any(stored_identity.get(key) != identity.get(key) for key in ("execution_id", "epoch"))
            ):
                raise SandboxLeaseLost("Event writer no longer owns this run result")
            retained = {
                event["event_index"]: event
                for event in previous.get("events", [])
                if event.get("event_index") is not None
            }
            retained.update({event["event_index"]: event for event in events if event.get("event_index") is not None})
            if retained:
                previous["events"] = [retained[key] for key in sorted(retained)]
                connection.execute(
                    update(self.runs).where(self.runs.c.run_id == run["run_id"]).values(run_data=self._json(previous))
                )

        await self._transaction(publish)

    async def _aclaim_stop(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: Optional[str],
        run_id: str,
        queue_attempt: Optional[int],
        status: str,
        reason: str,
        cancellation_stage: Optional[str] = None,
    ) -> Any:
        """Fence execution before a queue terminal path retires its compute."""
        from agno.run.status_persist import RunPersistOutcome

        if status not in ("ERROR", "CANCELLED"):
            raise ValueError("Queue termination requires ERROR or CANCELLED")

        def stop(connection: Connection) -> Any:
            self._hold_session(connection, session_id)
            self._lock_run(connection, run_id)
            # Insert an idle binding to serialize even a never-started run with
            # its first coordinator. A plain SELECT cannot lock an absent row.
            try:
                with connection.begin_nested():
                    connection.execute(
                        insert(self.bindings)
                        .values(
                            namespace=self.namespace,
                            session_id=session_id,
                            agent_id=agent_id,
                            user_id=user_id,
                            epoch=0,
                            record={
                                "phase": "idle",
                                "generation": uuid4().int,
                                "checkpoint": None,
                                "incarnation": uuid4().hex,
                            },
                        )
                        .on_conflict_do_nothing()
                    )
            except IntegrityError:
                # The binding's foreign key: the session, and with it the run, was deleted.
                return RunPersistOutcome.MISSING
            binding = (
                connection.execute(select(self.bindings).where(self._key(session_id)).with_for_update())
                .mappings()
                .one()
            )
            # A session bound to another owner can never have executed this run.
            foreign = binding["agent_id"] != agent_id or binding["user_id"] != user_id
            row = (
                connection.execute(select(self.runs).where(self.runs.c.run_id == run_id).with_for_update())
                .mappings()
                .first()
            )
            if row is None or (row["session_id"], row["agent_id"], row["user_id"]) != (session_id, agent_id, user_id):
                return RunPersistOutcome.MISSING
            run = dict(row["run_data"])
            actual_attempt = run.get("queue_attempt")
            if actual_attempt != queue_attempt and not (actual_attempt is None and queue_attempt == 0):
                return RunPersistOutcome.STALE_ATTEMPT
            record = dict(binding["record"])
            active = not foreign and record["phase"] != "idle" and binding["run_id"] == run_id
            if not active:
                if str(row["status"]).upper() in ("COMPLETED", "CANCELLED"):
                    return RunPersistOutcome.TERMINAL_REFUSED
                run.update(status=status, content=run.get("content") or reason)
                run["metadata"] = {**(run.get("metadata") or {}), "retryable": False}
                if foreign or binding["epoch"] == 0:
                    run["metadata"]["sandbox"] = {"never_executed": True}
                if status == "CANCELLED" and cancellation_stage is not None:
                    run["cancellation_stage"] = cancellation_stage
                connection.execute(
                    update(self.runs)
                    .where(self.runs.c.run_id == run_id)
                    .values(status=status, run_data=self._json(run), updated_at=int(time.time()))
                )
                return RunPersistOutcome.UPDATED
            # Take over an interrupted stop without rewriting the status it already committed to.
            if record["phase"] != "stopping":
                record.update(phase="stopping", stop_status=status, stop_reason=reason, stop_retryable=False)
            if record.get("computer") is None:
                record["computer_stopped"] = True
            now: datetime = connection.execute(select(func.clock_timestamp())).scalar_one()
            updated = (
                connection.execute(
                    update(self.bindings)
                    .where(self._key(session_id))
                    .values(
                        epoch=binding["epoch"] + 1,
                        owner=uuid4().hex,
                        queue_attempt=actual_attempt,
                        expires_at=now + timedelta(seconds=600),
                        record=self._json(record),
                    )
                    .returning(self.bindings)
                )
                .mappings()
                .one()
            )
            return self._state(updated)

        return await self._transaction(stop)

    async def aprepare(self, run: Dict[str, Any]) -> None:
        """Insert an accepted queued run without rewriting existing session recovery metadata."""
        value = self._json(run)
        await self._transaction(lambda connection: self._prepare_service_run(connection, value))

    def prepare(self, run: Dict[str, Any]) -> None:
        self._sync(self.aprepare, run)

    async def _aoperation(
        self, lease: SandboxLease, operation: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
    ) -> SandboxState:
        # Hold the ownership rows through a bounded provider mutation. A concurrent
        # takeover waits until it drains, then checks ownership against the DB clock.
        # This closes the check-then-act gap between a lease read and provider calls.
        async def perform() -> SandboxState:
            await self._ensure_tables()
            if isinstance(self.db, AsyncPostgresDb):
                async with self.db.db_engine.begin() as connection:
                    row = await connection.run_sync(lambda c: self._locked(c, lease))
                    record = await operation(self._json(row["record"]))
                    # Extend the lease with the commit: the heartbeat could not renew it during the call.
                    return await connection.run_sync(lambda c: self._write_record(c, lease, record, extend=True))
            sync_connection = await asyncio.to_thread(self.db.db_engine.connect)
            sync_transaction = await asyncio.to_thread(sync_connection.begin)
            try:
                row = await asyncio.to_thread(self._locked, sync_connection, lease)
                record = await operation(self._json(row["record"]))
                state = await asyncio.to_thread(lambda: self._write_record(sync_connection, lease, record, extend=True))
                await asyncio.to_thread(sync_transaction.commit)
                return state
            except BaseException:
                await asyncio.to_thread(sync_transaction.rollback)
                raise
            finally:
                await asyncio.to_thread(sync_connection.close)

        task = asyncio.create_task(perform())
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Closing a transaction while its provider operation still runs would
            # let the next owner mutate that same computer concurrently.
            await _drain(task)
            raise

    async def arelease_warm(
        self, session_id: str, *, agent_id: str, user_id: Optional[str], before: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """Take the warm computer off an idle binding so the caller can destroy it.

        Returns the computer's handle fields, or None when the binding holds no warm
        computer, is not idle, or its window ends after ``before``. The next claim then
        opens a fresh generation; the checkpoint stays the recovery point.
        """

        def release(connection: Connection) -> Optional[Dict[str, Any]]:
            row = (
                connection.execute(select(self.bindings).where(self._key(session_id)).with_for_update())
                .mappings()
                .one_or_none()
            )
            if row is None or row["agent_id"] != agent_id or row["user_id"] != user_id:
                return None
            record = dict(row["record"])
            computer, until = record.get("computer"), record.get("warm_until")
            if record["phase"] != "idle" or computer is None or until is None:
                return None
            if before is not None and float(until) > before:
                return None
            record.update(computer=None, computer_stopped=True, warm_until=None)
            connection.execute(update(self.bindings).where(self._key(session_id)).values(record=self._json(record)))
            return dict(computer)

        return await self._transaction(release)

    def release_warm(
        self, session_id: str, *, agent_id: str, user_id: Optional[str], before: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        return self._sync(self.arelease_warm, session_id, agent_id=agent_id, user_id=user_id, before=before)

    async def aexpired_warm(self, before: float) -> list:
        """Sessions whose idle binding keeps a computer whose warm window ended before ``before``."""

        def expired(connection: Connection) -> list:
            rows = connection.execute(
                select(self.bindings.c.session_id, self.bindings.c.agent_id, self.bindings.c.user_id).where(
                    (self.bindings.c.namespace == self.namespace)
                    & (self.bindings.c.record["phase"].astext == "idle")
                    & (self.bindings.c.record["warm_until"].astext.cast(Float) < before)
                )
            ).all()
            return [tuple(row) for row in rows]

        return await self._transaction(expired)

    def leftovers(self, connection: Connection, session_ids: List[str], agent_ids: List[str]) -> List[Dict[str, Any]]:
        """The computer and checkpoints each of these sessions leaves behind once it is deleted.

        Runs inside the session delete, before the cascade removes the bindings. The session
        rows are locked first, the lock the delete takes anyway, so an in-flight turn's
        operation commits its computer before this reads it.
        """
        if not self._tables_ready or not session_ids or not agent_ids:
            return []
        connection.execute(
            select(self.sessions.c.session_id).where(self.sessions.c.session_id.in_(session_ids)).with_for_update()
        )
        rows = connection.execute(
            select(self.bindings.c.session_id, self.bindings.c.record).where(
                (self.bindings.c.namespace == self.namespace)
                & self.bindings.c.session_id.in_(session_ids)
                & self.bindings.c.agent_id.in_(agent_ids)
            )
        ).all()
        found: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            session_id, record = str(row[0]), dict(row[1] or {})
            references = [
                *_retained(record),
                record.get("checkpoint"),
                record.get("staged_checkpoint"),
                *(record.get("retired_checkpoints") or []),
            ]
            computer = record.get("computer") if not record.get("computer_stopped") else None
            found[session_id] = {"computer": computer, "checkpoints": [ref for ref in references if ref]}
        if found:
            # Runs keep the checkpoint they committed, including ones from before retention existed.
            committed = self.runs.c.run_data["metadata"]["sandbox"]["checkpoint"]
            for row in connection.execute(
                select(self.runs.c.session_id, committed).where(self.runs.c.session_id.in_(list(found)))
            ).all():
                if isinstance(row[1], dict):
                    found[str(row[0])]["checkpoints"].append(row[1])
        for leftover in found.values():
            unique: List[Dict[str, Any]] = []
            for reference in leftover["checkpoints"]:
                if reference not in unique:
                    unique.append(reference)
            leftover["checkpoints"] = unique
        return list(found.values())

    async def aretired_checkpoints(self, session_id: str) -> List[Dict[str, Any]]:
        """Checkpoints the session's binding has queued for deletion from the store."""

        def read(connection: Connection) -> List[Dict[str, Any]]:
            row = connection.execute(select(self.bindings.c.record).where(self._key(session_id))).first()
            return list((row[0] or {}).get("retired_checkpoints") or []) if row is not None else []

        await self._ensure_tables()
        return await self._transaction(read)

    async def aforget_checkpoints(self, session_id: str, references: List[Dict[str, Any]]) -> None:
        """Drop references whose objects were deleted from the binding's retired queue."""

        def forget(connection: Connection) -> None:
            row = (
                connection.execute(select(self.bindings).where(self._key(session_id)).with_for_update())
                .mappings()
                .one_or_none()
            )
            if row is None:
                return
            record = dict(row["record"])
            record["retired_checkpoints"] = [
                reference for reference in record.get("retired_checkpoints") or [] if reference not in references
            ]
            connection.execute(update(self.bindings).where(self._key(session_id)).values(record=self._json(record)))

        await self._transaction(forget)

    async def arelinquish(self, lease: SandboxLease) -> None:
        """Detach the coordinator after draining its control calls; preserve ongoing execution."""

        def release(connection: Connection) -> None:
            self._locked(connection, lease)
            connection.execute(
                update(self.bindings).where(self._key(lease.session_id)).values(expires_at=func.clock_timestamp())
            )

        await self._transaction(release)

    def relinquish(self, lease: SandboxLease) -> None:
        self._sync(self.arelinquish, lease)
