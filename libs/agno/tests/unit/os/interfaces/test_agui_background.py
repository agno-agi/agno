"""Resumable background runs over the AG-UI interface.

The contract under test: a background AG-UI run keeps executing after the
client goes away, and a reconnecting client receives every AG-UI event exactly
once, in the same order, with the same payloads it would have seen on an
uninterrupted connection. The last section drives the real route, where the
decision to run detached at all is made.
"""

import asyncio
import contextlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import BaseEvent, EventType
from fastapi.testclient import TestClient

from agno.agent import Agent, RemoteAgent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse, ToolExecution
from agno.os.app import AgentOS
from agno.os.event_streams import get_event_stream, set_event_stream
from agno.os.event_streams.base import BaseEventStream
from agno.os.event_streams.in_memory import InMemoryEventStream
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.agui import background as background_module
from agno.os.interfaces.agui.background import (
    background_cursor,
    background_requested,
    run_entity_background,
    supports_background,
)
from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.os.utils import format_sse_event_with_index
from agno.reasoning.step import ReasoningStep
from agno.run.agent import (
    ReasoningCompletedEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.base import RunStatus
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.team.remote import RemoteTeam

# ---------------------------------------------------------------------------
# Fixtures and doubles
# ---------------------------------------------------------------------------

TERMINAL_STATUSES = (RunStatus.completed, RunStatus.error, RunStatus.cancelled, RunStatus.paused)

# Long enough that a loaded machine still gets there, short enough that a
# condition which never arrives fails the test instead of hanging the suite.
CONDITION_TIMEOUT_SECONDS = 10.0
# Real time between polls: a zero sleep hands control back without letting the
# clock move, so a budget spent in polls is no budget at all.
POLL_SECONDS = 0.005


def fresh_event_stream(max_events_per_run: int = 1000) -> InMemoryEventStream:
    """Install an empty event stream so a run id can be reused from scratch."""
    stream = InMemoryEventStream(
        events_buffer=EventsBuffer(max_events_per_run=max_events_per_run),
        subscriber_manager=SSESubscriberManager(),
    )
    set_event_stream(stream)
    return stream


@pytest.fixture(autouse=True)
def isolated_event_stream():
    """Each test gets its own buffer and module state, so run ids never collide."""
    original = get_event_stream()
    # The drain task set is deliberately not touched: it holds the only strong
    # reference keeping a live background run from being collected.
    background_module._STARTED_RUNS.clear()
    background_module._STARTING_RUNS.clear()
    try:
        yield fresh_event_stream()
    finally:
        set_event_stream(original)
        background_module._STARTED_RUNS.clear()
        background_module._STARTING_RUNS.clear()


class FakeRunInput:
    def __init__(
        self,
        *,
        thread_id: str = "thread-1",
        run_id: str = "run-1",
        forwarded_props: Optional[Dict[str, Any]] = None,
        state: Any = None,
        messages: Optional[List[Any]] = None,
        tools: Optional[List[Any]] = None,
        context: Optional[List[Any]] = None,
    ):
        self.thread_id = thread_id
        self.run_id = run_id
        self.forwarded_props = forwarded_props
        self.state = state
        self.messages = messages if messages is not None else [_user_message("hello")]
        self.tools = tools or []
        self.context = context or []


@dataclass
class _FakeMessage:
    id: str
    role: str
    content: str
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Any]] = None
    name: Optional[str] = None


def _user_message(text: str) -> _FakeMessage:
    return _FakeMessage(id="m1", role="user", content=text)


class ScriptedEntity:
    """Stands in for an Agent or Team running detached in the background.

    ``arun(background=True, stream=True)`` mirrors what Agno's background
    producer does: it appends each event to the event stream (which owns index
    assignment) and yields the SSE string for the originating connection.

    ``final_status`` is the status the producer leaves behind, so a script that
    carries no terminal event plus an error status reproduces a producer that
    died mid run.
    """

    def __init__(
        self,
        events: List[Any],
        *,
        db: Any = "db",
        pause_after: Optional[int] = None,
        final_status: RunStatus = RunStatus.completed,
    ):
        self.events = events
        self.db = db
        self.final_status = final_status
        self.arun_kwargs: Dict[str, Any] = {}
        self.arun_calls = 0
        self._pause_after = pause_after
        self._gate = asyncio.Event()
        self.started = asyncio.Event()

    def release(self) -> None:
        self._gate.set()

    def arun(self, **kwargs):
        self.arun_calls += 1
        self.arun_kwargs = kwargs
        run_id = kwargs["run_id"]

        async def _produce() -> AsyncIterator[str]:
            stream = get_event_stream()
            await stream.register_run(run_id, RunStatus.pending)
            await stream.set_run_status(run_id, RunStatus.running)
            self.started.set()
            try:
                for position, event in enumerate(self.events):
                    if self._pause_after is not None and position == self._pause_after:
                        await self._gate.wait()
                    index = await stream.add_event(run_id, event)
                    yield format_sse_event_with_index(event, event_index=index, run_id=run_id)
            finally:
                await stream.complete_run(run_id, self.final_status)

        return _produce()

    async def aget_run_output(self, run_id: str, session_id: Optional[str] = None, user_id: Optional[str] = None):
        return object()


class ForeignRunEntity(ScriptedEntity):
    """A run the caller's session does not own."""

    async def aget_run_output(self, run_id: str, session_id: Optional[str] = None, user_id: Optional[str] = None):
        return None


class UnreadableRunEntity(ScriptedEntity):
    """An entity whose run rows cannot be read: a storage failure, not a denial."""

    async def aget_run_output(self, run_id: str, session_id: Optional[str] = None, user_id: Optional[str] = None):
        raise RuntimeError("run store unavailable")


class NoRunOutputEntity(ScriptedEntity):
    """An entity that cannot read its own run rows back, so ownership is unverifiable."""

    aget_run_output = None


class UnstartableEntity(ScriptedEntity):
    """An entity that refuses to start, after the run has already been registered."""

    def arun(self, **kwargs):
        self.arun_calls += 1
        raise RuntimeError("no capacity for another run")


class DyingProducerEntity(ScriptedEntity):
    """A producer that raises part way through without ending its own run.

    Unlike ``ScriptedEntity`` it leaves no terminal status behind, so the only
    thing that can end the run for an attached client is the drain's own
    failure path.
    """

    def arun(self, **kwargs):
        self.arun_calls += 1
        self.arun_kwargs = kwargs
        run_id = kwargs["run_id"]

        async def _produce() -> AsyncIterator[str]:
            stream = get_event_stream()
            await stream.register_run(run_id, RunStatus.pending)
            await stream.set_run_status(run_id, RunStatus.running)
            self.started.set()
            for event in self.events:
                index = await stream.add_event(run_id, event)
                yield format_sse_event_with_index(event, event_index=index, run_id=run_id)
            raise RuntimeError("the producer died mid run")

        return _produce()


class UnmappedEvent:
    """A buffered event whose wire name no Agno event class claims."""

    event = "AnEventTypeAgnoDoesNotKnow"

    def __init__(self, payload: str):
        self.payload = payload

    def to_dict(self) -> Dict[str, Any]:
        return {"event": self.event, "payload": self.payload}


