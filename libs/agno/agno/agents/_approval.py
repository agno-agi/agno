"""Human decisions for live native harness requests. A decision never starts a turn."""

import asyncio
import hashlib
import inspect
import json
import math
import time
from contextlib import suppress
from contextvars import ContextVar
from typing import Any, AsyncIterator, Dict, Iterator, Optional
from uuid import uuid4

from agno.models.response import ToolExecution
from agno.run.agent import RunContinuedEvent, RunPausedEvent
from agno.run.base import RunStatus
from agno.run.cancel import araise_if_cancelled
from agno.run.requirement import RunRequirement

_current: ContextVar[Optional["ApprovalBridge"]] = ContextVar("harness_approval", default=None)
_MARKER = "native_approval"


async def db_call(db: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    # Keep synchronous SQLite connections on their owning thread (including :memory:).
    result = getattr(db, method)(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def active_bridge() -> Optional["ApprovalBridge"]:
    return _current.get()


def current_bridge() -> "ApprovalBridge":
    bridge = _current.get()
    if bridge is None:
        raise RuntimeError("Human approvals require an active Agno run")
    return bridge


def action_digest(value: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def validate_human_mode(agent: Any) -> None:
    if agent.db is None:
        raise ValueError("Native approvals require an approval-capable database")
    if not math.isfinite(agent.approval_timeout) or not 0 < agent.approval_timeout <= 86400:
        raise ValueError("approval_timeout must be between 0 and 86400 seconds")


async def _retire_direct_approvals(agent: Any, run_id: str, status: str) -> None:
    page = 1
    while True:
        rows, total = await db_call(agent.db, "get_approvals", run_id=run_id, page=page, limit=100)
        for row in rows:
            if not (row.get("context") or {}).get(_MARKER):
                continue
            values: Dict[str, Any] = {"run_status": status}
            if row.get("run_status") == "PAUSED" and row["status"] in ("pending", "approved", "rejected"):
                values["status"] = "expired" if row.get("expires_at", 0) <= time.time() else "cancelled"
            await db_call(agent.db, "update_approval", row["id"], expected_status=row["status"], **values)
        if page * 100 >= total or not rows:
            return
        page += 1


class ApprovalBridge:
    def __init__(self, agent: Any, run_id: str, session_id: str, user_id: Optional[str], allow_requests: bool = True):
        self.agent = agent
        self.run_id = run_id
        self.session_id = session_id
        self.user_id = user_id
        self.owner = uuid4().hex
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        self.requests: Dict[str, Dict[str, Any]] = {}
        self.closed = False
        self.allow_requests = allow_requests

    async def request(self, tool_name: str, arguments: Dict[str, Any], native: Dict[str, Any]) -> bool:
        if not self.allow_requests:
            raise ValueError("Native approval requests currently require a standalone Claude or Codex agent")
        if self.closed:
            raise RuntimeError("The approval execution is no longer available")
        # Bound both persisted and transported data before emitting a reviewable action.
        action = {"tool_name": tool_name, "tool_args": arguments, "native": native}
        if len(json.dumps(action, allow_nan=False).encode()) > 65536:
            raise ValueError("Native approval request exceeds 64 KiB")
        approval_id = str(uuid4())
        expires = time.time() + self.agent.approval_timeout
        context = {"version": 1, "owner": self.owner, "digest": action_digest(action), "native": native}
        tool = ToolExecution(
            tool_call_id=str(native.get("tool_call_id") or approval_id),
            tool_name=tool_name,
            tool_args=arguments,
            requires_confirmation=True,
            approval_type="required",
            approval_id=approval_id,
        )
        requirement = RunRequirement(tool_execution=tool)
        record = {
            "id": approval_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "agent_id": self.agent.get_id(),
            "user_id": self.user_id,
            "source_type": "agent",
            "source_name": self.agent.name,
            "status": "pending",
            "approval_type": "required",
            "pause_type": "confirmation",
            "tool_name": tool_name,
            "tool_args": arguments,
            "requirements": [requirement.to_dict()],
            "context": {_MARKER: context},
            "created_at": int(time.time()),
            "expires_at": math.ceil(expires),
            "run_status": "PAUSED",
        }
        await db_call(self.agent.db, "create_approval", record)
        self.requests[approval_id] = record
        ready = asyncio.Event()
        event = RunPausedEvent(
            run_id=self.run_id,
            session_id=self.session_id,
            agent_id=self.agent.get_id(),
            tools=[tool],
            requirements=[requirement],
            approval=record,
        )
        await self.queue.put((event, ready))
        try:
            # No decision is consumed before the paused run is persisted and published.
            await asyncio.wait_for(ready.wait(), max(0.001, expires - time.time()))
            while True:
                await araise_if_cancelled(self.run_id)
                if self.closed:
                    raise RuntimeError("The approval execution is no longer available")
                if time.time() >= expires:
                    await self._retire(approval_id, "expired")
                    raise TimeoutError("Native permission request expired")
                row = await db_call(self.agent.db, "get_approval", approval_id)
                if row is None or row.get("status") in ("cancelled", "expired"):
                    raise RuntimeError("Native permission request is no longer available")
                decision = (row.get("resolution_data") or {}).get(_MARKER)
                if row.get("status") in ("approved", "rejected") and decision == context:
                    allowed = row["status"] == "approved"
                    tool.confirmed = allowed
                    requirement.confirmation = allowed
                    record.update(row)
                    acknowledged = asyncio.Event()
                    await self.queue.put(
                        (
                            RunContinuedEvent(
                                approval_id=approval_id,
                                run_id=self.run_id,
                                session_id=self.session_id,
                                agent_id=self.agent.get_id(),
                            ),
                            acknowledged,
                        )
                    )
                    await asyncio.wait_for(acknowledged.wait(), max(0.001, expires - time.time()))
                    await araise_if_cancelled(self.run_id)
                    if self.closed:
                        raise RuntimeError("The approval execution is no longer available")
                    accepted = await db_call(
                        self.agent.db,
                        "update_approval",
                        approval_id,
                        expected_status=row["status"],
                        run_status="RUNNING",
                    )
                    if accepted is None:
                        raise RuntimeError("Native approval changed before acknowledgement")
                    return allowed
                await asyncio.sleep(0.1)
        except BaseException as error:
            await self._retire(approval_id, "cancelled")
            if not isinstance(error, asyncio.CancelledError):
                await self.queue.put((error, None))
            raise

    async def _retire(self, approval_id: str, status: str) -> None:
        row = await db_call(self.agent.db, "get_approval", approval_id)
        if row and row.get("status") in ("pending", "approved", "rejected"):
            await db_call(self.agent.db, "update_approval", approval_id, expected_status=row["status"], status=status)

    async def events(self, source: AsyncIterator[Any]) -> AsyncIterator[Any]:
        async def produce() -> None:
            token = _current.set(self)
            try:
                async for event in source:
                    await self.queue.put((event, None))
            except BaseException as error:
                await self.queue.put((error, None))
            finally:
                _current.reset(token)
                await self.queue.put((None, None))

        task = asyncio.create_task(produce())
        try:
            while True:
                event, ready = await self.queue.get()
                if event is None:
                    break
                if isinstance(event, BaseException):
                    raise event
                yield event
                if ready is not None:
                    ready.set()
        finally:
            self.closed = True
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            for approval_id, record in self.requests.items():
                # Decisions that reached the native callback remain in the audit history.
                if not (record.get("resolution_data") or {}).get(_MARKER):
                    await self._retire(approval_id, "cancelled")


async def submit_decisions(agent: Any, run_id: str, session_id: str, user_id: Optional[str], tools: Any = None) -> Any:
    run = await agent.aget_run_output(run_id, session_id=session_id, user_id=user_id)
    if run is None or run.agent_id != agent.get_id() or run.session_id != session_id:
        raise ValueError("Native approval run not found")
    if run.status not in (RunStatus.paused, RunStatus.running):
        raise ValueError("Native approval execution is no longer available")
    ids = (run.metadata or {}).get(_MARKER, {}).get("approval_ids", [])
    if not ids:
        raise ValueError("Run has no live native approval requests")
    supplied = {t.tool_call_id: t for t in tools or []}
    rows = []
    for approval_id in ids:
        row = await db_call(agent.db, "get_approval", approval_id)
        if not row or row.get("run_id") != run_id or row.get("session_id") != session_id:
            raise ValueError("Native approval identity mismatch")
        if row.get("status") not in ("approved", "rejected"):
            raise ValueError("Resolve the approval before continuing the run")
        if row.get("expires_at", 0) <= time.time():
            raise ValueError("Native approval has expired")
        context = (row.get("context") or {}).get(_MARKER)
        if not context or context.get("digest") != action_digest(
            {"tool_name": row.get("tool_name"), "tool_args": row.get("tool_args"), "native": context.get("native")}
        ):
            raise ValueError("Native approval action does not match its recorded digest")
        owner = (run.metadata or {}).get(_MARKER, {}).get("owner")
        if (
            row.get("agent_id") != agent.get_id()
            or row.get("user_id") != run.user_id
            or (owner is not None and context.get("owner") != owner)
        ):
            raise ValueError("Native approval execution identity mismatch")
        for req in row.get("requirements") or []:
            te = req["tool_execution"]
            candidate = supplied.get(te["tool_call_id"])
            if candidate is not None and (
                candidate.tool_name != te["tool_name"]
                or candidate.tool_args != te["tool_args"]
                or candidate.confirmed != (row["status"] == "approved")
            ):
                raise ValueError("Continuation does not match the reviewed native action")
        rows.append(row)
    known = {req["tool_execution"]["tool_call_id"] for row in rows for req in row.get("requirements") or []}
    if supplied.keys() - known:
        raise ValueError("Continuation contains an unknown native tool request")
    for row in rows:
        context = row["context"][_MARKER]
        result = await db_call(
            agent.db, "update_approval", row["id"], expected_status=row["status"], resolution_data={_MARKER: context}
        )
        if result is None:
            raise ValueError("Native approval changed before delivery")
    return run


async def continue_stream(
    agent: Any, run_id: str, session_id: str, user_id: Optional[str], tools: Any
) -> AsyncIterator[Any]:
    before = await agent.aget_run_output(run_id, session_id=session_id, user_id=user_id)
    cursor = len(before.events or []) if before else 0
    await submit_decisions(agent, run_id, session_id, user_id, tools)
    async for event in tail_stored(agent, run_id, session_id, user_id, cursor):
        yield event


async def tail_stored(
    agent: Any, run_id: str, session_id: str, user_id: Optional[str], cursor: int
) -> AsyncIterator[Any]:
    deadline = time.monotonic() + agent.approval_timeout
    while time.monotonic() < deadline:
        run = await agent.aget_run_output(run_id, session_id=session_id, user_id=user_id)
        if run is None:
            raise ValueError("Native approval run is no longer available")
        events = run.events or []
        for event in events[cursor:]:
            yield event
        progressed = len(events) > cursor
        cursor = len(events)
        if run.status in (RunStatus.completed, RunStatus.cancelled, RunStatus.error) or (
            progressed and run.status == RunStatus.paused
        ):
            yield run
            return
        await asyncio.sleep(0.1)
    raise TimeoutError("Native approval continuation timed out; inspect the persisted run")


def continue_run(
    agent: Any,
    run_response: Any = None,
    *,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    updated_tools: Any = None,
    requirements: Any = None,
    stream: bool = False,
    **kwargs: Any,
) -> Any:
    if (
        kwargs.get("fork")
        or kwargs.get("regenerate")
        or kwargs.get("input")
        or kwargs.get("additional_instructions")
        or kwargs.get("continue_from", "end") != "end"
    ):
        raise ValueError("Native permission continuation only delivers a reviewed decision")
    run_id = run_id or getattr(run_response, "run_id", None)
    session_id = session_id or getattr(run_response, "session_id", None)
    if not run_id or not session_id:
        raise ValueError("Native approval continuation requires run_id and session_id")
    tools = updated_tools or [r.tool_execution for r in requirements or []]
    events = continue_stream(agent, run_id, session_id, user_id, tools)
    if stream:
        return events

    async def result() -> Any:
        from agno.run.agent import RunOutput

        async for item in events:
            if isinstance(item, RunOutput):
                return item
        raise RuntimeError("Native approval continuation returned no run")

    return result()


def sync_events(events: AsyncIterator[Any]) -> Iterator[Any]:
    """Consume a continuation with one loop for the whole iterator's lifetime."""
    # Continuation tails only read persisted state; closing this iterator must not
    # cancel the independently owned native run.
    loop = asyncio.new_event_loop()
    try:
        while True:
            try:
                yield loop.run_until_complete(events.__anext__())
            except StopAsyncIteration:
                break
    finally:
        loop.run_until_complete(events.aclose())  # type: ignore[attr-defined]
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


async def wait_for_execution(task: Any, active_timeout: float, approval_timeout: float, is_waiting: Any) -> bool:
    """Wait with separate bounded active and cumulative human-wait budgets.

    The owner cancels the task after this returns False, so it can stamp the
    timeout cause before cancellation reaches the native execution.
    """
    active = waiting = 0.0
    previous = time.monotonic()
    while not task.done():
        paused = is_waiting()
        if inspect.isawaitable(paused):
            paused = await paused
        await asyncio.wait(
            {task}, timeout=min(0.25, max(0.001, active_timeout - active), max(0.001, approval_timeout - waiting))
        )
        now = time.monotonic()
        if paused:
            waiting += now - previous
        else:
            active += now - previous
        previous = now
        if active >= active_timeout or waiting >= approval_timeout:
            return task.done()
    return True
