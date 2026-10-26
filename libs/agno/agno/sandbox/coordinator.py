"""Durable cold-replacement session execution. Service credentials stay on this side."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import threading
import time
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict
from queue import Queue
from typing import Any, AsyncGenerator, Dict, Iterator, List, Mapping, Optional, Sequence, Set, Union
from uuid import uuid4

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.media import File, Image
from agno.models.message import Message
from agno.run.agent import (
    RunCancelledEvent,
    RunCompletedEvent,
    RunErrorEvent,
    RunInput,
    RunOutput,
    run_output_event_from_dict,
)
from agno.run.base import RunStatus
from agno.sandbox.base import Sandbox, SandboxError, SandboxHandle, _retention, _sync
from agno.sandbox.checkpoint import CheckpointContentError, CheckpointObjectNotFound, CheckpointRef
from agno.sandbox.client import RuntimeExecution, SandboxRuntimeClient
from agno.sandbox.media import decode_media, encode_media
from agno.sandbox.postgres import SandboxLease, SandboxLeaseLost, SandboxRunFinished, _drain, _SandboxStore, _settled
from agno.sandbox.protocol import NATIVE_SESSION_KEYS
from agno.sandbox.transfer import CheckpointTransfer
from agno.utils.log import log_warning

_CHECKPOINT_MISSING = (
    "This session's sandbox checkpoint is missing from checkpoint storage, so its workspace and conversation "
    "cannot be restored; start a new session, and check that every replica uses the same checkpoints= store"
)


class SandboxCoordinator:
    """Restore, execute, checkpoint and atomically complete one logical session turn.

    Leases and recovery state live in ``db``, the same PostgresDb as the agent's
    sessions and runs. All replicas need the same provider namespace and durable
    checkpoint storage.

    Every turn ends with a checkpoint, which is the recovery point. The computer
    itself is kept for ``warm_computer_seconds`` afterwards, paused where the provider can
    pause and idle otherwise, and the next turn resumes it instead of creating a
    new one and restoring: no cold start, files and processes as the last turn
    left them. A computer that is gone, expired or differently configured is
    replaced by a fresh generation restored from the checkpoint, which is the only
    path with ``warm_computer_seconds=0``. Losing a caller detaches it; explicit
    cancellation and failures retire the computer. A warm computer whose session
    never gets another turn is retired by that session's next claim, so a
    deployment that pauses containers should also sweep provider computers idle
    past the window.
    """

    def __init__(
        self,
        db: Union[PostgresDb, AsyncPostgresDb],
        provider: Sandbox,
        transfer: CheckpointTransfer,
        *,
        lease_seconds: float = 600,
        poll_wait: float = 5,
        warm_computer_seconds: float = 300,
        retain_checkpoints: Optional[int] = 3,
    ) -> None:
        # poll_wait is how long one poll waits inside the container for new events; it also
        # bounds how long a cancellation can go unnoticed while a turn emits nothing.
        if not 30 <= lease_seconds <= 3600 or not 0 < poll_wait <= 30:
            raise ValueError("Use a 30-3600 second lease and a poll wait of up to 30 seconds")
        if not math.isfinite(warm_computer_seconds) or not 0 <= warm_computer_seconds <= 3600:
            raise ValueError("Keep computers warm for between 0 and 3600 seconds")
        self.store, self.provider, self.transfer = _SandboxStore(db), provider, transfer
        self.client = SandboxRuntimeClient(provider)
        self.lease_seconds, self.poll_wait, self.warm_computer_seconds = lease_seconds, poll_wait, warm_computer_seconds
        self.retain_checkpoints = _retention(retain_checkpoints)
        # Agents whose sessions this coordinator cleans up when they are deleted.
        self.agent_ids: Set[str] = set()

    async def arun(
        self,
        session_id: str,
        *,
        agent_id: str,
        run_id: str,
        input: str,
        sdk: str,
        user_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        env: Optional[Mapping[str, str]] = None,
        queue_attempt: Optional[int] = None,
        execution_timeout: float = 900,
        images: Optional[Sequence[Image]] = None,
        files: Optional[Sequence[File]] = None,
    ) -> RunOutput:
        result = None
        async for value in self.astream(
            session_id,
            agent_id=agent_id,
            run_id=run_id,
            input=input,
            sdk=sdk,
            user_id=user_id,
            agent_name=agent_name,
            config=config,
            **({"metadata": metadata} if metadata is not None else {}),
            env=env,
            queue_attempt=queue_attempt,
            execution_timeout=execution_timeout,
            images=images,
            files=files,
        ):
            if isinstance(value, RunOutput):
                result = value
        if result is not None:
            return result
        raise SandboxError("Coordinator ended without a committed result")

    def run(
        self,
        session_id: str,
        *,
        agent_id: str,
        run_id: str,
        input: str,
        sdk: str,
        user_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        env: Optional[Mapping[str, str]] = None,
        queue_attempt: Optional[int] = None,
        execution_timeout: float = 900,
        images: Optional[Sequence[Image]] = None,
        files: Optional[Sequence[File]] = None,
    ) -> RunOutput:
        return self.store._sync(
            self.arun,
            session_id,
            agent_id=agent_id,
            run_id=run_id,
            input=input,
            sdk=sdk,
            user_id=user_id,
            agent_name=agent_name,
            config=config,
            **({"metadata": metadata} if metadata is not None else {}),
            env=env,
            queue_attempt=queue_attempt,
            execution_timeout=execution_timeout,
            images=images,
            files=files,
        )

    async def _stop(self, lease: SandboxLease, *, status: str, reason: str, retryable: bool = False) -> Dict[str, Any]:
        state = await self.store.abegin_stop(lease, status=status, reason=reason, retryable=retryable)
        if state.record.get("computer") is not None:
            handle = SandboxHandle(**state.record["computer"])
            # The persisted stopping phase forbids every subsequent owner from
            # restarting execution on this immutable generation.
            await self.provider.adestroy(handle)
            if await self.provider.aget(handle.provider_ref) is not None:
                raise SandboxError("Provider has not confirmed compute removal")
            await self.store.aconfirm_stopped(lease, handle.provider_ref)
        return await self.store.afinish_stop(lease)

    async def _aterminate(
        self,
        session_id: str,
        *,
        agent_id: str,
        run_id: str,
        user_id: Optional[str],
        queue_attempt: Optional[int],
        status: str,
        reason: str,
        cancellation_stage: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> Any:
        """Fence a queue terminal path and retire the run's compute before its ticket settles."""
        from agno.run.status_persist import RunPersistOutcome

        state = await self.store._aclaim_stop(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            run_id=run_id,
            queue_attempt=queue_attempt,
            status=status,
            reason=reason,
            cancellation_stage=cancellation_stage,
        )
        if not hasattr(state, "lease"):
            return state
        allocation: Dict[str, Any] = dict(agent_id=agent_id, generation=state.record["generation"], env=env)

        async def find_orphan(record: Dict[str, Any]) -> Dict[str, Any]:
            if record.get("computer") is None and not record.get("stopped_ref"):
                orphan = await self.provider.afind(session_id, **allocation)
                if orphan is not None:
                    record.update(computer=asdict(orphan), computer_stopped=False)
            return record

        try:
            await self.store._aoperation(state.lease, find_orphan)
            committed = await self._stop(state.lease, status=status, reason=reason)
            # An earlier stop that committed a different status wins; callers reconcile from the row.
            if committed.get("status") != status:
                return RunPersistOutcome.TERMINAL_REFUSED
            return RunPersistOutcome.UPDATED
        finally:
            with suppress(SandboxLeaseLost):
                await self.store.arelinquish(state.lease)

    async def aretire_computer(self, session_id: str, *, agent_id: str, user_id: Optional[str] = None) -> bool:
        """Remove the computer a session keeps warm between turns, if it has one.

        The checkpoint stays the recovery point, so the next turn simply runs on a
        fresh generation restored from it. Returns whether a computer was removed.
        """
        computer = await self.store.arelease_warm(session_id, agent_id=agent_id, user_id=user_id)
        if computer is None:
            return False
        with suppress(SandboxError):
            await self.provider.adestroy(SandboxHandle(**computer))
        return True

    def retire_computer(self, session_id: str, *, agent_id: str, user_id: Optional[str] = None) -> bool:
        return self.store._sync(self.aretire_computer, session_id, agent_id=agent_id, user_id=user_id)

    async def asweep_warm(self) -> int:
        """Retire every warm computer whose window has ended; run this periodically on one replica.

        A session's next claim retires its own stale computer, but a session that never
        returns would otherwise keep a paused container forever. Returns how many were removed.
        """
        now = time.time()
        removed = 0
        for session_id, agent_id, user_id in await self.store.aexpired_warm(now):
            computer = await self.store.arelease_warm(session_id, agent_id=agent_id, user_id=user_id, before=now)
            if computer is None:
                continue
            with suppress(SandboxError):
                await self.provider.adestroy(SandboxHandle(**computer))
            removed += 1
        return removed

    def sweep_warm(self) -> int:
        return self.store._sync(self.asweep_warm)

    def collect_deleted_sessions(self, connection: Any, session_ids: List[str]) -> List[Dict[str, Any]]:
        """Read, inside a session delete, what its cascade would otherwise orphan."""
        return self.store.leftovers(connection, session_ids, sorted(self.agent_ids))

    async def arelease_deleted_sessions(self, leftovers: List[Dict[str, Any]]) -> None:
        """Remove deleted sessions' computers and checkpoint objects; best-effort after the delete commits."""
        for leftover in leftovers:
            if leftover["computer"] is not None:
                try:
                    await self.provider.adestroy(SandboxHandle(**leftover["computer"]))
                except Exception as error:
                    log_warning(f"Could not remove a deleted session's sandbox computer: {error}")
            for reference in leftover["checkpoints"]:
                try:
                    await self.transfer.store.adelete(CheckpointRef(**reference))
                except Exception as error:
                    log_warning(f"Could not delete a deleted session's checkpoint {reference.get('sha256')}: {error}")

    def release_deleted_sessions(self, leftovers: List[Dict[str, Any]]) -> None:
        _sync(self.arelease_deleted_sessions(leftovers))

    def stream(
        self,
        session_id: str,
        *,
        agent_id: str,
        run_id: str,
        input: str,
        sdk: str,
        user_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        env: Optional[Mapping[str, str]] = None,
        queue_attempt: Optional[int] = None,
        execution_timeout: float = 900,
        images: Optional[Sequence[Image]] = None,
        files: Optional[Sequence[File]] = None,
    ) -> Iterator[Any]:
        """Synchronous ``astream``: the turn runs on its own loop in a worker thread and events
        arrive as they are produced. Stopping early detaches this caller like any disconnect."""
        if isinstance(self.store.db, AsyncPostgresDb):
            raise TypeError("Use astream with AsyncPostgresDb")
        done = object()
        items: "Queue[Any]" = Queue()

        async def pump() -> None:
            try:
                async for value in self.astream(
                    session_id,
                    agent_id=agent_id,
                    run_id=run_id,
                    input=input,
                    sdk=sdk,
                    user_id=user_id,
                    agent_name=agent_name,
                    config=config,
                    **({"metadata": metadata} if metadata is not None else {}),
                    env=env,
                    queue_attempt=queue_attempt,
                    execution_timeout=execution_timeout,
                    images=images,
                    files=files,
                ):
                    items.put(value)
            except BaseException as error:
                items.put(error)
            finally:
                items.put(done)

        worker = threading.Thread(target=lambda: asyncio.run(pump()), name="sandbox-stream", daemon=True)
        worker.start()
        try:
            while True:
                item = items.get()
                if item is done:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            worker.join()

    async def astream(
        self,
        session_id: str,
        *,
        agent_id: str,
        run_id: str,
        input: str,
        sdk: str,
        user_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        env: Optional[Mapping[str, str]] = None,
        queue_attempt: Optional[int] = None,
        execution_timeout: float = 900,
        images: Optional[Sequence[Image]] = None,
        files: Optional[Sequence[File]] = None,
    ) -> AsyncGenerator[Any, None]:
        """Run one turn and yield its events as they arrive, then the committed ``RunOutput`` last.

        The same turn as ``arun``: the run output is yielded only once the result and recovery
        checkpoint are stored, so a consumer that sees it can rely on it. Cancelling the consumer
        detaches it; the turn keeps running and a later call with the same run id reattaches.
        """
        if not isinstance(input, str) or sdk not in ("claude", "codex", "fixture"):
            raise ValueError("Sandbox runtime requires text input and a supported SDK")
        # Validate before any allocation, including JSON serializability and limits.
        from agno.sandbox.protocol import validate_request as _validate

        request = dict(
            version=1,
            execution_id="validate",
            run_id=run_id,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            input=input,
            sdk=sdk,
            config=dict(config or {}),
            execution_timeout=execution_timeout,
        )
        if metadata is not None:
            request["metadata"] = metadata
        media = encode_media(images=images, files=files)
        if media:
            request["media"] = media
        # Validate what the client will actually send, not this fingerprint form: the start request
        # carries a 32-character execution id and the committed conversation id, which is unknown
        # before the claim, so the largest id allowed stands in for it. Fixture opt-in belongs to the
        # compute image/environment; production SDKs use the same pure request validation without
        # importing either SDK.
        probe = {**request, "execution_id": "0" * 32, "native_session_id": "0" * 256}
        _validate({**probe, "sdk": "claude" if sdk == "fixture" else sdk})
        request = json.loads(json.dumps(request, allow_nan=False))
        config = request["config"]
        metadata = request.get("metadata")
        # The client's own measurement of the start request.
        if len(json.dumps(probe, allow_nan=False).encode()) > 1024 * 1024:
            raise ValueError("Runtime request exceeds 1 MiB")
        run = RunOutput(
            run_id=run_id,
            agent_id=agent_id,
            agent_name=agent_name,
            session_id=session_id,
            user_id=user_id,
            input=RunInput(input_content=input, **decode_media(media)),
            # The user's turn stays in the history of a run that is cancelled or fails before the
            # runtime returns any messages; a completed turn's messages replace it.
            messages=[Message(role="user", content=input, created_at=int(time.time()))],
            status=RunStatus.running,
        )
        prepared = run.to_dict()
        prepared["queue_attempt"] = queue_attempt
        claim_task = asyncio.create_task(
            self.store.aclaim(
                agent_id=agent_id,
                session_id=session_id,
                user_id=user_id,
                run_id=run_id,
                owner=uuid4().hex,
                queue_attempt=queue_attempt,
                lease_seconds=self.lease_seconds,
                prepared_run=prepared,
            )
        )
        try:
            state = await asyncio.shield(claim_task)
        except asyncio.CancelledError:
            # Drain without forwarding further cancels: a cancelled claim can still commit its lease.
            await _drain(claim_task)
            if not claim_task.cancelled() and claim_task.exception() is None:
                await _settled(self.store.arelinquish(claim_task.result().lease))
            raise
        except SandboxRunFinished as finished:
            yield self._terminal(finished.run)
            yield RunOutput.from_dict(finished.run)
            return
        lease = state.lease
        heartbeat_error: list[BaseException] = []

        async def heartbeat() -> None:
            try:
                while True:
                    await asyncio.sleep(self.lease_seconds / 3)
                    await self.store.arenew(lease, lease_seconds=self.lease_seconds)
            except asyncio.CancelledError:
                raise
            except BaseException as error:
                heartbeat_error.append(error)

        heart = asyncio.create_task(heartbeat())
        # Set once the turn's outcome is stored, which also releases the session.
        committed: Optional[Dict[str, Any]] = None
        try:
            # Image and resource limits belong to the provider; afind refuses a generation created with others.
            def allocation_for(record: Dict[str, Any]) -> Dict[str, Any]:
                return dict(agent_id=agent_id, generation=record["generation"], env=env)

            fingerprint = hashlib.sha256(
                json.dumps({"request": request, "env": dict(env or {})}, sort_keys=True, allow_nan=False).encode()
            ).hexdigest()

            async def provision(record: Dict[str, Any]) -> Dict[str, Any]:
                from agno.run.cancel import ais_cancelled

                allocation = allocation_for(record)
                if await ais_cancelled(run_id):
                    if record["phase"] == "stopping":
                        # A stop is already recorded; cleanup finishes it with its own status and reason.
                        return record
                    if record.get("computer") is None and record["phase"] == "executing":
                        orphan = await self.provider.afind(session_id, **allocation)
                        if orphan is not None:
                            record["computer"] = asdict(orphan)
                    record.update(
                        phase="stopping",
                        stop_status="CANCELLED",
                        stop_reason="Run cancelled",
                        computer_stopped=record.get("computer") is None,
                    )
                    return record
                # Checked before any early return: a retry must not finalize a staged result
                # under a different SDK or configuration.
                if record.get("request_hash") not in (None, fingerprint):
                    raise SandboxError("Active run configuration changed; reconnect with the original configuration")
                if record["phase"] != "executing":
                    return record
                record["request_hash"] = fingerprint
                # Keep caller metadata on the service side. Runtime output cannot replace it,
                # and caller values cannot control execution status or recovery decisions.
                record["run_metadata"] = {
                    key: value
                    for key, value in (metadata or {}).items()
                    if key not in ("sandbox", "warnings", "attempts", "retryable", "error_type")
                }
                native = record.get("native") or {}
                if native and NATIVE_SESSION_KEYS[sdk] not in native:
                    # Starting the other SDK fresh would fork the conversation.
                    held = ", ".join(sorted(name for name, key in NATIVE_SESSION_KEYS.items() if key in native))
                    record.update(
                        phase="stopping",
                        stop_status="ERROR",
                        stop_reason=f"This session's conversation belongs to {held}; it cannot continue with {sdk}",
                        computer_stopped=record.get("computer") is None,
                    )
                    return record
                if record.get("computer") is not None and record.get("warm_until") is None:
                    return record
                if record.get("computer") is not None:
                    # The last turn left its computer warm. Resume it if it is still there, inside
                    # its window and the same computer; otherwise retire it and take the cold path
                    # on a fresh generation.
                    resumed = await self._aresume_warm(record, allocation, execution_timeout)
                    if resumed is not None:
                        record.update(computer=asdict(resumed), warm_until=None, resumed=True)
                        return record
                    record.update(generation=record["generation"] + 1, computer=None, warm_until=None)
                    allocation = allocation_for(record)
                # No SDK execution can start before this binding commits. An
                # unbound allocation is a crashed provisioning attempt: replace
                # it before retrying restore, never restore over uncertain files.
                orphan = await self.provider.afind(session_id, for_create=True, **allocation)
                if orphan is not None:
                    await self.provider.adestroy(orphan)
                handle = await self.provider.acreate(session_id, **allocation)
                try:
                    if record.get("checkpoint"):
                        restored = await self.transfer.arestore(handle, CheckpointRef(**record["checkpoint"]))
                        if restored.get("binding") != record.get("checkpoint_identity"):
                            raise SandboxError("Checkpoint manifest does not match committed session identity")
                except CheckpointObjectNotFound:
                    # No retry can bring the object back; stop the turn instead of failing every attempt.
                    record.update(
                        phase="stopping",
                        stop_status="ERROR",
                        stop_reason=_CHECKPOINT_MISSING,
                        computer=asdict(handle),
                        computer_stopped=False,
                    )
                    return record
                except BaseException:
                    await self.provider.adestroy(handle)
                    raise
                record.update(computer=asdict(handle), computer_since=time.time(), resumed=False)
                return record

            try:
                state = await self.store._aoperation(lease, provision)
            except ValueError as error:
                committed = await self._retire_invalid(lease, error)
                yield self._terminal(committed)
                yield RunOutput.from_dict(committed)
                return
            if state.record["phase"] == "stopping":
                committed = await self._stop(
                    lease, status=state.record["stop_status"], reason=state.record["stop_reason"]
                )
            else:
                if state.record["phase"] == "executing":
                    handle = SandboxHandle(**state.record["computer"])
                    current = await self.provider.aget(handle.provider_ref)
                    if current is None or current.state != "running":
                        committed = await self._stop(
                            lease,
                            status="ERROR",
                            reason="Sandbox execution computer was lost; recover from the previous completed turn",
                            retryable=True,
                        )
                        yield self._terminal(committed)
                        yield RunOutput.from_dict(committed)
                        return
                    execution = RuntimeExecution(handle, state.record["execution_id"], run_id)
                    try:
                        # Identical execution identity/request reconciles a lost start acknowledgement.
                        await self.client.astart(
                            handle,
                            execution_id=execution.execution_id,
                            run_id=run_id,
                            sdk=sdk,
                            input=input,
                            user_id=user_id,
                            config=config,
                            execution_timeout=execution_timeout,
                            media=media,
                            **({"metadata": metadata} if metadata is not None else {}),
                            # The conversation the restored checkpoint must hold; None on a session's first turn.
                            native_session_id=(state.record.get("native") or {}).get(NATIVE_SESSION_KEYS[sdk]),
                        )
                    except ValueError as error:
                        committed = await self._retire_invalid(lease, error)
                        yield self._terminal(committed)
                        yield RunOutput.from_dict(committed)
                        return
                    cursor = 0
                    while True:
                        if heartbeat_error:
                            raise heartbeat_error[0]
                        from agno.run.cancel import ais_cancelled

                        if await ais_cancelled(run_id):
                            committed = await self._stop(lease, status="CANCELLED", reason="Run cancelled")
                            yield self._terminal(committed)
                            yield RunOutput.from_dict(committed)
                            return
                        page = await self.client.apoll(execution, cursor=cursor, wait=self.poll_wait)
                        cursor = page.cursor
                        # One lease check per page, before its events are published; the heartbeat
                        # keeps the lease alive. A resumed caller may receive provisional events
                        # again; queue/event transport supplies its own attempt fencing.
                        await self.store.aget(lease)
                        for event in page.events:
                            yield run_output_event_from_dict(event)
                        if page.result is not None:
                            if page.result["type"] != "execution_finished":
                                committed = await self._stop(
                                    lease,
                                    status="ERROR",
                                    reason=str(page.result.get("error", "Runtime outcome is unknown"))[:8192],
                                    # Any other failure may have run tools with side effects; never replay it.
                                    retryable=page.result.get("reason")
                                    in ("native_state_missing", "repository_preparation_failed"),
                                )
                                yield self._terminal(committed)
                                yield RunOutput.from_dict(committed)
                                return
                            state = await self.store.astage_result(lease, page.result)
                            break
                result = state.record["result"]["run"]
                native_id = (state.record["result"]["session"].get("session_data") or {}).get(NATIVE_SESSION_KEYS[sdk])
                native_failed = any(
                    isinstance(warning, dict) and warning.get("type") == "transcript_persistence_failed"
                    for warning in (result.get("metadata") or {}).get("warnings", [])
                )
                if native_failed:
                    committed = await self._stop(
                        lease,
                        status="ERROR",
                        reason="Native transcript persistence failed; cannot publish recoverable completion",
                    )
                elif result["status"] == "COMPLETED" and not native_id:
                    # Publishing it would leave the next turn no conversation to require.
                    committed = await self._stop(
                        lease,
                        status="ERROR",
                        reason="Completed turn reported no native conversation; cannot publish recoverable completion",
                    )
                elif state.record["result"]["run"]["status"] != "COMPLETED":
                    result = state.record["result"]["run"]
                    committed = await self._stop(
                        lease,
                        status=result["status"],
                        reason=str(result.get("content", "Execution failed"))[:8192],
                        retryable=(result.get("metadata") or {}).get("retryable") is not False,
                    )
                else:
                    committed = await self._finalize(lease)
            yield self._terminal(committed)
            yield RunOutput.from_dict(committed)
        except Exception as error:
            from agno.exceptions import RunCancelledException
            from agno.run.cancel import ais_cancelled

            # A cancel issued elsewhere, by the cancel endpoint or another replica, fences this
            # lease and retires this computer, so this attempt fails with a lost lease or a dead
            # transport. Report the cancellation the caller asked for rather than the failure it
            # caused, so the queue settles its ticket as cancelled instead of failed.
            if not isinstance(error, RunCancelledException) and await ais_cancelled(run_id):
                raise RunCancelledException("Run cancelled elsewhere") from error
            raise
        except asyncio.CancelledError:
            from agno.run.cancel import ais_cancelled
            from agno.run.concurrency import get_worker_ownership

            owner = get_worker_ownership(run_id)
            cause = owner.cancellation_cause if owner is not None else None
            if cause in ("user_cancel", "timeout") or await ais_cancelled(run_id):
                with suppress(SandboxLeaseLost):
                    await self._stop(
                        lease,
                        status="ERROR" if cause == "timeout" else "CANCELLED",
                        reason="Run timed out" if cause == "timeout" else "Run cancelled",
                        retryable=cause == "timeout",
                    )
            # Shutdown/disconnect alone detaches; the queue's next attempt uses
            # this generation's execution journal instead of rerunning tools.
            raise
        finally:
            heart.cancel()
            with suppress(asyncio.CancelledError):
                await heart
            if committed is None:
                # The caller is leaving a turn that is still running: detach, keep execution going.
                # Shielded so a further cancel cannot abort the release and leave the lease to run out.
                with suppress(SandboxLeaseLost):
                    await _settled(self.store.arelinquish(lease))
            else:
                await self._aprune_checkpoints(session_id)

    async def _aprune_checkpoints(self, session_id: str) -> None:
        """Delete the checkpoints retention retired; best-effort, a later turn retries what is left."""
        try:
            deleted = []
            for reference in await self.store.aretired_checkpoints(session_id):
                try:
                    await self.transfer.store.adelete(CheckpointRef(**reference))
                except Exception as error:
                    log_warning(f"Could not delete retired sandbox checkpoint {reference.get('sha256')}: {error}")
                    continue
                deleted.append(reference)
            if deleted:
                await self.store.aforget_checkpoints(session_id, deleted)
        except Exception as error:
            log_warning(f"Sandbox checkpoint retention for session {session_id} failed: {error}")

    async def _retire_invalid(self, lease: SandboxLease, error: ValueError) -> Dict[str, Any]:
        # A request the runtime can never accept was only caught after the claim, before anything
        # executed. Retire the turn so the session is released: propagating would leave the run
        # bound to it, and every retry would fail the same way. Provider and transport failures
        # still propagate, since a retry of the same run reconciles them.
        return await self._stop(lease, status="ERROR", reason=str(error)[:8192] or "Invalid runtime request")

    async def _aresume_warm(
        self, record: Dict[str, Any], allocation: Dict[str, Any], execution_timeout: float
    ) -> Optional[SandboxHandle]:
        """The last turn's warm computer, resumed and running; None once it has been retired."""
        kept = SandboxHandle(**record["computer"])
        usable = time.time() < float(record["warm_until"])
        lifetime = getattr(self.provider, "lifetime", None)
        if usable and isinstance(lifetime, (int, float)):
            # A provider that ends computers at a fixed lifetime must still have room for this turn.
            usable = time.time() - float(record.get("computer_since") or 0) + execution_timeout + 120 < lifetime
        found: Optional[SandboxHandle] = None
        if usable:
            try:
                found = await self.provider.afind(kept.session_id, **allocation)
            except SandboxError:
                found = None
        if found is not None and found.name == kept.name:
            try:
                if found.state == "paused":
                    found = await self.provider.aresume(found)
                if found.state == "running":
                    return found
            except SandboxError:
                pass
        # Gone, expired, changed or not resumable: nothing of it may stay behind.
        with suppress(Exception):
            await self.provider.adestroy(kept)
        return None

    async def _akeep_warm(self, handle: SandboxHandle) -> bool:
        """Park the computer for the next turn: paused where the provider can, idle otherwise."""
        try:
            await self.provider.apause(handle)
        except NotImplementedError:
            return True
        except SandboxError:
            return False
        return True

    async def _finalize(self, lease: SandboxLease) -> Dict[str, Any]:
        async def capture(record: Dict[str, Any]) -> Dict[str, Any]:
            if record["phase"] != "finalizing":
                raise SandboxError("Only retained execution output can be finalized")
            if record.get("staged_checkpoint") is None:
                handle = SandboxHandle(**record["computer"])
                current = await self.provider.aget(handle.provider_ref)
                if current is None or current.state != "running":
                    record.update(
                        phase="stopping",
                        stop_status="ERROR",
                        stop_reason="Completed execution lost compute before checkpointing; model execution will not be repeated",
                    )
                    return record
                identity = dict(
                    agent_id=lease.agent_id,
                    session_id=lease.session_id,
                    user_id=lease.user_id,
                    incarnation=record["incarnation"],
                    run_id=lease.run_id,
                    execution_id=record["execution_id"],
                    generation=record["generation"],
                )
                # A digest, not the result: the manifest is capped at the runtime's own result limit.
                digest = hashlib.sha256(
                    json.dumps(record["result"], sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                ).hexdigest()
                try:
                    reference = await self.transfer.acapture(
                        handle, state={"binding": identity, "result_sha256": digest}
                    )
                except CheckpointContentError as error:
                    # Capturing the same files again fails the same way; a retry would only keep the session busy.
                    record.update(
                        phase="stopping",
                        stop_status="ERROR",
                        stop_reason=(
                            "Completed turn's files cannot be checkpointed, so they were discarded and the session "
                            f"continues from the previous checkpoint: {error}"
                        )[:8192],
                    )
                    return record
                await self.transfer.store.averify(reference)
                record.update(staged_checkpoint=asdict(reference), staged_identity=identity)
            await self.transfer.store.averify(CheckpointRef(**record["staged_checkpoint"]))
            return record

        state = await self.store._aoperation(lease, capture)
        if state.record["phase"] == "stopping":
            return await self._stop(lease, status="ERROR", reason=state.record["stop_reason"])
        handle = SandboxHandle(**state.record["computer"]) if state.record.get("computer") is not None else None
        keep_until: Optional[float] = None
        if handle is not None and self.warm_computer_seconds > 0 and await self._akeep_warm(handle):
            keep_until = time.time() + self.warm_computer_seconds
        elif handle is not None:
            await self.provider.adestroy(handle)
            if await self.provider.aget(handle.provider_ref) is not None:
                raise SandboxError("Provider has not confirmed compute removal")
            await self.store.aconfirm_stopped(lease, handle.provider_ref)
        try:
            return await self.store.acommit(
                lease, keep_computer_until=keep_until, retain_checkpoints=self.retain_checkpoints
            )
        except SandboxRunFinished as finished:
            # Another writer finished the run; the commit already released the session and kept
            # the previous checkpoint, so the stored outcome is the result.
            if keep_until is not None and handle is not None:
                with suppress(Exception):
                    await self.provider.adestroy(handle)
            return finished.run

    @staticmethod
    def _terminal(run: Dict[str, Any]) -> Any:
        fields: Dict[str, Any] = {key: run.get(key) for key in ("run_id", "agent_id", "session_id", "content")}
        if run["status"] == "COMPLETED":
            output = RunOutput.from_dict(deepcopy(run))
            return RunCompletedEvent(**fields, content_type=output.content_type, metrics=output.metrics)
        if run["status"] == "CANCELLED":
            fields.pop("content")
            return RunCancelledEvent(**fields, reason="Run cancelled")
        return RunErrorEvent(**fields)