class _DelegatingEventStream(BaseEventStream):
    """Forwards the stream interface to a wrapped one so subclasses override just one.

    reopen_run is left to the base class, which no background run reaches.
    """

    def __init__(self, inner: BaseEventStream):
        self._inner = inner

    async def register_run(self, run_id: str, status: RunStatus = RunStatus.pending) -> None:
        await self._inner.register_run(run_id, status)

    async def set_run_status(self, run_id: str, status: RunStatus, generation: Optional[int] = None) -> None:
        await self._inner.set_run_status(run_id, status, generation)

    async def get_run_status(self, run_id: str) -> Optional[RunStatus]:
        return await self._inner.get_run_status(run_id)

    async def complete_run(self, run_id: str, status: RunStatus, generation: Optional[int] = None) -> None:
        await self._inner.complete_run(run_id, status, generation)

    async def begin_attempt(self, run_id: str, generation: int) -> None:
        await self._inner.begin_attempt(run_id, generation)

    async def cleanup_run(self, run_id: str) -> None:
        await self._inner.cleanup_run(run_id)

    async def reset_run_events(self, run_id: str, generation: Optional[int] = None) -> None:
        await self._inner.reset_run_events(run_id, generation)

    async def add_event(self, run_id: str, event: Any, generation: Optional[int] = None) -> int:
        return await self._inner.add_event(run_id, event, generation)

    async def replay(self, run_id: str, last_event_index: Optional[int] = None) -> List[Tuple[int, Any]]:
        return await self._inner.replay(run_id, last_event_index)

    async def get_last_index(self, run_id: str) -> int:
        return await self._inner.get_last_index(run_id)

    async def get_event_count(self, run_id: str) -> int:
        return await self._inner.get_event_count(run_id)

    def tail(self, run_id: str, last_event_index: Optional[int] = None) -> AsyncIterator[Tuple[int, str]]:
        return self._inner.tail(run_id, last_event_index)


class SseOnlyEventStream(_DelegatingEventStream):
    """A durable-shaped stream: nothing but SSE strings crosses the boundary.

    Redis-backed streams behave this way. ``tail`` is built here from this
    class's own ``replay`` plus a status poll instead of borrowing the
    in-memory live tail, so a translation that secretly depended on the
    in-memory stream handing back event objects fails against it.
    """

    # How long the tail may sit idle on a run that is still going. Reaching it
    # raises rather than returning: a tail that closes quietly leaves the
    # translation reporting a truncated run as a whole one, which is exactly
    # the failure this double exists to catch.
    _IDLE_TIMEOUT_SECONDS = CONDITION_TIMEOUT_SECONDS

    def __init__(self, inner: BaseEventStream):
        super().__init__(inner)
        self.replay_calls = 0
        self.tail_calls = 0

    async def replay(self, run_id: str, last_event_index: Optional[int] = None) -> List[Tuple[int, Any]]:
        self.replay_calls += 1
        return [
            (index, format_sse_event_with_index(event, event_index=index, run_id=run_id))
            for index, event in await self._inner.replay(run_id, last_event_index)
        ]

    async def tail(self, run_id: str, last_event_index: Optional[int] = None) -> AsyncIterator[Tuple[int, str]]:
        self.tail_calls += 1
        loop = asyncio.get_running_loop()
        last = last_event_index if last_event_index is not None else -1
        idle_since = loop.time()
        while True:
            delivered = False
            for index, frame in await self.replay(run_id, last):
                delivered = True
                last = max(last, index)
                yield index, frame
            status = await self.get_run_status(run_id)
            if status in TERMINAL_STATUSES:
                # Whatever landed between that replay and the status read is
                # still owed to this tail before it may close.
                for index, frame in await self.replay(run_id, last):
                    last = max(last, index)
                    yield index, frame
                return
            if status is None:
                # The registration is gone, so no producer will write again.
                return
            if delivered:
                idle_since = loop.time()
            elif loop.time() - idle_since > self._IDLE_TIMEOUT_SECONDS:
                raise AssertionError(
                    f"the durable tail for run {run_id} produced nothing for "
                    f"{self._IDLE_TIMEOUT_SECONDS}s while its status was still {status}"
                )
            await asyncio.sleep(POLL_SECONDS)


class GatedRegistrationStream(_DelegatingEventStream):
    """Holds the first connection inside ``register_run``.

    A connection claims a new run id before it registers it, and only a second
    connection landing inside that window takes the wait-for-registration
    path. Nothing in that window suspends on its own, so two connections
    started together never interleave there: this gate opens the window and
    counts the status reads that prove the second one went through it.
    """

    def __init__(self, inner: BaseEventStream):
        super().__init__(inner)
        self.registering = asyncio.Event()
        self.release = asyncio.Event()
        self.status_reads = 0

    async def get_run_status(self, run_id: str) -> Optional[RunStatus]:
        self.status_reads += 1
        return await self._inner.get_run_status(run_id)

    async def register_run(self, run_id: str, status: RunStatus = RunStatus.pending) -> None:
        self.registering.set()
        await self.release.wait()
        await self._inner.register_run(run_id, status)


class InjectedFrameStream(_DelegatingEventStream):
    """Splices extra frames into an otherwise real tail.

    Each injected frame carries the index of the event it precedes, so a frame
    the parser skips must not shift the cursor of anything that follows it.
    """

    def __init__(self, inner: BaseEventStream, frames_before: Dict[int, List[str]]):
        super().__init__(inner)
        self._frames_before = frames_before

    async def tail(self, run_id: str, last_event_index: Optional[int] = None) -> AsyncIterator[Tuple[int, str]]:
        async for index, frame in self._inner.tail(run_id, last_event_index):
            for injected in self._frames_before.get(index, []):
                yield index, injected
            yield index, frame


class BreakingTailStream(_DelegatingEventStream):
    """A tail that fails after handing over some of the run.

    The client keeps what it was given, so the error that ends the connection
    has to be positioned relative to that rather than to the start of the run.
    """

    def __init__(self, inner: BaseEventStream, fail_after: int):
        super().__init__(inner)
        self._fail_after = fail_after

    async def tail(self, run_id: str, last_event_index: Optional[int] = None) -> AsyncIterator[Tuple[int, str]]:
        handed_over = 0
        async for index, frame in self._inner.tail(run_id, last_event_index):
            yield index, frame
            handed_over += 1
            if handed_over >= self._fail_after:
                raise RuntimeError("the event stream broke mid run")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def background_props(cursor: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
    props: Dict[str, Any] = {"agnoBackground": {"enabled": True}}
    if cursor is not None:
        props["agnoBackground"]["lastEventIndex"] = cursor[0]
        props["agnoBackground"]["lastSubIndex"] = cursor[1]
    return props


def cursor_of(event: BaseEvent) -> Tuple[int, int]:
    marker = (event.metadata or {}).get("agnoBackground")
    assert marker is not None, f"{event.type} carries no background cursor: {event!r}"
    return marker["eventIndex"], marker["subIndex"]


# Wall-clock fields that never replay equal. ``created_at`` is nested rather
# than top level: a raw event and a run error both carry the source event's
# wire payload, so two separately built scripts differ across a second
# boundary unless it is stripped at every depth.
_VOLATILE_FIELDS = ("timestamp", "created_at")


def _without_volatile_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_volatile_fields(item) for key, item in value.items() if key not in _VOLATILE_FIELDS}
    if isinstance(value, list):
        return [_without_volatile_fields(item) for item in value]
    return value


def fingerprint(event: BaseEvent) -> str:
    """Payload identity, ignoring wall-clock fields that never replay equal."""
    data = _without_volatile_fields(event.model_dump(by_alias=True, exclude_none=True))
    return json.dumps(data, sort_keys=True, default=str)


def fingerprints(events: Iterable[BaseEvent]) -> List[str]:
    return [fingerprint(event) for event in events]


def assert_spans_are_well_formed(events: List[BaseEvent]) -> None:
    """Every content event belongs to a span that was opened and is later closed."""
    open_messages: List[str] = []
    open_tool_calls: List[str] = []
    for event in events:
        if event.type == EventType.TEXT_MESSAGE_START:
            assert event.message_id not in open_messages, f"a second start for message {event.message_id}"
            open_messages.append(event.message_id)
        elif event.type == EventType.TEXT_MESSAGE_CONTENT:
            assert event.message_id in open_messages, f"content for an unopened message {event.message_id}"
        elif event.type == EventType.TEXT_MESSAGE_END:
            assert event.message_id in open_messages, f"end for an unopened message {event.message_id}"
            open_messages.remove(event.message_id)
        elif event.type == EventType.TOOL_CALL_START:
            assert event.parent_message_id, "a tool call must parent to a message"
            assert event.tool_call_id not in open_tool_calls, f"a second start for call {event.tool_call_id}"
            open_tool_calls.append(event.tool_call_id)
        elif event.type in (EventType.TOOL_CALL_ARGS, EventType.TOOL_CALL_END):
            assert event.tool_call_id in open_tool_calls, f"args or end for an unstarted call {event.tool_call_id}"
            if event.type == EventType.TOOL_CALL_END:
                open_tool_calls.remove(event.tool_call_id)
    assert open_messages == []
    assert open_tool_calls == []


