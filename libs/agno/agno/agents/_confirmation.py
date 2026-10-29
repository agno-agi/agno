"""Human-in-the-loop confirmation of a live harness agent's native permission requests.

Claude Code and Codex ask before using a tool their native policy does not allow. Each request pauses
the Agno run with a tool that requires confirmation, as an Agno agent's confirmation tool does: the
paused run carries the request as a requirement, and the person confirms or rejects it in the chat.
Continuing the run delivers that decision to the same native execution, which is still waiting for it,
so a decision never starts or replays a turn.

The run row is the only shared state. The paused run records each pending request with a digest of the
exact action; a continuation records the decision and moves the run from PAUSED to RUNNING in one
conditional write, and the waiting execution reads the decision from the row. Any replica can therefore
deliver a decision, and a repeated or stale continuation finds the run no longer paused.
"""

import asyncio
import hashlib
import inspect
import json
import math
import threading
import time
from contextlib import suppress
from contextvars import ContextVar
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Set
from uuid import uuid4

from agno.models.response import ToolExecution
from agno.run.agent import RunContinuedEvent, RunPausedEvent
from agno.run.base import RunStatus
from agno.run.cancel import araise_if_cancelled
from agno.run.requirement import RunRequirement

_current: ContextVar[Optional["ConfirmationBridge"]] = ContextVar("harness_confirmation", default=None)
# Run metadata key holding the native confirmation state.
KEY = "native_confirmation"


