"""Human-in-the-loop for a live harness agent's native permission requests and questions.

Claude Code and Codex ask before using a tool their native policy does not allow. Each request pauses
the Agno run with a tool that requires confirmation, as an Agno agent's confirmation tool does: the
paused run carries the request as a requirement, and the person confirms or rejects it in the chat.
A harness's own multiple-choice questions to the user pause the same way, as user feedback like Agno's
``ask_user`` tool, and the person's selections are the answer. Continuing the run delivers that
decision to the same native execution, which is still waiting for it, so a decision never starts or
replays a turn.

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
from agno.tools.function import UserFeedbackOption, UserFeedbackQuestion
from agno.run.agent import RunContinuedEvent, RunPausedEvent
from agno.run.base import RunStatus
from agno.run.cancel import araise_if_cancelled
from agno.run.requirement import RunRequirement

_current: ContextVar[Optional["HITLBridge"]] = ContextVar("harness_hitl", default=None)
# Run metadata key holding the native human-in-the-loop state.
KEY = "native_hitl"


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


def hitl_state(run: Any) -> Dict[str, Any]:
    return dict((getattr(run, "metadata", None) or {}).get(KEY) or {})


def pending_ids(run: Any) -> List[str]:
    return list(hitl_state(run).get("pending") or [])


def awaiting_decision(run: Any) -> bool:
    """Whether the run is paused on a native request nobody has answered yet."""
    return run is not None and run.status == RunStatus.paused and bool(pending_ids(run))


def live_native_run(run: Any) -> bool:
    """Whether the run's native execution may still be live and waiting on people.

    A finished run keeps its HITL state as history; continuing it is an ordinary continuation.
    """
    return (
        run is not None
        and bool(hitl_state(run))
        and run.status not in (RunStatus.completed, RunStatus.cancelled, RunStatus.error)
    )


def active_bridge() -> Optional["HITLBridge"]:
    return _current.get()


def current_bridge() -> "HITLBridge":
    bridge = _current.get()
    if bridge is None:
        raise RuntimeError("Native human-in-the-loop requires an active Agno run")
    return bridge


def action_digest(value: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def feedback_questions(questions: List[Dict[str, Any]]) -> List[UserFeedbackQuestion]:
    """Agno user feedback questions for a harness's questions, as ``ask_user`` presents them."""
    return [
        UserFeedbackQuestion(
            question=q["question"],
            header=q.get("header"),
            options=[UserFeedbackOption(label=o["label"], description=o.get("description")) for o in q["options"]],
            multi_select=q.get("multi_select") is True,
        )
        for q in questions
    ]


def selected_answers(questions: List[UserFeedbackQuestion], supplied: Any) -> List[List[str]]:
    """Each question's selected options, in order, from the user feedback the chat sent back.

    A skipped question has no selections. Free text the person typed instead of an option is kept.
    """
    if not isinstance(supplied, list) or len(supplied) != len(questions):
        raise ValueError("Answer every question of the pending request to continue")
    answers = []
    for question, answer in zip(questions, supplied):
        if answer.question != question.question or answer.selected_options is None:
            raise ValueError("Answer every question of the pending request to continue")
        selected = answer.selected_options
        if (
            not isinstance(selected, list)
            or len(selected) > 32
            or not all(isinstance(value, str) and len(value) <= 4096 for value in selected)
        ):
            raise ValueError("Invalid answer to a native question")
        answers.append(list(selected))
    return answers


def apply_answers(tool: Any, requirement: Any, answers: List[List[str]]) -> None:
    for schema in (tool.user_feedback_schema, requirement.user_feedback_schema):
        for question, selected in zip(schema or [], answers):
            question.selected_options = selected
            for option in question.options or []:
                option.selected = option.label in selected
    tool.answered = True


def validate_native_hitl(agent: Any) -> None:
    if agent.db is None:
        raise ValueError("Native human-in-the-loop requires a database")
    if not math.isfinite(agent.hitl_timeout) or not 0 < agent.hitl_timeout <= 86400:
        raise ValueError("hitl_timeout must be between 0 and 86400 seconds")