async def wait_until(predicate: Callable[[], bool], timeout: float = CONDITION_TIMEOUT_SECONDS) -> None:
    """Wait for a predicate to hold, giving the loop real time to get there."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "the awaited condition never became true"
        await asyncio.sleep(POLL_SECONDS)


async def collect(stream: AsyncIterator[BaseEvent], stop_after: Optional[int] = None) -> List[BaseEvent]:
    out: List[BaseEvent] = []
    async for event in stream:
        out.append(event)
        if stop_after is not None and len(out) >= stop_after:
            await stream.aclose()
            break
    return out


TOOL = ToolExecution(tool_call_id="call-1", tool_name="add", tool_args={"a": 1, "b": 2}, result="3")


def reasoning_script() -> List[Any]:
    return [
        ReasoningStartedEvent(),
        ReasoningStepEvent(
            content=ReasoningStep(title="weigh it up", reasoning="because of the numbers"),
            reasoning_content="because of the numbers",
        ),
        ReasoningCompletedEvent(),
        RunContentEvent(content="four"),
        RunCompletedEvent(content="four"),
    ]


def agent_script() -> List[Any]:
    return [
        RunStartedEvent(),
        RunContentEvent(content="Hel"),
        ToolCallStartedEvent(tool=TOOL),
        ToolCallCompletedEvent(tool=TOOL),
        RunContentEvent(content="lo"),
        RunCompletedEvent(content="Hello", session_state={"counter": 1}),
    ]


# A buffer this small keeps only the last three events of ``agent_script``,
# which drops the tool call's start and keeps the event completing it. Sized
# one larger the start survives and the trimming exercises nothing.
TRIMMED_TO_AFTER_THE_TOOL_CALL_START = 3


def team_script() -> List[Any]:
    return [
        TeamRunContentEvent(content="team says"),
        TeamRunCompletedEvent(content="team says hi", session_state={"counter": 2}),
    ]


def member_completion_script() -> List[Any]:
    """A team run whose member completes and whose own terminal never arrives.

    The member's completion is an agent-level ``RunCompleted``, which is what
    makes the last completion in the buffer say the run succeeded whatever the
    run itself did.
    """
    return [TeamRunContentEvent(content="team says"), RunCompletedEvent(content="member done")]


def script_with_events_after_the_terminal() -> List[Any]:
    """A team run: the member completes, then the leader keeps talking."""
    return [
        TeamRunContentEvent(content="team says"),
        RunCompletedEvent(content="member done"),
        TeamRunContentEvent(content=" and stops"),
    ]


def dying_script() -> List[Any]:
    """A run that stops mid flight: no terminal event ever reaches the buffer."""
    return [RunStartedEvent(), RunContentEvent(content="Hel")]


# ---------------------------------------------------------------------------
# Opt-in parsing
# ---------------------------------------------------------------------------


class TestOptIn:
    def test_absent_forwarded_props_is_foreground(self):
        assert background_requested(FakeRunInput(forwarded_props=None)) is False

    def test_unrelated_forwarded_props_is_foreground(self):
        assert background_requested(FakeRunInput(forwarded_props={"user_id": "u1"})) is False

    def test_nested_enabled_flag_opts_in(self):
        assert background_requested(FakeRunInput(forwarded_props=background_props())) is True

    def test_bare_true_opts_in(self):
        assert background_requested(FakeRunInput(forwarded_props={"agnoBackground": True})) is True

    def test_explicit_false_stays_foreground(self):
        assert background_requested(FakeRunInput(forwarded_props={"agnoBackground": {"enabled": False}})) is False

    def test_cursor_is_none_on_a_first_connection(self):
        assert background_cursor(FakeRunInput(forwarded_props=background_props())) is None

    def test_cursor_round_trips(self):
        assert background_cursor(FakeRunInput(forwarded_props=background_props((4, 1)))) == (4, 1)

    def test_the_very_first_cursor_is_readable(self):
        assert background_cursor(FakeRunInput(forwarded_props=background_props((0, 0)))) == (0, 0)

    def test_a_missing_sub_index_means_the_first_event_of_that_group(self):
        props = {"agnoBackground": {"enabled": True, "lastEventIndex": 3}}
        assert background_cursor(FakeRunInput(forwarded_props=props)) == (3, 0)

    @pytest.mark.parametrize(
        "position",
        [
            {"lastEventIndex": "4"},
            {"lastEventIndex": 4.5},
            {"lastEventIndex": None},
            # A JSON true is an int subclass in Python, so without a guard it
            # would resume from index 1 rather than be rejected.
            {"lastEventIndex": True},
            {"lastEventIndex": 4, "lastSubIndex": "1"},
            {"lastEventIndex": 4, "lastSubIndex": False},
        ],
    )
    def test_an_unreadable_resume_position_is_rejected(self, position):
        props = {"agnoBackground": {"enabled": True, **position}}
        with pytest.raises(ValueError, match="Unreadable background resume position"):
            background_cursor(FakeRunInput(forwarded_props=props))


# ---------------------------------------------------------------------------
# Which entities may run detached
# ---------------------------------------------------------------------------


class TestSupportsBackground:
    def test_a_remote_agent_is_refused(self):
        """A remote agent's events land in another process, so none of them replay here."""
        assert supports_background(RemoteAgent(base_url="http://localhost:1", agent_id="remote-agent")) is False

    def test_a_remote_team_is_refused(self):
        assert supports_background(RemoteTeam(base_url="http://localhost:1", team_id="remote-team")) is False

    def test_an_entity_without_a_database_is_refused(self):
        """Detached execution needs somewhere to persist run status."""
        assert supports_background(ScriptedEntity(agent_script(), db=None)) is False

    def test_an_entity_that_cannot_read_run_output_is_refused(self):
        """Without a run reader the ownership of a resumed run cannot be checked."""
        assert supports_background(NoRunOutputEntity(agent_script())) is False

    def test_an_in_process_entity_with_a_database_is_accepted(self):
        assert supports_background(ScriptedEntity(agent_script())) is True


# ---------------------------------------------------------------------------
# Starting a background run
# ---------------------------------------------------------------------------