async def db_call(db: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    fn = getattr(db, method)
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    if getattr(getattr(getattr(db, "db_engine", None), "dialect", None), "name", None) == "postgresql":
        return await asyncio.to_thread(fn, *args, **kwargs)
    # Keep synchronous SQLite connections on their owning thread (including :memory:).
    result = fn(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


async def read_run(agent: Any, run_id: str, session_id: Optional[str], user_id: Optional[str]) -> Any:
    """Read only the requested run, preserving agent/session/user isolation."""
    from agno.run.agent import RunOutput

    if getattr(agent, "db", None) is None:
        return await agent.aget_run_output(run_id, session_id=session_id, user_id=user_id)
    run = await db_call(agent.db, "get_run", run_id)
    if isinstance(run, dict):
        run = RunOutput.from_dict(run)
    if run is None or run.agent_id != agent.get_id() or run.session_id != session_id:
        return None
    if user_id is not None and run.user_id != user_id:
        return None
    return run


def confirmation_state(run: Any) -> Dict[str, Any]:
    return dict((getattr(run, "metadata", None) or {}).get(KEY) or {})


def pending_ids(run: Any) -> List[str]:
    return list(confirmation_state(run).get("pending") or [])


def active_bridge() -> Optional["ConfirmationBridge"]:
    return _current.get()


def current_bridge() -> "ConfirmationBridge":
    bridge = _current.get()
    if bridge is None:
        raise RuntimeError("Native confirmations require an active Agno run")
    return bridge


def action_digest(value: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def validate_native_confirmations(agent: Any) -> None:
    if agent.db is None:
        raise ValueError("Native confirmations require a database")
    if not math.isfinite(agent.confirmation_timeout) or not 0 < agent.confirmation_timeout <= 86400:
        raise ValueError("confirmation_timeout must be between 0 and 86400 seconds")


class ConfirmationBridge:
    """Turns a running harness's native permission requests into paused-run confirmations."""

    def __init__(self, agent: Any, run_id: str, session_id: str, user_id: Optional[str], allow_requests: bool = True):
        self.agent = agent
        self.run_id = run_id
        self.session_id = session_id
        self.user_id = user_id
        self.owner = uuid4().hex
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        # tool_call_id -> {"digest", "native", "expires_at", "requirement"}
        self.requests: Dict[str, Dict[str, Any]] = {}
        self.decisions: Dict[str, Dict[str, Any]] = {}
        self.pending: List[str] = []
        self.closed = False
        self.allow_requests = allow_requests
        # One request waits at a time, so the run row has one writer at a time: this execution while it
        # runs, the continuation while the run is paused.
        self._lock = asyncio.Lock()

    def state(self) -> Dict[str, Any]:
        """The run metadata entry describing this execution's requests."""
        return {
            "owner": self.owner,
            "pending": list(self.pending),
            "requests": {
                key: {k: v for k, v in value.items() if k != "requirement"} for key, value in self.requests.items()
            },
            "decisions": dict(self.decisions),
        }

    def pending_requirements(self) -> List[RunRequirement]:
        return [self.requests[key]["requirement"] for key in self.pending]

    async def request(self, tool_name: str, arguments: Dict[str, Any], native: Dict[str, Any]) -> bool:
        """Pause the run for one native request and return whether the person confirmed it."""
        if not self.allow_requests:
            raise ValueError("Native permission requests currently require a standalone Claude or Codex agent")
        async with self._lock:
            return await self._request(tool_name, arguments, native)

    async def _request(self, tool_name: str, arguments: Dict[str, Any], native: Dict[str, Any]) -> bool:
        if self.closed:
            raise RuntimeError("The native execution is no longer available")
        # Bound both persisted and transported data before showing an action for review.
        action = {"tool_name": tool_name, "tool_args": arguments, "native": native}
        if len(json.dumps(action, allow_nan=False).encode()) > 65536:
            raise ValueError("Native permission request exceeds 64 KiB")
        tool_call_id = str(native.get("tool_call_id") or uuid4())
        if tool_call_id in self.requests:
            tool_call_id = f"{tool_call_id}:{uuid4().hex[:8]}"
        expires = time.time() + self.agent.confirmation_timeout
        digest = action_digest(action)
        # An ordinary confirmation, answered in the chat like an Agno agent's confirmation tool.
        tool = ToolExecution(
            tool_call_id=tool_call_id, tool_name=tool_name, tool_args=arguments, requires_confirmation=True
        )
        requirement = RunRequirement(tool_execution=tool)
        self.requests[tool_call_id] = {
            "digest": digest,
            "native": native,
            "expires_at": math.ceil(expires),
            "requirement": requirement,
        }
        self.pending = [tool_call_id]
        ready = asyncio.Event()
        event = RunPausedEvent(
            run_id=self.run_id,
            session_id=self.session_id,
            agent_id=self.agent.get_id(),
            tools=[tool],
            requirements=[requirement],
            native_confirmation={
                "tool_call_id": tool_call_id,
                "owner": self.owner,
                "digest": digest,
                "native": native,
                "expires_at": math.ceil(expires),
                "requirement": requirement.to_dict(),
            },
        )
        await self.queue.put((event, ready))
        try:
            # No decision is read before the paused run is persisted and published.
            await asyncio.wait_for(ready.wait(), max(0.001, expires - time.time()))
            while True:
                await araise_if_cancelled(self.run_id)
                if self.closed:
                    raise RuntimeError("The native execution is no longer available")
                if time.time() >= expires:
                    raise TimeoutError("Native permission request expired before it was confirmed")
                run = await read_run(self.agent, self.run_id, self.session_id, self.user_id)
                if run is None or run.status == RunStatus.cancelled:
                    raise RuntimeError("The paused run is no longer available")
                decision = (confirmation_state(run).get("decisions") or {}).get(tool_call_id)
                if decision and decision.get("digest") == digest and decision.get("owner") == self.owner:
                    allowed = decision.get("confirmed") is True
                    tool.confirmed = allowed
                    requirement.confirmation = allowed
                    self.decisions[tool_call_id] = decision
                    self.pending = []
                    acknowledged = asyncio.Event()
                    await self.queue.put(
                        (
                            RunContinuedEvent(
                                run_id=self.run_id,
                                session_id=self.session_id,
                                agent_id=self.agent.get_id(),
                                native_confirmation_id=tool_call_id,
                            ),
                            acknowledged,
                        )
                    )
                    await asyncio.wait_for(acknowledged.wait(), max(0.001, expires - time.time()))
                    await araise_if_cancelled(self.run_id)
                    return allowed
                await asyncio.sleep(min(1.0, max(0.001, expires - time.time())))
        except BaseException as error:
            self.pending = []
            if not isinstance(error, asyncio.CancelledError):
                await self.queue.put((error, None))
            raise

    async def events(self, source: AsyncIterator[Any]) -> AsyncIterator[Any]:
        """Multiplex the adapter's events with this bridge's pause and continue events."""

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


# A database without a conditional run update is used by one process: a per-run lock there keeps two
# continuations from both acting on the same paused run. Several replicas need the conditional update.
_local_continuations: Dict[str, threading.Lock] = {}
_local_continuations_guard = threading.Lock()


async def _record_decisions(agent: Any, run: Any, fields: Dict[str, Any], pending: List[str]) -> bool:
    """Write ``fields`` and move the run from PAUSED to RUNNING, only while it still waits on ``pending``.

    Matching the pending requests, not only the status, matters: a stale continuation that arrives after
    the run continued and paused again for a new request must not overwrite that new pause.
    """
    expected = {"status": RunStatus.paused.value, f"metadata.{KEY}.pending": pending}
    if callable(getattr(agent.db, "update_run_if_matches", None)):
        return bool(
            await db_call(
                agent.db,
                "update_run_if_matches",
                run.run_id,
                run.session_id,
                expected,
                fields,
                user_id=run.user_id,
            )
        )
    with _local_continuations_guard:
        lock = _local_continuations.setdefault(run.run_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return False
    try:
        current = await read_run(agent, run.run_id, run.session_id, run.user_id)
        if current is None or current.status != RunStatus.paused or pending_ids(current) != pending:
            return False
        current.status = RunStatus.running
        current.metadata = fields["metadata"]
        current.requirements = [RunRequirement.from_dict(r) for r in fields["requirements"]]
        session = await agent.aread_or_create_session(run.session_id, run.user_id)
        await agent._apersist_run_in_session(session, current, strict=True)
        return True
    finally:
        lock.release()
        with _local_continuations_guard:
            _local_continuations.pop(run.run_id, None)


async def submit_decisions(agent: Any, run_id: str, session_id: str, user_id: Optional[str], tools: Any = None) -> Any:
    """Record the chat's confirm or reject for every pending native request of a paused run.

    ``tools`` are the paused run's tools as the chat returns them, with ``confirmed`` set on each pending
    one; tools that are not pending, such as earlier tool calls, are ignored. Each decision must match the
    reviewed action exactly. The waiting native execution reads the decision and continues.
    """
    run = await read_run(agent, run_id, session_id, user_id)
    if run is None:
        raise ValueError("Native confirmation run not found")
    if run.status != RunStatus.paused:
        raise ValueError("Run is not waiting for a confirmation")
    state = confirmation_state(run)
    pending = list(state.get("pending") or [])
    if not pending:
        raise ValueError("Run has no pending native confirmation")
    supplied = {t.tool_call_id: t for t in tools or [] if getattr(t, "tool_call_id", None)}
    reviewed = {r.tool_execution.tool_call_id: r for r in run.requirements or [] if r.tool_execution is not None}
    decisions = dict(state.get("decisions") or {})
    for tool_call_id in pending:
        request = (state.get("requests") or {}).get(tool_call_id)
        requirement = reviewed.get(tool_call_id)
        if request is None or requirement is None:
            raise ValueError("Native confirmation request is missing from the paused run")
        if request.get("expires_at", 0) <= time.time():
            raise ValueError("Native confirmation request has expired")
        tool = requirement.tool_execution
        assert tool is not None
        if request.get("digest") != action_digest(
            {"tool_name": tool.tool_name, "tool_args": tool.tool_args, "native": request.get("native")}
        ):
            raise ValueError("Native confirmation does not match its recorded action")
        candidate = supplied.get(tool_call_id)
        if candidate is None or candidate.confirmed is None:
            raise ValueError(f"Confirm or reject the pending '{tool.tool_name}' request to continue")
        if candidate.tool_name != tool.tool_name or candidate.tool_args != tool.tool_args:
            raise ValueError("Continuation does not match the reviewed native action")
        confirmed = candidate.confirmed is True
        decisions[tool_call_id] = {"confirmed": confirmed, "digest": request["digest"], "owner": state.get("owner")}
        tool.confirmed = confirmed
        requirement.confirmation = confirmed
    metadata = {**(run.metadata or {}), KEY: {**state, "pending": [], "decisions": decisions}}
    fields = {
        "status": RunStatus.running.value,
        "metadata": metadata,
        "requirements": [r.to_dict() for r in run.requirements or []],
    }
    if not await _record_decisions(agent, run, fields, pending):
        raise ValueError("Run was already continued or is no longer paused")
    run.status = RunStatus.running
    run.metadata = metadata
    return run


async def record_decision(
    agent: Any,
    run_id: str,
    session_id: str,
    user_id: Optional[str],
    *,
    tool_call_id: str,
    confirmed: bool,
    digest: str,
    owner: str,
) -> bool:
    """Record one decision a coordinator delivers to a sandbox runtime's paused run.

    The coordinator delivers a decision a continuation already validated on the host; this checks it
    still answers the exact pending request. A repeated delivery of the same decision is accepted.
    """
    run = await read_run(agent, run_id, session_id, user_id)
    if run is None:
        raise ValueError("Unknown native confirmation run")
    state = confirmation_state(run)
    decision = {"confirmed": confirmed is True, "digest": digest, "owner": owner}
    existing = (state.get("decisions") or {}).get(tool_call_id)
    if existing is not None:
        return existing == decision
    request = (state.get("requests") or {}).get(tool_call_id)
    if run.status != RunStatus.paused or tool_call_id not in (state.get("pending") or []) or request is None:
        raise ValueError("The native request is not waiting for a decision")
    if request.get("digest") != digest or state.get("owner") != owner:
        raise ValueError("The decision does not answer this native request")
    if request.get("expires_at", 0) <= time.time():
        raise ValueError("Native confirmation request has expired")
    for requirement in run.requirements or []:
        if requirement.tool_execution is not None and requirement.tool_execution.tool_call_id == tool_call_id:
            requirement.tool_execution.confirmed = decision["confirmed"]
            requirement.confirmation = decision["confirmed"]
    decisions = {**(state.get("decisions") or {}), tool_call_id: decision}
    metadata = {**(run.metadata or {}), KEY: {**state, "pending": [], "decisions": decisions}}
    fields = {
        "status": RunStatus.running.value,
        "metadata": metadata,
        "requirements": [r.to_dict() for r in run.requirements or []],
    }
    return await _record_decisions(agent, run, fields, list(state.get("pending") or []))


async def continue_stream(
    agent: Any, run_id: str, session_id: str, user_id: Optional[str], tools: Any
) -> AsyncIterator[Any]:
    before = await submit_decisions(agent, run_id, session_id, user_id, tools)
    answered = set(confirmation_state(before).get("decisions") or {})
    async for event in tail_stored(agent, run_id, session_id, user_id, len(before.events or []), answered):
        yield event


async def tail_stored(
    agent: Any,
    run_id: str,
    session_id: str,
    user_id: Optional[str],
    cursor: int,
    answered: Optional[Set[str]] = None,
) -> AsyncIterator[Any]:
    """Follow a continued run through its stored events until it ends or pauses for a new request.

    ``answered`` are the requests this continuation decided; a pause for any other request is new.
    Without it, the requests pending at the first read count as answered.
    """
    deadline = time.monotonic() + agent.confirmation_timeout
    submitted = answered
    while time.monotonic() < deadline:
        run = await read_run(agent, run_id, session_id, user_id)
        if run is None:
            raise ValueError("Native confirmation run is no longer available")
        events = run.events or []
        for event in events[cursor:]:
            yield event
        ids = set(pending_ids(run))
        if submitted is None:
            submitted = ids
        new_pause = run.status == RunStatus.paused and bool(ids - submitted)
        if new_pause and not any(getattr(event, "event", None) == "RunPaused" for event in events[cursor:]):
            # Sandbox snapshots can advance before their events are retained.
            yield RunPausedEvent(
                run_id=run_id,
                session_id=session_id,
                agent_id=run.agent_id,
                content=run.content,
                tools=run.tools,
                requirements=run.requirements,
            )
        cursor = len(events)
        if run.status in (RunStatus.completed, RunStatus.cancelled, RunStatus.error) or new_pause:
            yield run
            return
        await asyncio.sleep(min(1.0, max(0.001, agent.confirmation_timeout / 10)))
    raise TimeoutError("Native confirmation continuation timed out; inspect the persisted run")


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
        raise ValueError("Continuing a native confirmation only delivers the confirm or reject decision")
    run_id = run_id or getattr(run_response, "run_id", None)
    session_id = session_id or getattr(run_response, "session_id", None)
    if not run_id or not session_id:
        raise ValueError("Native confirmation continuation requires run_id and session_id")
    if updated_tools is None and requirements is None and run_response is not None:
        requirements = getattr(run_response, "requirements", None)
    tools = updated_tools or [r.tool_execution for r in requirements or [] if r.tool_execution is not None]
    events = continue_stream(agent, run_id, session_id, user_id, tools)
    if stream:
        return events

    async def result() -> Any:
        from agno.run.agent import RunOutput

        async for item in events:
            if isinstance(item, RunOutput):
                return item
        raise RuntimeError("Native confirmation continuation returned no run")

    return result()


def sync_events(events: AsyncIterator[Any]) -> Iterator[Any]:
    """Consume a continuation with one loop for the whole iterator's lifetime."""
    # Continuation tails only read persisted state; closing this iterator must not
    # cancel the independently owned native run.
    from concurrent.futures import ThreadPoolExecutor

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pool = None
    else:
        pool = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.new_event_loop()

    def drive(coro: Any) -> Any:
        return pool.submit(loop.run_until_complete, coro).result() if pool else loop.run_until_complete(coro)

    try:
        while True:
            try:
                yield drive(events.__anext__())
            except StopAsyncIteration:
                break
    finally:
        try:
            drive(events.aclose())  # type: ignore[attr-defined]
            drive(loop.shutdown_asyncgens())
        finally:
            loop.close()
            if pool:
                pool.shutdown()


async def wait_for_execution(task: Any, active_timeout: float, confirmation_timeout: float, is_waiting: Any) -> bool:
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
            {task},
            timeout=min(0.25, max(0.001, active_timeout - active), max(0.001, confirmation_timeout - waiting)),
        )
        now = time.monotonic()
        if paused:
            waiting += now - previous
        else:
            active += now - previous
        previous = now
        if active >= active_timeout or waiting >= confirmation_timeout:
            return task.done()
    return True