class HITLBridge:
    """Turns a running harness's native permission requests and questions into paused-run requirements."""

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
        decision = await self._serialized(tool_name, arguments, native, None)
        return decision.get("confirmed") is True

    async def ask(
        self, tool_name: str, arguments: Dict[str, Any], native: Dict[str, Any], questions: List[Dict[str, Any]]
    ) -> List[List[str]]:
        """Pause the run for the harness's questions and return each one's selections, in order.

        ``questions`` are ``{"question", "header", "options": [{"label", "description"}], "multi_select"}``.
        A skipped question has no selections.
        """
        if not questions or len(questions) > 8:
            raise ValueError("A native question request needs between 1 and 8 questions")
        decision = await self._serialized(tool_name, arguments, native, questions)
        return decision["answers"]

    async def _serialized(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        native: Dict[str, Any],
        questions: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        if not self.allow_requests:
            raise ValueError("Native permission requests currently require a standalone Claude or Codex agent")
        async with self._lock:
            return await self._request(tool_name, arguments, native, questions)

    async def _request(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        native: Dict[str, Any],
        questions: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if self.closed:
            raise RuntimeError("The native execution is no longer available")
        # Bound both persisted and transported data before showing an action for review.
        action = {"tool_name": tool_name, "tool_args": arguments, "native": native}
        if len(json.dumps(action, allow_nan=False).encode()) > 65536:
            raise ValueError("Native permission request exceeds 64 KiB")
        tool_call_id = str(native.get("tool_call_id") or uuid4())
        if tool_call_id in self.requests:
            tool_call_id = f"{tool_call_id}:{uuid4().hex[:8]}"
        expires = time.time() + self.agent.hitl_timeout
        digest = action_digest(action)
        if questions is None:
            # An ordinary confirmation, answered in the chat like an Agno agent's confirmation tool.
            tool = ToolExecution(
                tool_call_id=tool_call_id, tool_name=tool_name, tool_args=arguments, requires_confirmation=True
            )
        else:
            # User feedback, answered in the chat like Agno's ask_user tool.
            tool = ToolExecution(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_args=arguments,
                requires_user_input=True,
                user_feedback_schema=feedback_questions(questions),
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
            external_agent_request={
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
                    raise TimeoutError("Native request expired before it was answered")
                run = await read_run(self.agent, self.run_id, self.session_id, self.user_id)
                if run is None or run.status == RunStatus.cancelled:
                    raise RuntimeError("The paused run is no longer available")
                decision = (hitl_state(run).get("decisions") or {}).get(tool_call_id)
                if decision and decision.get("digest") == digest and decision.get("owner") == self.owner:
                    if questions is None:
                        tool.confirmed = requirement.confirmation = decision.get("confirmed") is True
                    elif isinstance(decision.get("answers"), list):
                        apply_answers(tool, requirement, decision["answers"])
                    else:
                        raise ValueError("The decision does not answer this native question")
                    self.decisions[tool_call_id] = decision
                    self.pending = []
                    acknowledged = asyncio.Event()
                    await self.queue.put(
                        (
                            RunContinuedEvent(
                                run_id=self.run_id,
                                session_id=self.session_id,
                                agent_id=self.agent.get_id(),
                                external_agent_request_id=tool_call_id,
                            ),
                            acknowledged,
                        )
                    )
                    await asyncio.wait_for(acknowledged.wait(), max(0.001, expires - time.time()))
                    await araise_if_cancelled(self.run_id)
                    return decision
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
    """Record the chat's decision for every pending native request of a paused run.

    ``tools`` are the paused run's tools as the chat returns them: ``confirmed`` set on each pending
    confirmation, or ``selected_options`` on each question of pending user feedback. Tools that are not
    pending, such as earlier tool calls, are ignored. Each decision must match the reviewed action
    exactly. The waiting native execution reads the decision and continues.
    """
    run = await read_run(agent, run_id, session_id, user_id)
    if run is None:
        raise ValueError("Paused native run not found")
    if run.status != RunStatus.paused:
        raise ValueError("Run is not waiting for a native request")
    state = hitl_state(run)
    pending = list(state.get("pending") or [])
    if not pending:
        raise ValueError("Run has no pending native request")
    supplied = {t.tool_call_id: t for t in tools or [] if getattr(t, "tool_call_id", None)}
    reviewed = {r.tool_execution.tool_call_id: r for r in run.requirements or [] if r.tool_execution is not None}
    decisions = dict(state.get("decisions") or {})
    for tool_call_id in pending:
        request = (state.get("requests") or {}).get(tool_call_id)
        requirement = reviewed.get(tool_call_id)
        if request is None or requirement is None:
            raise ValueError("Native request is missing from the paused run")
        if request.get("expires_at", 0) <= time.time():
            raise ValueError("Native request has expired")
        tool = requirement.tool_execution
        assert tool is not None
        if request.get("digest") != action_digest(
            {"tool_name": tool.tool_name, "tool_args": tool.tool_args, "native": request.get("native")}
        ):
            raise ValueError("Native request does not match its recorded action")
        candidate = supplied.get(tool_call_id)
        if tool.user_feedback_schema:
            if candidate is None:
                raise ValueError(f"Answer the pending '{tool.tool_name}' questions to continue")
        elif candidate is None or candidate.confirmed is None:
            raise ValueError(f"Confirm or reject the pending '{tool.tool_name}' request to continue")
        if candidate.tool_name != tool.tool_name or candidate.tool_args != tool.tool_args:
            raise ValueError("Continuation does not match the reviewed native action")
        decision: Dict[str, Any] = {"digest": request["digest"], "owner": state.get("owner")}
        if tool.user_feedback_schema:
            decision["answers"] = selected_answers(tool.user_feedback_schema, candidate.user_feedback_schema)
            apply_answers(tool, requirement, decision["answers"])
        else:
            decision["confirmed"] = candidate.confirmed is True
            tool.confirmed = requirement.confirmation = decision["confirmed"]
        decisions[tool_call_id] = decision
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
    digest: str,
    owner: str,
    confirmed: Optional[bool] = None,
    answers: Optional[List[List[str]]] = None,
) -> bool:
    """Record one decision a coordinator delivers to a sandbox runtime's paused run.

    The decision is ``confirmed`` for a confirmation, or ``answers`` for user feedback. The coordinator
    delivers a decision a continuation already validated on the host; this checks it still answers the
    exact pending request. A repeated delivery of the same decision is accepted.
    """
    run = await read_run(agent, run_id, session_id, user_id)
    if run is None:
        raise ValueError("Unknown paused native run")
    state = hitl_state(run)
    decision: Dict[str, Any] = {"digest": digest, "owner": owner}
    if answers is not None:
        decision["answers"] = answers
    else:
        decision["confirmed"] = confirmed is True
    existing = (state.get("decisions") or {}).get(tool_call_id)
    if existing is not None:
        return existing == decision
    request = (state.get("requests") or {}).get(tool_call_id)
    if run.status != RunStatus.paused or tool_call_id not in (state.get("pending") or []) or request is None:
        raise ValueError("The native request is not waiting for a decision")
    if request.get("digest") != digest or state.get("owner") != owner:
        raise ValueError("The decision does not answer this native request")
    if request.get("expires_at", 0) <= time.time():
        raise ValueError("Native request has expired")
    for requirement in run.requirements or []:
        tool = requirement.tool_execution
        if tool is None or tool.tool_call_id != tool_call_id:
            continue
        if bool(tool.user_feedback_schema) != (answers is not None):
            raise ValueError("The decision does not answer this native request")
        if answers is not None:
            if len(answers) != len(tool.user_feedback_schema or []):
                raise ValueError("The decision does not answer this native question")
            apply_answers(tool, requirement, answers)
        else:
            tool.confirmed = requirement.confirmation = decision["confirmed"]
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
    answered = set(hitl_state(before).get("decisions") or {})
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
    deadline = time.monotonic() + agent.hitl_timeout
    submitted = answered
    while time.monotonic() < deadline:
        run = await read_run(agent, run_id, session_id, user_id)
        if run is None:
            raise ValueError("Paused native run is no longer available")
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
        await asyncio.sleep(min(1.0, max(0.001, agent.hitl_timeout / 10)))
    raise TimeoutError("Native continuation timed out; inspect the persisted run")


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
        raise ValueError("Continuing a native request only delivers its decision")
    run_id = run_id or getattr(run_response, "run_id", None)
    session_id = session_id or getattr(run_response, "session_id", None)
    if not run_id or not session_id:
        raise ValueError("Native continuation requires run_id and session_id")
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
        raise RuntimeError("Native continuation returned no run")

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


async def wait_for_execution(task: Any, active_timeout: float, hitl_timeout: float, is_waiting: Any) -> bool:
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
            timeout=min(0.25, max(0.001, active_timeout - active), max(0.001, hitl_timeout - waiting)),
        )
        now = time.monotonic()
        if paused:
            waiting += now - previous
        else:
            active += now - previous
        previous = now
        if active >= active_timeout or waiting >= hitl_timeout:
            return task.done()
    return True