class TestBackgroundStart:
    @pytest.mark.asyncio
    async def test_detached_execution_is_requested(self):
        entity = ScriptedEntity(agent_script())
        run_input = FakeRunInput(forwarded_props=background_props())

        await collect(run_entity_background(entity, run_input))

        assert entity.arun_kwargs.get("background") is True
        assert entity.arun_kwargs.get("stream") is True
        assert entity.arun_kwargs.get("stream_events") is True
        assert entity.arun_kwargs.get("run_id") == "run-1"
        assert entity.arun_kwargs.get("session_id") == "thread-1"

    @pytest.mark.asyncio
    async def test_canonical_agent_sequence(self):
        entity = ScriptedEntity(agent_script())
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        types = [event.type for event in events]
        assert types[0] == EventType.RUN_STARTED
        assert types[-1] == EventType.RUN_FINISHED
        assert EventType.TEXT_MESSAGE_START in types
        assert EventType.TOOL_CALL_START in types
        assert EventType.TOOL_CALL_ARGS in types
        assert EventType.TOOL_CALL_END in types
        assert EventType.TOOL_CALL_RESULT in types
        assert_spans_are_well_formed(events)

    @pytest.mark.asyncio
    async def test_every_event_carries_a_monotonic_cursor(self):
        entity = ScriptedEntity(agent_script())
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        cursors = [cursor_of(event) for event in events]
        assert cursors == sorted(cursors)
        assert len(set(cursors)) == len(cursors)

    @pytest.mark.asyncio
    async def test_tool_call_result_payload_survives(self):
        entity = ScriptedEntity(agent_script())
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        results = [event for event in events if event.type == EventType.TOOL_CALL_RESULT]
        assert [(event.tool_call_id, event.content) for event in results] == [("call-1", "3")]

    @pytest.mark.asyncio
    async def test_team_background_run(self):
        entity = ScriptedEntity(team_script())
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        contents = [event.delta for event in events if event.type == EventType.TEXT_MESSAGE_CONTENT]
        assert contents == ["team says"]
        assert events[-1].type == EventType.RUN_FINISHED

    @pytest.mark.asyncio
    async def test_state_snapshots_bracket_the_run(self):
        entity = ScriptedEntity(agent_script())
        run_input = FakeRunInput(forwarded_props=background_props(), state={"counter": 0})
        events = await collect(run_entity_background(entity, run_input))

        snapshots = [event.snapshot for event in events if event.type == EventType.STATE_SNAPSHOT]
        assert snapshots == [{"counter": 0}, {"counter": 1}]

    @pytest.mark.asyncio
    async def test_state_is_reported_the_way_a_foreground_run_reports_it(self):
        """A background run invents no state for a request that sent none.

        A request that sends state is bracketed by an opening and a closing
        snapshot; one that sends none gets neither, which is what the same run
        would do streaming inline. A client that keeps sending state the same
        way therefore sees the same event positions on every connection.
        """
        with_state = await collect(
            run_entity_background(
                ScriptedEntity(agent_script()),
                FakeRunInput(forwarded_props=background_props(), state={"counter": 0}),
            )
        )

        fresh_event_stream()
        resumed_with_state = await collect(
            run_entity_background(
                ScriptedEntity(agent_script()),
                FakeRunInput(forwarded_props=background_props(), state={"counter": 0}),
            )
        )

        fresh_event_stream()
        without_state = await collect(
            run_entity_background(ScriptedEntity(agent_script()), FakeRunInput(forwarded_props=background_props()))
        )

        assert [event.snapshot for event in with_state if event.type == EventType.STATE_SNAPSHOT] == [
            {"counter": 0},
            {"counter": 1},
        ]
        assert [event.type for event in without_state if event.type == EventType.STATE_SNAPSHOT] == []
        assert fingerprints(with_state) == fingerprints(resumed_with_state)
        assert with_state[-1].type == EventType.RUN_FINISHED
        assert without_state[-1].type == EventType.RUN_FINISHED

    @pytest.mark.asyncio
    async def test_error_terminal_is_preserved(self):
        entity = ScriptedEntity([RunStartedEvent(), RunErrorEvent(content="boom")])
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        assert events[-1].type == EventType.RUN_ERROR
        assert events[-1].message == "boom"


# ---------------------------------------------------------------------------
# Translating buffered frames
# ---------------------------------------------------------------------------


UNREADABLE_FRAMES = [
    "event: RunContent\n\n",
    "event: RunContent\ndata: {not json at all}\n\n",
    'event: RunContent\ndata: {"content": "names no event"}\n\n',
]

# U+2028 is a line terminator to str.splitlines but a legal character inside a
# JSON string, so a frame carrying one must not be split on it.
LINE_SEPARATOR_TEXT = "before\u2028after"


class TestFrameTranslation:
    @pytest.mark.asyncio
    async def test_a_reasoning_step_survives_the_trip_through_the_buffer(self):
        """A reasoning step is serialized to a plain mapping on its way into the
        buffer, and reading it back as one is what keeps the run alive."""
        entity = ScriptedEntity(reasoning_script())
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        contents = [event.delta for event in events if event.type == EventType.REASONING_MESSAGE_CONTENT]
        assert contents == ["## Step 1: weigh it up\nbecause of the numbers\n\n"]
        assert events[-1].type == EventType.RUN_FINISHED
        assert_spans_are_well_formed(events)

    @pytest.mark.asyncio
    async def test_an_unmapped_event_arrives_as_a_raw_event(self):
        """An event with no Agno class is forwarded raw, as the foreground path does.

        Dropping it would lose a custom event on every reconnect while the same
        run had delivered it on a first connection. The payload is the event's
        own, down to the field: the index the buffer stamps onto the frame is
        the buffer's bookkeeping and belongs in the resume marker rather than
        inside an event a client is asked to interpret.
        """
        entity = ScriptedEntity([UnmappedEvent("keep me"), RunCompletedEvent(content="done")])
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        assert [event.type for event in events] == [
            EventType.RUN_STARTED,
            EventType.RAW,
            EventType.RUN_FINISHED,
        ]
        raw = events[1]
        assert raw.source == "agno"
        assert raw.event == {"event": UnmappedEvent.event, "payload": "keep me", "run_id": "run-1"}
        assert cursor_of(raw) == (0, 0)

    @pytest.mark.asyncio
    async def test_unreadable_frames_are_skipped_without_ending_the_stream(self):
        """A frame with no data, bad JSON, or no event name is dropped, not fatal."""
        baseline = await collect(
            run_entity_background(ScriptedEntity(agent_script()), FakeRunInput(forwarded_props=background_props()))
        )

        inner = fresh_event_stream()
        set_event_stream(InjectedFrameStream(inner, {index: UNREADABLE_FRAMES for index in range(len(agent_script()))}))
        events = await collect(
            run_entity_background(ScriptedEntity(agent_script()), FakeRunInput(forwarded_props=background_props()))
        )

        assert fingerprints(events) == fingerprints(baseline)
        assert [cursor_of(event) for event in events] == [cursor_of(event) for event in baseline]

    @pytest.mark.asyncio
    async def test_a_unicode_line_separator_inside_a_frame_still_decodes(self):
        entity = ScriptedEntity(
            [RunContentEvent(content=LINE_SEPARATOR_TEXT), RunCompletedEvent(content=LINE_SEPARATOR_TEXT)]
        )
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        deltas = [event.delta for event in events if event.type == EventType.TEXT_MESSAGE_CONTENT]
        assert deltas == [LINE_SEPARATOR_TEXT]
        assert events[-1].type == EventType.RUN_FINISHED


# ---------------------------------------------------------------------------
# Terminal events
# ---------------------------------------------------------------------------


class TestTerminalEvents:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [RunStatus.error, RunStatus.cancelled, RunStatus.paused])
    async def test_a_tail_that_ends_badly_reports_the_runs_own_status(self, status):
        """No terminal event in the buffer: the run's status decides how it ended.

        Synthesizing a RUN_FINISHED here would tell the client a run succeeded
        that in fact died, was cancelled, or is sitting paused with nothing in
        the buffer to say so.
        """
        entity = ScriptedEntity(dying_script(), final_status=status)
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        assert [event.type for event in events] == [
            EventType.RUN_STARTED,
            EventType.RAW,
            EventType.TEXT_MESSAGE_START,
            EventType.TEXT_MESSAGE_CONTENT,
            EventType.TEXT_MESSAGE_END,
            EventType.RUN_ERROR,
        ]
        assert events[-1].message == f"Run ended without a result, last known status {status.value.lower()}"
        assert_spans_are_well_formed(events)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [RunStatus.error, RunStatus.cancelled])
    async def test_a_held_member_completion_does_not_report_a_failed_run_as_a_success(self, status):
        """A completion belonging to a member may not end the run happily.

        A team run buffers each member's completion before its own, so the
        last completion the buffer holds can be a member's while the run
        itself died or was cancelled. The run's status decides how the client
        is told it ended.
        """
        entity = ScriptedEntity(member_completion_script(), final_status=status)
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        assert [event.type for event in events] == [
            EventType.RUN_STARTED,
            EventType.TEXT_MESSAGE_START,
            EventType.TEXT_MESSAGE_CONTENT,
            EventType.TEXT_MESSAGE_END,
            EventType.RUN_ERROR,
        ]
        assert events[-1].message == f"Run ended without a result, last known status {status.value.lower()}"
        assert [event.delta for event in events if event.type == EventType.TEXT_MESSAGE_CONTENT] == ["team says"]
        assert_spans_are_well_formed(events)

    @pytest.mark.asyncio
    async def test_a_held_member_completion_ends_the_run_when_the_status_agrees(self):
        """The status overrides a held completion only when it contradicts one."""
        entity = ScriptedEntity(member_completion_script(), final_status=RunStatus.completed)
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        assert [event.type for event in events] == [
            EventType.RUN_STARTED,
            EventType.TEXT_MESSAGE_START,
            EventType.TEXT_MESSAGE_CONTENT,
            EventType.TEXT_MESSAGE_END,
            EventType.RUN_FINISHED,
        ]
        assert_spans_are_well_formed(events)

    @pytest.mark.asyncio
    async def test_the_terminal_group_lands_after_everything_the_buffer_holds(self):
        """A terminal with events buffered behind it is still emitted last.

        Its own index is already behind theirs, and keeping it would hand two
        AG-UI events one address, so the whole terminal group moves past the
        highest index the tail saw.
        """
        entity = ScriptedEntity(script_with_events_after_the_terminal())
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        assert [event.type for event in events] == [
            EventType.RUN_STARTED,
            EventType.TEXT_MESSAGE_START,
            EventType.TEXT_MESSAGE_CONTENT,
            EventType.TEXT_MESSAGE_CONTENT,
            EventType.TEXT_MESSAGE_END,
            EventType.RUN_FINISHED,
        ]
        assert [event.delta for event in events if event.type == EventType.TEXT_MESSAGE_CONTENT] == [
            "team says",
            " and stops",
        ]
        terminal_group = [cursor_of(event) for event in events[-2:]]
        assert terminal_group == [(3, 0), (3, 1)]
        assert min(terminal_group) > max(cursor_of(event) for event in events[:-2])
        assert_spans_are_well_formed(events)

    @pytest.mark.asyncio
    async def test_a_producer_that_dies_mid_run_still_ends_the_clients_stream(self):
        """A run whose producer raises is marked errored, so nobody waits on it.

        The buffer holds no terminal event and the producer is gone, so
        without the drain reporting the failure the client would sit through
        the stream's idle recheck and then be told the run succeeded.
        """
        entity = DyingProducerEntity(dying_script())
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        assert [event.type for event in events] == [
            EventType.RUN_STARTED,
            EventType.RAW,
            EventType.TEXT_MESSAGE_START,
            EventType.TEXT_MESSAGE_CONTENT,
            EventType.TEXT_MESSAGE_END,
            EventType.RUN_ERROR,
        ]
        assert events[-1].message == f"Run ended without a result, last known status {RunStatus.error.value.lower()}"
        assert await get_event_stream().get_run_status("run-1") == RunStatus.error
        assert_spans_are_well_formed(events)

    @pytest.mark.asyncio
    async def test_a_mid_stream_failure_ends_above_everything_already_delivered(self):
        """A stream that breaks part way through still terminates, past what it sent.

        The client keeps what it received, so the error ending the connection
        has to sit above all of it: one that did not would be dropped by a
        client filtering by cursor, which would then reconnect into it.
        """
        set_event_stream(BreakingTailStream(get_event_stream(), fail_after=2))
        entity = ScriptedEntity(agent_script())

        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        assert [event.type for event in events] == [
            EventType.RUN_STARTED,
            EventType.RAW,
            EventType.TEXT_MESSAGE_START,
            EventType.TEXT_MESSAGE_CONTENT,
            EventType.RUN_ERROR,
        ]
        assert events[-1].message == "the event stream broke mid run"
        delivered = [cursor_of(event) for event in events[:-1]]
        assert delivered == [(-1, 0), (0, 0), (1, 0), (1, 1)]
        assert cursor_of(events[-1]) > max(delivered)

    @pytest.mark.asyncio
    async def test_a_synthesized_terminal_is_never_filtered_out_by_a_cursor(self):
        """A client echoing the terminal cursor still receives a terminal event.

        Filtering the run's end away would leave that client holding a
        connection that will never say anything again, so the terminal is
        re-issued past whatever position the client sent. Only the terminal:
        the span-closing events beside it in that group were already
        delivered, and re-issuing one would end a message this leg never
        opened.
        """
        entity = ScriptedEntity(dying_script(), final_status=RunStatus.error)
        baseline = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))
        assert baseline[-2].type == EventType.TEXT_MESSAGE_END
        held = cursor_of(baseline[-1])

        resumed = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props(held))))

        assert [event.type for event in resumed] == [EventType.RUN_ERROR]
        assert resumed[-1].message == baseline[-1].message
        assert cursor_of(resumed[-1]) > held
        assert_spans_are_well_formed(resumed)
        assert entity.arun_calls == 1

    @pytest.mark.asyncio
    async def test_a_run_that_cannot_be_started_still_terminates_the_client(self):
        """Starting failed after registration, so the client is owed a terminal event."""
        entity = UnstartableEntity(agent_script())
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        assert [event.type for event in events] == [EventType.RUN_ERROR]
        assert events[-1].message == "no capacity for another run"
        # The registration is gone afterwards, so the same run id can be tried
        # again rather than answering "already ended" for the rest of the
        # process. A tail that attached first was ended before it was dropped.
        assert await get_event_stream().get_run_status("run-1") is None

    @pytest.mark.asyncio
    async def test_a_run_id_whose_start_failed_can_be_started_again(self):
        """A failed start must not poison the run id for every later attempt."""
        await collect(
            run_entity_background(UnstartableEntity(agent_script()), FakeRunInput(forwarded_props=background_props()))
        )

        retried = ScriptedEntity(agent_script())
        events = await collect(run_entity_background(retried, FakeRunInput(forwarded_props=background_props())))

        assert retried.arun_calls == 1
        assert events[0].type == EventType.RUN_STARTED
        assert events[-1].type == EventType.RUN_FINISHED


# ---------------------------------------------------------------------------
# Disconnect and reconnect
# ---------------------------------------------------------------------------


class TestReconnect:
    @pytest.mark.asyncio
    async def test_reconnect_delivers_each_event_exactly_once_in_order(self):
        baseline_entity = ScriptedEntity(agent_script())
        baseline = await collect(
            run_entity_background(baseline_entity, FakeRunInput(forwarded_props=background_props()))
        )

        fresh_event_stream()
        entity = ScriptedEntity(agent_script())
        first_leg = await collect(
            run_entity_background(entity, FakeRunInput(forwarded_props=background_props())),
            stop_after=4,
        )
        resumed = await collect(
            run_entity_background(entity, FakeRunInput(forwarded_props=background_props(cursor_of(first_leg[-1]))))
        )

        assert fingerprints(first_leg + resumed) == fingerprints(baseline)

    @pytest.mark.asyncio
    async def test_reconnect_does_not_restart_the_run(self):
        entity = ScriptedEntity(agent_script())
        first_leg = await collect(
            run_entity_background(entity, FakeRunInput(forwarded_props=background_props())), stop_after=3
        )
        await collect(
            run_entity_background(entity, FakeRunInput(forwarded_props=background_props(cursor_of(first_leg[-1]))))
        )

        assert entity.arun_calls == 1

    @pytest.mark.asyncio
    async def test_run_continues_while_no_client_is_attached(self):
        entity = ScriptedEntity(agent_script(), pause_after=3)
        stream = run_entity_background(entity, FakeRunInput(forwarded_props=background_props()))
        first_leg = await collect(stream, stop_after=2)

        entity.release()
        resumed = await collect(
            run_entity_background(entity, FakeRunInput(forwarded_props=background_props(cursor_of(first_leg[-1]))))
        )

        assert entity.arun_calls == 1
        assert resumed[-1].type == EventType.RUN_FINISHED

    @pytest.mark.asyncio
    async def test_reconnect_after_completion_replays_the_remainder(self):
        entity = ScriptedEntity(agent_script())
        baseline = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        resumed = await collect(
            run_entity_background(entity, FakeRunInput(forwarded_props=background_props(cursor_of(baseline[2]))))
        )

        assert fingerprints(resumed) == fingerprints(baseline[3:])

    @pytest.mark.asyncio
    async def test_replay_reproduces_identical_message_ids(self):
        entity = ScriptedEntity(agent_script())
        baseline = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        full_replay = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        assert fingerprints(full_replay) == fingerprints(baseline)

    @pytest.mark.asyncio
    async def test_durable_stream_replay_path(self):
        """A stream that only ever hands back SSE strings replays identically."""
        durable = SseOnlyEventStream(get_event_stream())
        set_event_stream(durable)
        entity = ScriptedEntity(agent_script())
        baseline = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        resumed = await collect(
            run_entity_background(entity, FakeRunInput(forwarded_props=background_props(cursor_of(baseline[1]))))
        )

        # Asserted of each leg rather than only of the pair: two legs that
        # agree can still both be truncated, which is what a tail that gives
        # up quietly would produce.
        assert baseline[-1].type == EventType.RUN_FINISHED
        assert resumed[-1].type == EventType.RUN_FINISHED
        assert fingerprints(resumed) == fingerprints(baseline[2:])
        # Both legs really came through this stream's own replay-and-poll tail,
        # so the assertions above say something about the durable path.
        assert durable.tail_calls == 2
        assert durable.replay_calls > 0

    @pytest.mark.asyncio
    async def test_a_second_connection_naming_a_started_run_does_not_start_it_again(self):
        """A second client naming a run id this process already started attaches to it.

        Both connections are launched together, but nothing between the
        started-probe and the registration suspends, so the first reaches the
        buffer before the second is scheduled and the second finds a started
        run rather than a starting one. The window where it finds a starting
        one is held open deliberately in the test below.
        """
        baseline = await collect(
            run_entity_background(ScriptedEntity(agent_script()), FakeRunInput(forwarded_props=background_props()))
        )

        fresh_event_stream()
        entity = ScriptedEntity(agent_script())
        first, second = await asyncio.gather(
            collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props()))),
            collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props()))),
        )

        assert entity.arun_calls == 1
        assert fingerprints(first) == fingerprints(baseline)
        assert fingerprints(second) == fingerprints(baseline)

    @pytest.mark.asyncio
    async def test_a_connection_arriving_while_the_run_registers_waits_and_attaches(self):
        """A second connection inside the start window waits rather than being turned away.

        The first connection is held inside ``register_run``, so the second
        arrives while the run id is claimed but not yet registered: the state
        the wait-for-registration guard exists for. Attaching is what that
        connection wanted anyway, so it must end up with the same stream, not
        a refusal and not a second producer.
        """
        gated = GatedRegistrationStream(get_event_stream())
        set_event_stream(gated)
        entity = ScriptedEntity(agent_script())

        first = asyncio.create_task(
            collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))
        )
        await asyncio.wait_for(gated.registering.wait(), timeout=CONDITION_TIMEOUT_SECONDS)
        assert "run-1" in background_module._STARTING_RUNS

        reads_before = gated.status_reads
        second = asyncio.create_task(
            collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))
        )
        # The second connection's own started-probe, and then a poll that can
        # only come from the wait: the guard is reached, not merely available.
        await wait_until(lambda: gated.status_reads >= reads_before + 2)
        gated.release.set()

        first_events, second_events = await asyncio.gather(first, second)

        assert entity.arun_calls == 1
        assert first_events[0].type == EventType.RUN_STARTED
        assert first_events[-1].type == EventType.RUN_FINISHED
        assert fingerprints(second_events) == fingerprints(first_events)
        assert_spans_are_well_formed(second_events)

    @pytest.mark.asyncio
    async def test_a_connection_whose_run_never_registers_is_refused(self):
        """A wait that runs out ends the client instead of attaching it to nothing.

        The first connection is held inside ``register_run`` for good, so the
        second one spends its whole budget on a run that never appears.
        Falling through would leave it tailing a run id the event stream has
        never heard of, silent until something else times it out.
        """
        gated = GatedRegistrationStream(get_event_stream())
        set_event_stream(gated)
        entity = ScriptedEntity(agent_script())

        held = asyncio.create_task(
            collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))
        )
        await asyncio.wait_for(gated.registering.wait(), timeout=CONDITION_TIMEOUT_SECONDS)

        refused = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        assert [event.type for event in refused] == [EventType.RUN_ERROR]
        assert refused[0].message == "Run run-1 did not start"
        assert cursor_of(refused[0]) == (-1, 0)
        assert entity.arun_calls == 0

        held.cancel()
        gated.release.set()
        with contextlib.suppress(BaseException):
            await held

    @pytest.mark.asyncio
    async def test_attaching_from_another_session_without_a_resume_position_is_refused(self):
        """A started run is not readable by a second request that merely names its id.

        The run id is client-supplied, so a caller carrying no resume position
        at all still has to be checked against the session before the buffer
        is handed over.
        """
        owner = ScriptedEntity(agent_script())
        owned = await collect(run_entity_background(owner, FakeRunInput(forwarded_props=background_props())))
        assert owned[-1].type == EventType.RUN_FINISHED

        intruder = ForeignRunEntity(agent_script())
        events = await collect(
            run_entity_background(intruder, FakeRunInput(thread_id="other-thread", forwarded_props=background_props()))
        )

        assert [event.type for event in events] == [EventType.RUN_ERROR]
        assert events[0].message == "Run run-1 not found in this session"
        assert cursor_of(events[0]) == (-1, 0)
        assert intruder.arun_calls == 0

    @pytest.mark.asyncio
    async def test_a_trimmed_buffer_still_yields_a_valid_sequence(self):
        """When the buffer has dropped the start of a run, what is left is still coherent.

        The buffer is finite, so a long enough run replays from wherever it now
        begins. Here the trimmed events include the start of the tool call,
        while the event completing that call survives: closing a span this
        connection never opened would be invalid rather than merely
        incomplete, so the call is dropped whole, result and all.
        """
        fresh_event_stream(max_events_per_run=TRIMMED_TO_AFTER_THE_TOOL_CALL_START)
        entity = ScriptedEntity(agent_script())
        await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        replayed = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        assert entity.arun_calls == 1
        assert [event.type for event in replayed] == [
            EventType.RUN_STARTED,
            EventType.TEXT_MESSAGE_START,
            EventType.TEXT_MESSAGE_CONTENT,
            EventType.TEXT_MESSAGE_END,
            EventType.RUN_FINISHED,
        ]
        assert [event.delta for event in replayed if event.type == EventType.TEXT_MESSAGE_CONTENT] == ["lo"]
        assert TOOL.tool_call_id not in [getattr(event, "tool_call_id", None) for event in replayed]
        buffered_indices = [cursor_of(event)[0] for event in replayed if cursor_of(event)[0] >= 0]
        assert min(buffered_indices) == 4
        assert_spans_are_well_formed(replayed)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("held", [(0, 0), (1, 0), (2, 0)])
    async def test_resuming_against_a_trimmed_buffer_is_refused(self, held):
        """A trimmed buffer turns away a resume from any position at all.

        The translation is rebuilt from whatever the buffer still holds, so a
        message or a tool call whose source event is gone is opened again under
        a new identifier while the client's own copy of it is never closed.
        Held positions inside a group are covered too: one buffered event can
        produce several AG-UI events, and a client can hold the first of a
        group and still be owed its siblings.
        """
        fresh_event_stream(max_events_per_run=TRIMMED_TO_AFTER_THE_TOOL_CALL_START)
        entity = ScriptedEntity(agent_script())
        await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        refused = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props(held))))

        assert [event.type for event in refused] == [EventType.RUN_ERROR]
        assert refused[0].message == (
            "Run run-1 cannot be resumed from that position; the events after it are no longer buffered"
        )
        # Stamped past the position the client sent, so a client filtering by
        # cursor cannot drop the refusal and reconnect into it forever.
        assert cursor_of(refused[0]) == (held[0] + 1, 0)
        assert entity.arun_calls == 1

    @pytest.mark.asyncio
    async def test_a_resume_against_a_trimmed_buffer_is_refused(self):
        """A trimmed buffer cannot answer a resume, wherever the client stands.

        The translation is rebuilt from whatever the buffer still holds, so a
        message whose opening was trimmed is opened again under a new id while
        the client's own copy of it is never closed. That is worse than saying
        the run cannot be resumed.
        """
        fresh_event_stream(max_events_per_run=TRIMMED_TO_AFTER_THE_TOOL_CALL_START)
        entity = ScriptedEntity(agent_script())
        # The first connection tails live, so it sees every event before the
        # buffer drops any. Trimming only shows on a connection that replays.
        await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))
        replayed = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))
        buffered = [cursor_of(event)[0] for event in replayed if cursor_of(event)[0] >= 0]
        assert min(buffered) > 0, "the front of the run must have been trimmed for this to test anything"
        held = cursor_of(replayed[1])

        resumed = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props(held))))

        assert [event.type for event in resumed] == [EventType.RUN_ERROR]
        assert "no longer buffered" in resumed[0].message
        assert cursor_of(resumed[0]) > held
        assert all(cursor_of(event) > held for event in resumed)
        assert entity.arun_calls == 1


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


class TestRefusals:
    @pytest.mark.asyncio
    async def test_attaching_to_a_run_outside_the_session_is_refused(self):
        entity = ScriptedEntity(agent_script())
        await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        intruder = ForeignRunEntity(agent_script())
        events = await collect(
            run_entity_background(
                intruder,
                FakeRunInput(thread_id="other-thread", forwarded_props=background_props((0, 0))),
            )
        )

        assert [event.type for event in events] == [EventType.RUN_ERROR]
        assert events[-1].message == "Run run-1 not found in this session"
        assert intruder.arun_calls == 0

    @pytest.mark.asyncio
    async def test_an_ownership_check_that_raises_does_not_read_as_a_denial(self):
        """A storage failure must not send a client off to restart a run that is still live.

        The process did start this run, but its record of that is keyed by the
        entity, session and user the run belongs to, and the reconnect matches
        none of them. So the answer has to come from storage, which is what
        fails here.
        """
        entity = ScriptedEntity(agent_script())
        await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props())))

        unreadable = UnreadableRunEntity(agent_script())
        events = await collect(
            run_entity_background(
                unreadable, FakeRunInput(thread_id="other-thread", forwarded_props=background_props((0, 0)))
            )
        )

        assert [event.type for event in events] == [EventType.RUN_ERROR]
        assert events[-1].message == "Could not verify run run-1; try again"
        assert events[-1].message != "Run run-1 not found in this session"
        assert unreadable.arun_calls == 0

    @pytest.mark.asyncio
    async def test_attaching_when_ownership_cannot_be_checked_at_all_is_refused(self):
        """An entity with no way to read its run rows may not attach to a buffered run.

        The ownership check is what stops a caller naming any run id and
        reading another session's events back out of the buffer. An entity
        that cannot answer the question leaves no check to pass, so the answer
        is no rather than a shrug.
        """
        owner = ScriptedEntity(agent_script())
        owned = await collect(run_entity_background(owner, FakeRunInput(forwarded_props=background_props())))
        assert owned[-1].type == EventType.RUN_FINISHED

        blind = NoRunOutputEntity(agent_script())
        events = await collect(
            run_entity_background(blind, FakeRunInput(forwarded_props=background_props(cursor_of(owned[1]))))
        )

        assert [event.type for event in events] == [EventType.RUN_ERROR]
        assert events[0].message == "Run run-1 not found in this session"
        assert blind.arun_calls == 0

    @pytest.mark.asyncio
    async def test_an_unreadable_resume_position_is_refused_rather_than_replayed(self):
        """A resume position that cannot be read must not restart the whole run."""
        entity = ScriptedEntity(agent_script())
        props = {"agnoBackground": {"enabled": True, "lastEventIndex": "4"}}
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=props)))

        assert [event.type for event in events] == [EventType.RUN_ERROR]
        assert "Unreadable background resume position" in events[-1].message
        assert entity.arun_calls == 0

    @pytest.mark.asyncio
    async def test_a_json_true_resume_position_is_refused(self):
        """A JSON true is an int in Python, so it would otherwise resume from index 1."""
        entity = ScriptedEntity(agent_script())
        props = {"agnoBackground": {"enabled": True, "lastEventIndex": True}}
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=props)))

        assert [event.type for event in events] == [EventType.RUN_ERROR]
        assert "Unreadable background resume position" in events[-1].message
        assert entity.arun_calls == 0

    @pytest.mark.asyncio
    async def test_attaching_when_the_stream_state_is_gone_is_refused(self):
        """The run row outlived its events, so there is nothing left to resume from.

        Saying so beats stalling on an empty stream and then reporting success.
        """
        entity = ScriptedEntity(agent_script())
        events = await collect(run_entity_background(entity, FakeRunInput(forwarded_props=background_props((3, 0)))))

        assert [event.type for event in events] == [EventType.RUN_ERROR]
        assert events[-1].message == "Run run-1 is no longer available for replay"
        assert entity.arun_calls == 0


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------

ANSWER_CHUNKS = ["Hel", "lo"]

# The route quotes the entity's id when it declines to run it detached.
DETACHABLE_AGENT_ID = "background-agent"
INLINE_ONLY_AGENT_ID = "no-db-agent"
DETACHABLE_PATH = "/detachable/agui"
INLINE_ONLY_PATH = "/inline-only/agui"


class EchoModel(Model):
    """An offline model that answers with a fixed set of chunks.

    ``invocations`` is what tells a request the route refused from one it
    quietly ran again: a refusal must reach no model at all.
    """

    def __init__(self) -> None:
        super().__init__(id="echo-test-model", name="echo-test-model", provider="test")
        self.instructions = None
        self.invocations = 0

    def __deepcopy__(self, memo: dict) -> "EchoModel":
        # Shared rather than copied, so a run reached through the route still
        # counts against the instance the test holds.
        return self

    def _response(self, text: str) -> ModelResponse:
        return ModelResponse(content=text, role="assistant", response_usage=MessageMetrics())

    def get_instructions_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_system_message_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def aget_instructions_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def aget_system_message_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    def parse_args(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.invocations += 1
        return self._response("".join(ANSWER_CHUNKS))

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.invocations += 1
        return self._response("".join(ANSWER_CHUNKS))

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        self.invocations += 1
        for chunk in ANSWER_CHUNKS:
            yield self._response(chunk)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        self.invocations += 1
        for chunk in ANSWER_CHUNKS:
            yield self._response(chunk)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return self._response("")

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._response("")


@dataclass
class AguiRoutes:
    """A live AG-UI route pair: one entity that can run detached, one that cannot."""

    client: TestClient
    detachable_model: EchoModel
    inline_only_model: EchoModel


@pytest.fixture
def agui_routes() -> Iterator[AguiRoutes]:
    with tempfile.TemporaryDirectory() as directory:
        db = SqliteDb(db_file=str(Path(directory) / "agui-route.db"))
        detachable_model = EchoModel()
        inline_only_model = EchoModel()
        # A database and an in-process entity are what background execution
        # needs, so the second agent differs from the first only in having no
        # database to persist a detached run's status to.
        detachable = Agent(id=DETACHABLE_AGENT_ID, name=DETACHABLE_AGENT_ID, model=detachable_model, db=db)
        inline_only = Agent(id=INLINE_ONLY_AGENT_ID, name=INLINE_ONLY_AGENT_ID, model=inline_only_model)

        agent_os = AgentOS(
            agents=[detachable, inline_only],
            interfaces=[
                AGUI(agent=detachable, prefix="/detachable"),
                AGUI(agent=inline_only, prefix="/inline-only"),
            ],
        )
        with TestClient(agent_os.get_app()) as client:
            yield AguiRoutes(client=client, detachable_model=detachable_model, inline_only_model=inline_only_model)


def route_body(
    *,
    thread_id: str,
    run_id: str,
    background: Optional[Dict[str, Any]] = None,
    tool_result_for: Optional[str] = None,
) -> Dict[str, Any]:
    messages: List[Dict[str, Any]] = [{"id": "m1", "role": "user", "content": "say hello"}]
    if tool_result_for is not None:
        # A trailing tool message is what marks a request as the continuation
        # of a run that paused for the client to execute a tool.
        messages.append({"id": "t1", "role": "tool", "content": "{}", "toolCallId": tool_result_for})
    return {
        "threadId": thread_id,
        "runId": run_id,
        "state": None,
        "messages": messages,
        "tools": [],
        "context": [],
        "forwardedProps": {} if background is None else {"agnoBackground": background},
    }


def post_events(routes: AguiRoutes, path: str, body: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The AG-UI events one request produced, in the order they were written."""
    response = routes.client.post(path, json=body)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]


def resume_marker(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return (event.get("metadata") or {}).get("agnoBackground")


def route_cursor(event: Dict[str, Any]) -> Tuple[int, int]:
    marker = resume_marker(event)
    assert marker is not None, f"{event['type']} carries no resume marker: {event!r}"
    return marker["eventIndex"], marker["subIndex"]


def identity(event: Dict[str, Any]) -> Dict[str, Any]:
    """An event's payload, minus the protocol's optional wall-clock timestamp."""
    return {key: value for key, value in event.items() if key != "timestamp"}


class TestRoute:
    def test_a_background_run_streams_end_to_end(self, agui_routes: AguiRoutes):
        """The route runs the entity detached and serves it back out of the buffer.

        Every event carries a resume marker, which is how a client learns this
        connection can be dropped and picked up again, and the answer arrives
        in one piece with the model reached exactly once.
        """
        events = post_events(
            agui_routes,
            DETACHABLE_PATH,
            route_body(thread_id="detached", run_id="detached-run", background={"enabled": True}),
        )

        # Raw events pass through untranslated and their number is the model's
        # business, not the route's, so the answer is read around them.
        assert [event["type"] for event in events if event["type"] != "RAW"] == [
            "RUN_STARTED",
            "TEXT_MESSAGE_START",
            "TEXT_MESSAGE_CONTENT",
            "TEXT_MESSAGE_CONTENT",
            "TEXT_MESSAGE_END",
            "RUN_FINISHED",
        ]
        assert [event["delta"] for event in events if event["type"] == "TEXT_MESSAGE_CONTENT"] == ANSWER_CHUNKS
        assert agui_routes.detachable_model.invocations == 1

        cursors = [route_cursor(event) for event in events]
        assert cursors == sorted(cursors)
        assert len(set(cursors)) == len(cursors)
        assert cursors[0] == (-1, 0)
        assert cursors[-1] == max(cursors)

    def test_a_background_run_is_picked_up_from_a_cursor_rather_than_run_again(self, agui_routes: AguiRoutes):
        """A second request through the route resumes rather than answering twice.

        The remainder has to match the first connection's own tail event for
        event, ids included, or a client stitching the two legs together sees
        a message it never opened.
        """
        body = route_body(thread_id="resumed", run_id="resumed-run", background={"enabled": True})
        whole = post_events(agui_routes, DETACHABLE_PATH, body)
        assert whole[-1]["type"] == "RUN_FINISHED"

        pivot = next(index for index, event in enumerate(whole) if event["type"] == "TEXT_MESSAGE_CONTENT")
        event_index, sub_index = route_cursor(whole[pivot])
        rest = post_events(
            agui_routes,
            DETACHABLE_PATH,
            route_body(
                thread_id="resumed",
                run_id="resumed-run",
                background={"enabled": True, "lastEventIndex": event_index, "lastSubIndex": sub_index},
            ),
        )

        assert [identity(event) for event in rest] == [identity(event) for event in whole[pivot + 1 :]]
        assert agui_routes.detachable_model.invocations == 1

    def test_a_resume_position_with_background_disabled_is_refused(self, agui_routes: AguiRoutes):
        """A resume position is a claim to be continuing a run, switch or no switch.

        Falling through to a foreground run would answer the whole question a
        second time, which is the one thing the client asking to resume was
        trying to avoid.
        """
        events = post_events(
            agui_routes,
            DETACHABLE_PATH,
            route_body(
                thread_id="disabled",
                run_id="disabled-run",
                background={"enabled": False, "lastEventIndex": 3, "lastSubIndex": 1},
            ),
        )

        assert [event["type"] for event in events] == ["RUN_ERROR"]
        assert events[0]["message"] == "A resume position was sent with background execution disabled"
        assert resume_marker(events[0]) == {"eventIndex": 4, "subIndex": 0}
        assert agui_routes.detachable_model.invocations == 0

    def test_a_resume_position_to_an_entity_that_cannot_run_detached_is_refused(self, agui_routes: AguiRoutes):
        """Declining background execution must not turn a resume into a rerun."""
        events = post_events(
            agui_routes,
            INLINE_ONLY_PATH,
            route_body(
                thread_id="unsupported",
                run_id="unsupported-run",
                background={"enabled": True, "lastEventIndex": 3, "lastSubIndex": 1},
            ),
        )

        assert [event["type"] for event in events] == ["RUN_ERROR"]
        assert events[0]["message"] == (
            f"Background execution is unavailable for '{INLINE_ONLY_AGENT_ID}': it needs a database, "
            "an agent or team that runs in this process, and a readable run history"
        )
        assert resume_marker(events[0]) == {"eventIndex": 4, "subIndex": 0}
        assert agui_routes.inline_only_model.invocations == 0

    def test_a_first_connection_to_such_an_entity_runs_in_the_foreground(self, agui_routes: AguiRoutes):
        """With nothing to resume, the request is served inline rather than refused.

        The run then carries no resume marker at all, which is how a client
        learns this connection is the only one it gets.
        """
        events = post_events(
            agui_routes,
            INLINE_ONLY_PATH,
            route_body(thread_id="inline", run_id="inline-run", background={"enabled": True}),
        )

        # Raw events pass through untranslated and their number is the model's
        # business, not the route's, so the answer is read around them.
        assert [event["type"] for event in events if event["type"] != "RAW"] == [
            "RUN_STARTED",
            "TEXT_MESSAGE_START",
            "TEXT_MESSAGE_CONTENT",
            "TEXT_MESSAGE_CONTENT",
            "TEXT_MESSAGE_END",
            "RUN_FINISHED",
        ]
        assert [event["delta"] for event in events if event["type"] == "TEXT_MESSAGE_CONTENT"] == ANSWER_CHUNKS
        assert all(resume_marker(event) is None for event in events)
        assert agui_routes.inline_only_model.invocations == 1

    def test_continuing_a_paused_run_while_echoing_a_resume_position_is_not_refused(self, agui_routes: AguiRoutes):
        """A continuation is a new leg, so the position it still echoes does not apply.

        Deciding the continuation first is what keeps a client that
        answers a tool call, and happens to still be sending the last cursor
        it saw, from being turned away instead of continued. The session here
        holds no paused run, so the continuation fails on its way through the
        foreground path, which is the point: it got there.
        """
        events = post_events(
            agui_routes,
            DETACHABLE_PATH,
            route_body(
                thread_id="continuation",
                run_id="continuation-run",
                background={"enabled": True, "lastEventIndex": 3, "lastSubIndex": 1},
                tool_result_for="call-1",
            ),
        )

        assert [event["type"] for event in events] == ["RUN_STARTED", "RUN_ERROR"]
        assert events[1]["message"] == "Session continuation not found"
        # The foreground path stamps nothing, so a missing marker on the
        # RUN_STARTED is itself the evidence the run was never refused: a
        # refusal is a lone stamped RUN_ERROR with no run beginning at all.
        assert all(resume_marker(event) is None for event in events)

    @pytest.mark.parametrize(
        "background, message, marker",
        [
            (
                {"enabled": True, "lastEventIndex": "4"},
                "Unreadable background resume position: {'enabled': True, 'lastEventIndex': '4'}",
                {"eventIndex": -1, "subIndex": 0},
            ),
            (
                {"enabled": True, "lastEventIndex": 2, "lastSubIndex": 0},
                "Run ghost-run not found in this session",
                {"eventIndex": 3, "subIndex": 0},
            ),
        ],
    )
    def test_every_error_the_background_path_emits_carries_a_resume_marker(
        self, agui_routes: AguiRoutes, background: Dict[str, Any], message: str, marker: Dict[str, int]
    ):
        """A client filtering by cursor would drop an unmarked error and reconnect into it.

        So a refusal is positioned past whatever the client last held, exactly
        like the events it is refusing to send.
        """
        events = post_events(
            agui_routes,
            DETACHABLE_PATH,
            route_body(thread_id="ghost", run_id="ghost-run", background=background),
        )

        assert [event["type"] for event in events] == ["RUN_ERROR"]
        assert events[0]["message"] == message
        assert resume_marker(events[0]) == marker
        assert agui_routes.detachable_model.invocations == 0
