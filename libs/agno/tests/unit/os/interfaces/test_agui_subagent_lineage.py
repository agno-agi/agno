"""AG-UI subagent lineage for Team runs.

Agno stamps every streamed chunk with the run it came from and, for a member,
the run that delegated to it. These tests assert, from the emitted payloads,
that each message, tool call and reasoning block is attributed to the member
that produced it.

Wherever a scripted (no-network) model can drive the behavior, the stream is a
real entity run: one test drives the whole interface over SSE, and the state,
stamp and startup checks call the interface directly. A member that pauses is
one of those: a member whose tool needs a confirmation pauses for real under a
scripted model, and the announcement and the prompt on its lane are asserted
against that run. Reasoning inside a member, output that trails a member's own
terminal, a lane whose parent lane terminated before it and a run that fails
with member lanes still open are not reachable from a scripted model, and
neither are the pause shapes one run cannot produce: a leader and a member
paused at once, a pause naming a member whose lane already terminated, a paused
grandchild, and a pause reported only through requirements. Those tests
hand-build the chunk sequence. A hand-built chunk carries the lineage fields the framework
really stamps on a member's chunks: ``run_id`` for the run the chunk came from,
``parent_run_id`` for the run that delegated to it, and
``agent_id``/``agent_name`` or ``team_id``/``team_name`` for the member's
identity, which the real-stream tests in this module pin independently.

The default ``inline`` visibility is asserted to emit the same stream as before
lineage existed, and a single Agent is asserted to be unaffected by the setting.
"""

import ast
import inspect
import json
import threading
from dataclasses import fields
from functools import partial
from itertools import combinations
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import BaseEvent, EventType
from ag_ui.encoder import EventEncoder
from pydantic import BaseModel

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.response import ToolExecution
from agno.os.interfaces.agui import handlers, interrupts
from agno.os.interfaces.agui.handlers import validate_subagent_visibility
from agno.os.interfaces.agui.state import (
    ROOT_LANE,
    SUBAGENT_VISIBILITY_HIDDEN,
    SUBAGENT_VISIBILITY_INLINE,
    StreamState,
)
from agno.os.interfaces.agui.stream import (
    async_stream_agno_response_as_agui_events,
    stream_agno_response_as_agui_events,
)
from agno.reasoning.step import ReasoningStep
from agno.run.agent import (
    CustomEvent,
    ReasoningCompletedEvent,
    ReasoningContentDeltaEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunErrorEvent,
    RunEvent,
    RunStartedEvent,
    ToolCallCompletedEvent,
    ToolCallErrorEvent,
    ToolCallStartedEvent,
)
from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
from agno.run.requirement import RunRequirement
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.run.team import RunStartedEvent as TeamRunStartedEvent
from agno.run.team import ToolCallCompletedEvent as TeamToolCallCompletedEvent
from agno.run.team import ToolCallStartedEvent as TeamToolCallStartedEvent
from agno.team import Team
from agno.tools import tool

from .agui_stream_invariants import (
    ATTRIBUTED_EVEN_WHEN_REFUSED,
    TOP_LEVEL_RUN,
    TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL,
    ScriptedModel,
    SideEffect,
    agent_said,
    announcements,
    assert_stream_carries_exactly,
    assert_stream_contains,
    assert_well_formed_stream,
    attributed,
    captured_agno_logs,
    circular,
    collect_async,
    collect_async_recording_violations,
    collect_sync,
    collect_sync_recording_violations,
    event_type_named,
    in_emitted_order,
    joined_text_in_emitted_order,
    lane_of,
    member_chunk_kwargs,
    needs_lineage_events,
    of_type,
    require_lineage_events,
    sse_events,
    stream_invariant_violation,
    team_chunk_kwargs,
    team_said,
)

THREAD_ID = "lineage-session"

# The suspended subagent outcome arrived after the lineage events themselves, so
# a release can serve member attribution and still declare no ``outcome`` on a
# member's terminal. Anything here that reads or expects that field asks this
# rather than taking the lineage gate to cover it.
_SUSPENDED_OUTCOME_IS_SERVABLE = interrupts.subagent_suspension_available()


@tool
def search_docs(query: str) -> str:
    return f"docs about {query}"


@tool
def spell_check(text: str) -> str:
    return f"checked: {text}"


def _researcher(db: InMemoryDb) -> Agent:
    return Agent(
        name="Researcher",
        id="researcher",
        model=ScriptedModel(
            "m-researcher",
            [
                ("tool", "search_docs", {"query": "agno"}, "tc-search"),
                ("content", "Found three sources."),
            ],
        ),
        tools=[search_docs],
        db=db,
        telemetry=False,
    )


def _writer(db: InMemoryDb) -> Agent:
    return Agent(
        name="Writer",
        id="writer",
        model=ScriptedModel(
            "m-writer",
            [
                ("tool", "spell_check", {"text": "draft"}, "tc-spell"),
                ("content", "Here is the brief."),
            ],
        ),
        tools=[spell_check],
        db=db,
        telemetry=False,
    )


def _team(db: InMemoryDb, members: List[Agent], calls: List[tuple]) -> Team:
    script: List[tuple] = [("tool", "delegate_task_to_member", args, tcid) for args, tcid in calls]
    script.append(("content", "Final synthesis."))
    return Team(
        name="Research Team",
        id="research-team",
        model=ScriptedModel("m-leader", script),
        members=members,
        db=db,
        telemetry=False,
    )


def _two_member_team(db: InMemoryDb) -> Team:
    return _team(
        db,
        [_researcher(db), _writer(db)],
        [
            ({"member_id": "researcher", "task": "research the topic"}, "tc-delegate-researcher"),
            ({"member_id": "writer", "task": "write the brief"}, "tc-delegate-writer"),
        ],
    )


def _twin(db: InMemoryDb, member_id: str, name: str) -> Agent:
    """One member whose run reports the same words as its twin's."""
    return Agent(
        name=name,
        id=member_id,
        model=ScriptedModel(f"m-{member_id}", [("content", "identical wording")]),
        db=db,
        telemetry=False,
    )


def _twins_team(db: InMemoryDb) -> Team:
    """A leader that delegates to two members which report identical content."""
    return _team(
        db,
        [_twin(db, "alpha", "Alpha"), _twin(db, "beta", "Beta")],
        [
            ({"member_id": "alpha", "task": "say it"}, "tc-delegate-alpha"),
            ({"member_id": "beta", "task": "say it too"}, "tc-delegate-beta"),
        ],
    )


# Every collector below runs the shared stream-invariant helper before handing
# the events back, so each test in this module inherits the whole invariant set
# whether or not it thought to ask for it.


async def _collect_entity_sync(
    entity: Any, visibility: Optional[str] = None, prompt: str = "Write a brief"
) -> List[BaseEvent]:
    """One real entity run, mapped by the sync mapper."""
    events = list(
        stream_agno_response_as_agui_events(
            entity.run(prompt, session_id=THREAD_ID, stream=True, stream_events=True, run_id=TOP_LEVEL_RUN),
            thread_id=THREAD_ID,
            run_id=TOP_LEVEL_RUN,
            subagent_visibility=visibility,
        )
    )
    assert_well_formed_stream(events)
    return events


async def _collect_entity_async(
    entity: Any, visibility: Optional[str] = None, prompt: str = "Write a brief"
) -> List[BaseEvent]:
    """One real entity run, mapped by the async mapper."""
    stream = entity.arun(prompt, session_id=THREAD_ID, stream=True, stream_events=True, run_id=TOP_LEVEL_RUN)
    events = [
        event
        async for event in async_stream_agno_response_as_agui_events(
            stream, thread_id=THREAD_ID, run_id=TOP_LEVEL_RUN, subagent_visibility=visibility
        )
    ]
    assert_well_formed_stream(events)
    return events


# The two mappers duplicate the same body, so the attribution cases run through
# both rather than trusting the async one to stand for the pair.
entity_mappers = pytest.mark.parametrize(
    "collect_entity", [_collect_entity_sync, _collect_entity_async], ids=["sync", "async"]
)

_lane = lane_of
_of_type = of_type


async def _collect_chunks_sync(
    chunks: Iterable[Any],
    visibility: Optional[str] = None,
    *,
    run_id: str = TOP_LEVEL_RUN,
    run_state: Optional[Dict[str, Any]] = None,
    exempt: Sequence[str] = (),
    emit_interrupt_outcome: bool = False,
) -> List[BaseEvent]:
    """One hand-built chunk list, mapped by the sync mapper."""
    events, error = await collect_sync(
        chunks,
        visibility,
        thread_id=THREAD_ID,
        run_id=run_id,
        run_state=run_state,
        exempt=exempt,
        emit_interrupt_outcome=emit_interrupt_outcome,
    )
    assert error is None, f"the source stream raised {error!r}"
    return events


async def _collect_chunks_async(
    chunks: Iterable[Any],
    visibility: Optional[str] = None,
    *,
    run_id: str = TOP_LEVEL_RUN,
    run_state: Optional[Dict[str, Any]] = None,
    exempt: Sequence[str] = (),
    emit_interrupt_outcome: bool = False,
) -> List[BaseEvent]:
    """One hand-built chunk list, mapped by the async mapper."""
    events, error = await collect_async(
        chunks,
        visibility,
        thread_id=THREAD_ID,
        run_id=run_id,
        run_state=run_state,
        exempt=exempt,
        emit_interrupt_outcome=emit_interrupt_outcome,
    )
    assert error is None, f"the source stream raised {error!r}"
    return events


chunk_mappers = pytest.mark.parametrize("collect", [_collect_chunks_sync, _collect_chunks_async], ids=["sync", "async"])

# For the few streams whose subject is a shape the shared checker calls
# malformed. The invariants still run, on the same definition, so a stream that
# stops breaking one is a diff rather than a silence.
malformed_mappers = pytest.mark.parametrize(
    "collect_malformed",
    [collect_sync_recording_violations, collect_async_recording_violations],
    ids=["sync", "async"],
)


def _announcements(events: List[BaseEvent]) -> List[BaseEvent]:
    """Every SUBAGENT_STARTED in order.

    A list rather than a mapping, so a second announcement, or two lanes sharing
    a name, stays visible in whatever the caller compares. A lane announced twice
    is refused by the shared checker every collector here runs, so this does not
    assert it a second time.

    Built on the shared announcement reader, which names no event type an older
    protocol release lacks, so the visibility settings that work on such a
    release keep running here.
    """
    return announcements(events)


def _is_terminal(event: BaseEvent) -> bool:
    """Whether an event is a member's terminal, refusing to read the announcement as one.

    Matched on the two terminal types rather than on ``SUBAGENT`` appearing in
    the type name, which also matches ``SUBAGENT_STARTED``: the announcement
    precedes everything its lane carries, so an ordering claim made against it
    holds no matter what the stream does afterwards.
    """
    require_lineage_events()
    return event.type in (EventType.SUBAGENT_FINISHED, EventType.SUBAGENT_ERROR)


def _suspended_outcomes(terminals: Sequence[BaseEvent]) -> List[Any]:
    """What each member terminal says about being suspended, in the order given.

    A release that declares the field is read straight, so one that later drops
    it fails here rather than quietly reading as carrying nothing. A release
    that never had it can carry no outcome, and an outcome written on it anyway
    would ride out as an undeclared attribute, so it is read through ``getattr``
    and a terminal that carries nothing reads as ``None``.
    """
    if _SUSPENDED_OUTCOME_IS_SERVABLE:
        return [event.outcome for event in terminals]  # type: ignore[attr-defined]
    return [getattr(event, "outcome", None) for event in terminals]


def _lane_names(events: List[BaseEvent]) -> Dict[str, str]:
    """subagent run id -> the name it was announced under."""
    return {e.subagent_run_id: e.name for e in _announcements(events)}  # type: ignore[attr-defined]


def _messages_in_order(events: List[BaseEvent]) -> List[Tuple[Optional[str], str]]:
    """(name of the member that owns it, joined text) per message, in the order they opened.

    Ordered, never keyed by the text: two members that happen to say the same
    thing have to stay two entries.
    """
    names = _lane_names(events)
    return [(names[lane] if lane is not None else None, text) for lane, text in joined_text_in_emitted_order(events)]


def _tool_calls_in_order(events: List[BaseEvent]) -> List[Tuple[str, Optional[str]]]:
    """(tool call id, name of the member that owns it) per TOOL_CALL_START, in order."""
    names = _lane_names(events)
    return [
        (tool_call_id, names[lane] if lane is not None else None)
        for tool_call_id, lane in in_emitted_order(events, EventType.TOOL_CALL_START, "tool_call_id", _lane)
    ]


def _tool_call_lanes_in_order(events: List[BaseEvent]) -> List[Tuple[str, Optional[str]]]:
    """(tool call id, raw member lane) per TOOL_CALL_START, in order."""
    return [
        (tool_call_id, lane)
        for tool_call_id, lane in in_emitted_order(events, EventType.TOOL_CALL_START, "tool_call_id", _lane)
    ]


def _reasoning_blocks_in_order(events: List[BaseEvent]) -> List[Tuple[Optional[str], str]]:
    """(member lane, joined reasoning text) per reasoning message, in the order they opened."""
    deltas: Dict[str, str] = {}
    for event in _of_type(events, EventType.REASONING_MESSAGE_CONTENT):
        message_id = event.message_id  # type: ignore[attr-defined]
        deltas[message_id] = deltas.get(message_id, "") + event.delta  # type: ignore[attr-defined]
    return [
        (_lane(event), deltas.get(event.message_id, ""))  # type: ignore[attr-defined]
        for event in _of_type(events, EventType.REASONING_MESSAGE_START)
    ]


def _lane_of_message_id(events: List[BaseEvent]) -> Dict[str, Optional[str]]:
    """message id -> the member lane that opened it.

    A mapping is the right shape here: this is looked up by id to answer "who
    owns this message", never compared against an expected mapping. The stream
    invariant helper is what refuses a message id opened twice.
    """
    return {e.message_id: _lane(e) for e in _of_type(events, EventType.TEXT_MESSAGE_START)}  # type: ignore[attr-defined]


def _type_sequence(events: List[BaseEvent]) -> List[str]:
    return [str(e.type) for e in events]


def _lane_sequence(events: List[BaseEvent], lane: Optional[str]) -> List[str]:
    return [str(e.type).removeprefix("EventType.") for e in events if _lane(e) == lane]


def _span_pairs(events: List[BaseEvent], start: EventType, end: EventType) -> Tuple[List[str], List[str]]:
    """The message ids a span type opened and the ones it closed, in order."""
    return (
        [e.message_id for e in _of_type(events, start)],  # type: ignore[attr-defined]
        [e.message_id for e in _of_type(events, end)],  # type: ignore[attr-defined]
    )


def _normalized_payloads(events: List[BaseEvent]) -> List[Tuple[str, Dict[str, Any]]]:
    """Event payloads with generated ids replaced by first-seen ordinals, so two runs compare."""
    aliases: Dict[str, str] = {}

    def alias(value: Any) -> Any:
        if not isinstance(value, str) or len(value) != 36 or value.count("-") != 4:
            return value
        return aliases.setdefault(value, f"id-{len(aliases)}")

    normalized = []
    for event in events:
        payload = event.model_dump(exclude_none=True, by_alias=True)
        payload.pop("type", None)
        payload.pop("timestamp", None)
        if event.type == EventType.RAW:
            # RAW carries the whole Agno chunk, including timings and token
            # counts that differ between runs; its identity is the event name.
            payload = {"event": payload.get("event", {}).get("event")}
        normalized.append((str(event.type), {k: alias(v) for k, v in payload.items()}))
    return normalized


# The lineage fields a member's or a team's chunks carry, and the two content
# chunks, come from the shared module: the failure and hostile suites build the
# same chunks, and a member chunk only reads as one while its parent names the
# same top-level run these do.
_member_kwargs = member_chunk_kwargs
_team_kwargs = team_chunk_kwargs
_agent_said = agent_said
_team_said = team_said

_TOP_LEVEL = _team_kwargs("research-team", "Research Team", TOP_LEVEL_RUN)


def _reasoning_step(title: str, reasoning: str, **kwargs: Any) -> ReasoningStepEvent:
    chunk = ReasoningStepEvent(**kwargs)
    chunk.content = ReasoningStep(title=title, reasoning=reasoning)
    return chunk


def _delegation(tool_call_id: str, member_id: str, task: str, result: Optional[str] = None) -> ToolExecution:
    """The call a leader delegates to one member with, as the framework records it.

    The name and the two arguments are what the interface reads to tie a member
    to the call that spawned it, so they are written once here rather than at
    every site that needs one.
    """
    return ToolExecution(
        tool_call_id=tool_call_id,
        tool_name="delegate_task_to_member",
        tool_args={"member_id": member_id, "task": task},
        result=result,
    )


def _requirement(
    tool: ToolExecution,
    member_id: Optional[str] = None,
    run_id: Optional[str] = None,
    name: Optional[str] = None,
) -> RunRequirement:
    """A pending call a paused run names the member waiting on it by.

    The three member fields travel together, so they are written together: a
    case that means to leave one out passes None and says so, rather than
    omitting a line among three that reads as an oversight.
    """
    requirement = RunRequirement(tool)
    requirement.member_agent_id = member_id
    requirement.member_agent_name = name
    requirement.member_run_id = run_id
    return requirement


def _nameless_tool() -> ToolExecution:
    """A pending call with no tool name, which the client cannot be shown."""
    return ToolExecution(tool_call_id="tc-nameless", tool_args={"to": "ops"}, requires_confirmation=True)


def _idless_tool() -> ToolExecution:
    """A pending call with no id, which a resume has nothing to resolve against."""
    return ToolExecution(tool_name="send_invoice", tool_args={"to": "ops"}, requires_confirmation=True)


def _enumerated_by_the_interface(table: Iterable[Any], *floor: Any, described: str) -> Set[Any]:
    """One of the interface's own enumerations, refused when it has lost a member it must hold.

    Several checks in this module scan the interface for what one of its
    enumerations names and are handed that same enumeration to scan for. An
    empty one folds such a check to nothing found against nothing expected, and
    it then holds whatever the interface does. Naming a member that has to be
    there is what keeps the comparison from being between two absences, so every
    check of that shape states its floor through here.
    """
    names = set(table)
    missing = sorted(str(entry) for entry in floor if entry not in names)
    assert not missing, (
        f"{described} no longer names {missing}, so what is keyed by it compares nothing: "
        f"it holds {sorted(str(name) for name in names)}"
    )
    return names


# --- Attribution ------------------------------------------------------------


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_team_attributes_each_message_to_its_member(collect_entity):
    events = await collect_entity(_two_member_team(InMemoryDb()), attributed())

    assert_stream_contains(events, EventType.TEXT_MESSAGE_CONTENT, 3)
    # In order, so two lanes are never folded together by what they said. The
    # empty entries are the assistant messages a tool call has to be parented to.
    assert _messages_in_order(events) == [
        (None, ""),
        ("Researcher", ""),
        ("Researcher", "Found three sources."),
        ("Writer", ""),
        ("Writer", "Here is the brief."),
        # The team leader's own reply belongs to no subagent.
        (None, "Final synthesis."),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_two_members_that_say_the_same_thing_stay_two_messages(collect_entity):
    events = await collect_entity(_twins_team(InMemoryDb()), attributed())
    names = _lane_names(events)

    assert_stream_contains(events, EventType.TEXT_MESSAGE_CONTENT, 3)
    assert_stream_contains(events, EventType.SUBAGENT_FINISHED, 2)
    # In order, so the two identical messages stay two entries. The empty entry
    # is the assistant message the delegation calls are parented to.
    assert _messages_in_order(events) == [
        (None, ""),
        ("Alpha", "identical wording"),
        ("Beta", "identical wording"),
        (None, "Final synthesis."),
    ]
    terminals = in_emitted_order(events, EventType.SUBAGENT_FINISHED, "subagent_run_id", "result")
    assert [(names[lane], result) for lane, result in terminals] == [
        ("Alpha", "identical wording"),
        ("Beta", "identical wording"),
    ]
    # The framework gives each delegation its own run id, which is what keeps
    # two members saying one thing from sharing a lane.
    first, second = [lane for lane, _ in terminals]
    assert first != second, "both members were reported under one run id"


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_team_attributes_each_tool_call_to_its_member(collect_entity):
    events = await collect_entity(_two_member_team(InMemoryDb()), attributed())

    assert_stream_contains(events, EventType.TOOL_CALL_START, 4)
    # In order, so a call emitted twice cannot hide behind its own id, and the
    # delegations themselves stay the leader's own tool calls.
    assert _tool_calls_in_order(events) == [
        ("tc-delegate-researcher", None),
        ("tc-search", "Researcher"),
        ("tc-delegate-writer", None),
        ("tc-spell", "Writer"),
    ]


def _reasoning_team_chunks() -> List[Any]:
    """Two members reasoning at the same time, which a scripted model cannot drive.

    Both spans open before any step arrives and the four steps then alternate
    between the lanes, which is what tells per-lane step numbering apart from one
    counter for the whole stream: reset at each reasoning span or never reset,
    one counter numbers the alternating steps 1, 2, 3, 4, so the two blocks read
    "Step 1" then "Step 3" and "Step 2" then "Step 4". Only a counter kept per
    lane numbers both members 1 then 2.
    """

    def delegation(member_id: str, tool_call_id: str) -> ToolExecution:
        return _delegation(tool_call_id, member_id, f"work for {member_id}", result=f"{member_id} finished")

    researcher = _member_kwargs("researcher", "run-1")
    writer = _member_kwargs("writer", "run-2")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=delegation("researcher", "tc-d1")),
        RunStartedEvent(**researcher),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=delegation("writer", "tc-d2")),
        RunStartedEvent(**writer),
        ReasoningStartedEvent(**researcher),
        ReasoningStartedEvent(**writer),
        _reasoning_step("researcher plan", "researcher is thinking", **researcher),
        _reasoning_step("writer plan", "writer is thinking", **writer),
        _reasoning_step("researcher check", "researcher is checking", **researcher),
        _reasoning_step("writer check", "writer is checking", **writer),
        ReasoningCompletedEvent(**researcher),
        ReasoningCompletedEvent(**writer),
        _agent_said("researcher says hello", **researcher),
        RunCompletedEvent(content="researcher says hello", **researcher),
        TeamToolCallCompletedEvent(run_id=TOP_LEVEL_RUN, tool=delegation("researcher", "tc-d1")),
        _agent_said("writer says hello", **writer),
        RunCompletedEvent(content="writer says hello", **writer),
        TeamToolCallCompletedEvent(run_id=TOP_LEVEL_RUN, tool=delegation("writer", "tc-d2")),
        _team_said("Final synthesis.", **_TOP_LEVEL),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_team_attributes_each_reasoning_block_to_its_member(collect):
    events = await collect(_reasoning_team_chunks(), attributed())
    names = _lane_names(events)

    assert_stream_contains(events, EventType.REASONING_MESSAGE_CONTENT, 4)
    # Ordered, and the whole block text rather than a phrase inside it: a member's
    # reasoning landing in another member's block stays visible, and so does the
    # step numbering, which the two lanes count separately even while the steps
    # they contribute alternate on the wire.
    blocks = [(names[lane] if lane is not None else None, text) for lane, text in _reasoning_blocks_in_order(events)]
    assert blocks == [
        (
            "Researcher",
            "## Step 1: researcher plan\nresearcher is thinking\n\n"
            "## Step 2: researcher check\nresearcher is checking\n\n",
        ),
        (
            "Writer",
            "## Step 1: writer plan\nwriter is thinking\n\n## Step 2: writer check\nwriter is checking\n\n",
        ),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_two_members_reasoning_at_once_keep_a_reasoning_span_each(collect):
    """Neither lane's reasoning span is closed by the other lane's steps arriving.

    The two spans are open together and their steps alternate on the wire, so a
    lane switch that ended whichever span was current would split each member's
    reasoning into two blocks and interleave the pieces. The shared checker
    holds every delta to the span it names, which such a stream still satisfies.
    """
    events = await collect(_reasoning_team_chunks(), attributed())

    assert_stream_contains(events, EventType.REASONING_MESSAGE_CONTENT, 4)
    # One reasoning span per lane, holding both of that lane's steps, and the
    # same shape on both lanes so neither is the other's leftovers.
    for lane in ("run-1", "run-2"):
        assert _lane_sequence(events, lane) == [
            "SUBAGENT_STARTED",
            "RAW",
            "REASONING_START",
            "REASONING_MESSAGE_START",
            "REASONING_MESSAGE_CONTENT",
            "REASONING_MESSAGE_CONTENT",
            "REASONING_MESSAGE_END",
            "REASONING_END",
            "TEXT_MESSAGE_START",
            "TEXT_MESSAGE_CONTENT",
            "TEXT_MESSAGE_END",
            "SUBAGENT_FINISHED",
        ], lane


def _streamed_reasoning_chunks() -> List[Any]:
    """A member whose reasoning arrives as deltas rather than as whole steps.

    A model that streams its reasoning takes this path instead of the step path,
    and it opens the reasoning span itself rather than being told to.
    """
    member = _member_kwargs("scout", "run-scout")

    def delta(text: str) -> ReasoningContentDeltaEvent:
        chunk = ReasoningContentDeltaEvent(**member)
        chunk.reasoning_content = text
        return chunk

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        delta("first I "),
        delta("then I"),
        RunCompletedEvent(content="scout done", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_streamed_reasoning_deltas_are_attributed_to_the_member_that_streamed_them(collect):
    events = await collect(_streamed_reasoning_chunks(), attributed())

    assert_stream_contains(events, EventType.REASONING_MESSAGE_CONTENT, 2)
    # One span opened by the first delta, both deltas inside it, all on the
    # member's lane, and ordered so a delta emitted twice stays visible.
    assert in_emitted_order(events, EventType.REASONING_MESSAGE_CONTENT, "delta", _lane) == [
        ("first I ", "run-scout"),
        ("then I", "run-scout"),
    ]
    assert in_emitted_order(events, EventType.REASONING_START, _lane) == [("run-scout",)]
    assert _lane_sequence(events, "run-scout") == [
        "SUBAGENT_STARTED",
        "RAW",
        "REASONING_START",
        "REASONING_MESSAGE_START",
        "REASONING_MESSAGE_CONTENT",
        "REASONING_MESSAGE_CONTENT",
        "REASONING_MESSAGE_END",
        "REASONING_END",
        "SUBAGENT_FINISHED",
    ]


def _text_then_reasoning_and_tool_chunks() -> List[Any]:
    """A member that is mid-sentence when it starts reasoning, and again when it calls a tool."""
    member = _member_kwargs("scout", "run-scout")
    scout_tool = ToolExecution(tool_call_id="tc-scout-lookup", tool_name="lookup", tool_args={"q": "x"}, result="found")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        _agent_said("Let me think.", **member),
        ReasoningStartedEvent(**member),
        _reasoning_step("scout plan", "scout is thinking", **member),
        ReasoningCompletedEvent(**member),
        _agent_said("Now I will look it up.", **member),
        ToolCallStartedEvent(tool=scout_tool, **member),
        ToolCallCompletedEvent(tool=scout_tool, **member),
        RunCompletedEvent(content="scout done", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_lanes_open_text_message_is_closed_before_its_reasoning_or_tool_calls(collect):
    events = await collect(_text_then_reasoning_and_tool_chunks(), attributed())

    assert_stream_contains(events, EventType.REASONING_MESSAGE_CONTENT)
    assert_stream_contains(events, EventType.TOOL_CALL_START)
    # The member lane in full: each open text message is ended by the reasoning
    # or tool call that follows it, rather than staying open around it.
    assert _lane_sequence(events, "run-scout") == [
        "SUBAGENT_STARTED",
        "RAW",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "REASONING_START",
        "REASONING_MESSAGE_START",
        "REASONING_MESSAGE_CONTENT",
        "REASONING_MESSAGE_END",
        "REASONING_END",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
        "SUBAGENT_FINISHED",
    ]


@needs_lineage_events
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunk_factory",
    [_reasoning_team_chunks, _text_then_reasoning_and_tool_chunks],
    ids=["two_members_reasoning", "one_member_interleaving"],
)
@chunk_mappers
async def test_no_lane_ever_holds_a_reasoning_or_tool_event_inside_an_open_text_message(collect, chunk_factory):
    events = await collect(chunk_factory(), attributed())

    assert_stream_contains(events, EventType.REASONING_MESSAGE_START)
    assert_stream_contains(events, EventType.TOOL_CALL_START)
    open_in_lane: Dict[Optional[str], bool] = {}
    for event in events:
        lane = _lane(event)
        if event.type == EventType.TEXT_MESSAGE_START:
            open_in_lane[lane] = True
        elif event.type == EventType.TEXT_MESSAGE_END:
            open_in_lane[lane] = False
        elif str(event.type).rsplit(".", 1)[-1].startswith(("REASONING_", "TOOL_CALL_")):
            assert not open_in_lane.get(lane), f"{event.type} arrived inside an open text message in lane {lane}"


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_member_and_leader_text_never_share_a_message(collect_entity):
    """Inline joins the leader's reply to the message the last member left open; attributed does not.

    The shared checker holds every delta to the member its own span was opened
    in, so the leader's words written into a member's message and stamped with
    that member would satisfy it. What refuses that shape is the pair of
    streams read together: inline really does put the two in one bubble, which
    is what makes the split under attributed a change rather than a restatement.
    """
    inline = await collect_entity(_two_member_team(InMemoryDb()), SUBAGENT_VISIBILITY_INLINE)
    events = await collect_entity(_two_member_team(InMemoryDb()), attributed())

    assert_stream_contains(events, EventType.TEXT_MESSAGE_CONTENT, 3)
    assert joined_text_in_emitted_order(inline)[-1] == (None, "Here is the brief.Final synthesis.")
    assert _messages_in_order(events)[-2:] == [("Writer", "Here is the brief."), (None, "Final synthesis.")]


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_subagent_started_links_back_to_its_delegation(collect_entity):
    events = await collect_entity(_two_member_team(InMemoryDb()), attributed())
    assert_stream_contains(events, EventType.SUBAGENT_STARTED, 2)
    started = _announcements(events)
    parent_of_tool_call = {
        e.tool_call_id: e.parent_message_id  # type: ignore[attr-defined]
        for e in _of_type(events, EventType.TOOL_CALL_START)
    }

    # One announcement per delegation, in the order the leader delegated, and
    # neither has a parent subagent because the top-level team delegated to both.
    assert [
        (e.name, e.description, e.parent_tool_call_id, e.parent_subagent_run_id)  # type: ignore[attr-defined]
        for e in started
    ] == [
        ("Researcher", "research the topic", "tc-delegate-researcher", None),
        ("Writer", "write the brief", "tc-delegate-writer", None),
    ]
    # The delegation's own parent message, which has to be a message this stream
    # really opened: read back as None on both sides, this compares nothing.
    parents = [parent_of_tool_call["tc-delegate-researcher"], parent_of_tool_call["tc-delegate-writer"]]
    lane_of_message = _lane_of_message_id(events)
    assert all(parent in lane_of_message for parent in parents), (parents, sorted(lane_of_message))
    assert in_emitted_order(events, EventType.SUBAGENT_STARTED, "parent_message_id") == [
        (parent,) for parent in parents
    ]


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_each_subagent_gets_exactly_one_terminal_carrying_its_result(collect_entity):
    events = await collect_entity(_two_member_team(InMemoryDb()), attributed())
    names = _lane_names(events)
    assert_stream_contains(events, EventType.SUBAGENT_FINISHED, 2)
    finished = _of_type(events, EventType.SUBAGENT_FINISHED)

    assert [(names[e.subagent_run_id], e.result) for e in finished] == [  # type: ignore[attr-defined]
        ("Researcher", "Found three sources."),
        ("Writer", "Here is the brief."),
    ]
    assert not _of_type(events, EventType.SUBAGENT_ERROR)


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_a_members_terminal_goes_out_before_its_delegation_reports_a_result(collect_entity):
    """The member's card resolves before the leader's delegation renders what it returned.

    The shared checker orders a member's own events against its own terminal,
    and a child's terminal against its parent's. Neither says where that
    terminal sits relative to the leader's own tool call, which is what decides
    whether a client sees the member close before the result reporting it
    arrives, and before the next member is announced under the same leader.
    """
    events = await collect_entity(_two_member_team(InMemoryDb()), attributed())
    assert_stream_contains(events, EventType.SUBAGENT_FINISHED, 2)
    names = _lane_names(events)

    def described(event: BaseEvent) -> Optional[str]:
        lane = _lane(event)
        return names[lane] if lane is not None else getattr(event, "tool_call_id", None)

    lifecycle = [
        (str(event.type).removeprefix("EventType."), described(event))
        for event in events
        if event.type == EventType.SUBAGENT_STARTED
        or _is_terminal(event)
        or (_lane(event) is None and event.type in (EventType.TOOL_CALL_END, EventType.TOOL_CALL_RESULT))
    ]
    assert lifecycle == [
        ("SUBAGENT_STARTED", "Researcher"),
        ("SUBAGENT_FINISHED", "Researcher"),
        ("TOOL_CALL_END", "tc-delegate-researcher"),
        ("TOOL_CALL_RESULT", "tc-delegate-researcher"),
        ("SUBAGENT_STARTED", "Writer"),
        ("SUBAGENT_FINISHED", "Writer"),
        ("TOOL_CALL_END", "tc-delegate-writer"),
        ("TOOL_CALL_RESULT", "tc-delegate-writer"),
    ]


# --- Nesting ----------------------------------------------------------------


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_nested_team_reports_the_full_parent_chain(collect_entity):
    db = InMemoryDb()
    scout = Agent(
        name="Scout",
        id="scout",
        model=ScriptedModel(
            "m-scout",
            [("tool", "search_docs", {"query": "x"}, "tc-scout"), ("content", "Scout done.")],
        ),
        tools=[search_docs],
        db=db,
        telemetry=False,
    )
    inner = Team(
        name="Inner Team",
        id="inner-team",
        model=ScriptedModel(
            "m-inner",
            [
                ("tool", "delegate_task_to_member", {"member_id": "scout", "task": "scout it"}, "tc-inner"),
                ("content", "Inner done."),
            ],
        ),
        members=[scout],
        db=db,
        telemetry=False,
    )
    outer = _team(db, [inner], [({"member_id": "inner-team", "task": "run inner"}, "tc-outer")])

    events = await collect_entity(outer, attributed())
    assert_stream_contains(events, EventType.SUBAGENT_STARTED, 2)
    started = _announcements(events)
    # A mapping is the right shape here: it resolves a member name to the run id
    # the expected values below are written against, and the ordered assertions
    # that follow are what would catch two members sharing a name.
    lane_named = {e.name: e.subagent_run_id for e in started}  # type: ignore[attr-defined]

    assert [
        (e.name, e.parent_subagent_run_id, e.parent_tool_call_id, e.description)  # type: ignore[attr-defined]
        for e in started
    ] == [
        ("Inner Team", None, "tc-outer", "run inner"),
        ("Scout", lane_named["Inner Team"], "tc-inner", "scout it"),
    ]

    finished = [e.subagent_run_id for e in _of_type(events, EventType.SUBAGENT_FINISHED)]  # type: ignore[attr-defined]
    assert finished == [lane_named["Scout"], lane_named["Inner Team"]]


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_parallel_delegation_keeps_each_member_in_its_own_lane(collect_entity):
    db = InMemoryDb()
    team = Team(
        name="Research Team",
        id="research-team",
        model=ScriptedModel(
            "m-leader",
            [
                ("tool", "delegate_task_to_members", {"task": "both of you work"}, "tc-broadcast"),
                ("content", "Final synthesis."),
            ],
        ),
        members=[_researcher(db), _writer(db)],
        delegate_to_all_members=True,
        db=db,
        telemetry=False,
    )

    events = await collect_entity(team, attributed())
    assert_stream_contains(events, EventType.SUBAGENT_STARTED, 2)
    said = [entry for entry in _messages_in_order(events) if entry[1]]

    # This path runs the members as concurrent tasks merged through one queue, so
    # which of the two lanes reaches the wire first is the scheduler's and not a
    # promise. What is promised holds per lane: each member's own words arrive
    # whole in its own lane, and the leader's reply is the run's last word.
    assert sorted(entry for entry in said if entry[0] is not None) == [
        ("Researcher", "Found three sources."),
        ("Writer", "Here is the brief."),
    ]
    assert [entry for entry in said if entry[0] is None] == [(None, "Final synthesis.")]
    assert said[-1] == (None, "Final synthesis."), "the leader replied before both members had spoken"
    # Each member gets its own announcement rather than one shared between them.
    # The broadcast call names no member, so neither is linked to it: the link
    # is only reported off a delegation that says which member it spawned.
    assert sorted(
        in_emitted_order(events, EventType.SUBAGENT_STARTED, "name", "parent_tool_call_id", "description")
    ) == [
        ("Researcher", None, None),
        ("Writer", None, None),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_the_same_member_delegated_twice_occupies_two_lanes(collect_entity):
    db = InMemoryDb()
    scout = Agent(
        name="Scout",
        id="scout",
        model=ScriptedModel("m-scout", [("content", "done: scout the north"), ("content", "done: scout the south")]),
        db=db,
        telemetry=False,
    )
    team = _team(
        db,
        [scout],
        [
            ({"member_id": "scout", "task": "scout the north"}, "tc-first"),
            ({"member_id": "scout", "task": "scout the south"}, "tc-second"),
        ],
    )

    events = await collect_entity(team, attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED, 2)
    assert_stream_contains(events, EventType.SUBAGENT_FINISHED, 2)
    # One invocation is one lane, and the framework mints a run id per
    # delegation: keyed by name or by member id these would be one entry.
    announced = in_emitted_order(
        events, EventType.SUBAGENT_STARTED, "subagent_run_id", "name", "description", "parent_tool_call_id"
    )
    assert [row[1:] for row in announced] == [
        ("Scout", "scout the north", "tc-first"),
        ("Scout", "scout the south", "tc-second"),
    ]
    first, second = [row[0] for row in announced]
    assert first != second, "both delegations to one member were reported under a single run id"
    assert in_emitted_order(events, EventType.SUBAGENT_FINISHED, "subagent_run_id", "result") == [
        (first, "done: scout the north"),
        (second, "done: scout the south"),
    ]


# --- Failure paths ----------------------------------------------------------


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_a_failing_member_is_errored_and_the_team_run_still_finishes(collect_entity):
    db = InMemoryDb()
    broken = Agent(
        name="Broken",
        id="broken",
        model=ScriptedModel("m-broken", [], fail_with="member exploded"),
        db=db,
        telemetry=False,
    )
    team = _team(db, [broken], [({"member_id": "broken", "task": "break"}, "tc-delegate-broken")])

    events = await collect_entity(team, attributed())
    names = _lane_names(events)
    assert_stream_contains(events, EventType.SUBAGENT_ERROR)
    errors = _of_type(events, EventType.SUBAGENT_ERROR)

    assert [names[e.subagent_run_id] for e in errors] == ["Broken"]  # type: ignore[attr-defined]
    assert "member exploded" in errors[0].message  # type: ignore[attr-defined]
    # A lane that errored is not also reported as finished.
    assert not _of_type(events, EventType.SUBAGENT_FINISHED)
    # The leader recovered from its member's failure, so the run itself finished.
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)
    assert (None, "Final synthesis.") in _messages_in_order(events)


def _run_error_with_open_lanes_chunks(message: str) -> List[Any]:
    """A nested team and its member are both mid-run when the top-level run fails."""
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    member = _member_kwargs("scout", "run-scout", parent="run-inner")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamRunStartedEvent(**inner),
        RunStartedEvent(**member),
        _agent_said("half a sen", **member),
        TeamRunErrorEvent(content=message, error_type="RuntimeError", **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_run_that_errors_closes_every_open_member_lane_deepest_first(collect):
    events = await collect(_run_error_with_open_lanes_chunks("team blew up"), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_ERROR, 2)
    assert_stream_contains(events, EventType.RUN_ERROR)
    # The member's own span closes, then the lanes error child before parent, and
    # the run terminal is last with nothing after it.
    assert [(str(e.type).removeprefix("EventType."), _lane(e), getattr(e, "message", None)) for e in events[-4:]] == [
        ("TEXT_MESSAGE_END", "run-scout", None),
        ("SUBAGENT_ERROR", "run-scout", "team blew up"),
        ("SUBAGENT_ERROR", "run-inner", "team blew up"),
        ("RUN_ERROR", None, "team blew up"),
    ]
    assert [e.code for e in _of_type(events, EventType.RUN_ERROR)] == ["RuntimeError"]  # type: ignore[attr-defined]
    # Errored lanes are never also reported as finished.
    assert not _of_type(events, EventType.SUBAGENT_FINISHED)


_A_CHILD_RESOLVED_AFTER_ITS_PARENT = "terminated after its parent"


def _assert_the_child_resolved_after_its_parent(violation: Optional[str]) -> None:
    """The one thing a member's own terminal cannot put in order, stated once.

    A member's terminal terminates that member and nothing else, so a run whose
    source says a parent finished while its child was still streaming puts the
    child's terminal after its parent's. The alternatives were both worse and
    both reproduced defects: terminating the child from the parent's terminal
    sent a terminal for a member that was still working, with no result, after
    which the child's own completion was read as a repeat and dropped; holding
    the parent's terminal back would report the parent as running after its own
    run said otherwise.

    Pinned as a violation rather than exempted: the shared checker still calls
    such a stream malformed, which is the honest verdict on a source that
    reported those two things in that order.
    """
    assert violation is not None, "a child resolving after its parent passed as a well-formed stream"
    assert _A_CHILD_RESOLVED_AFTER_ITS_PARENT in violation, violation


def _parent_lane_terminates_first_chunks(fail: bool) -> List[Any]:
    """A sub-team reaches its own terminal with two generations still open below it.

    Two, at different depths, because with a single open descendant the order
    the run-end drain puts them in is whatever order one element comes in:
    reversing it would still pass.
    """
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    middle = _team_kwargs("middle-team", "Middle Team", "run-middle", parent="run-inner")
    member = _member_kwargs("scout", "run-scout", parent="run-middle")
    parent_terminal = (
        TeamRunErrorEvent(content="inner exploded", error_type="RuntimeError", **inner)
        if fail
        else TeamRunCompletedEvent(content="inner done", **inner)
    )

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamRunStartedEvent(**inner),
        TeamRunStartedEvent(**middle),
        RunStartedEvent(**member),
        _agent_said("scouting", **member),
        parent_terminal,
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fail,terminal",
    [(False, "SUBAGENT_FINISHED"), (True, "SUBAGENT_ERROR")],
    ids=["finished", "errored"],
)
@malformed_mappers
async def test_a_members_own_terminal_terminates_only_that_member(collect_malformed, fail, terminal):
    """The generations below it are still running, so the run end is what terminates them.

    Neither of them is finished or errored here, which is what keeps a member
    that never failed from carrying the failure above it and keeps a member that
    is still working from being reported as done with nothing to show.
    """
    events, error, violation = await collect_malformed(
        _parent_lane_terminates_first_chunks(fail),
        attributed(),
        thread_id=THREAD_ID,
        run_id=TOP_LEVEL_RUN,
    )

    assert error is None, f"the source stream raised {error!r}"
    terminals = [
        (str(e.type).removeprefix("EventType."), e.subagent_run_id)  # type: ignore[attr-defined]
        for e in events
        if str(e.type).removeprefix("EventType.") in {"SUBAGENT_FINISHED", "SUBAGENT_ERROR"}
    ]
    # Only the lane whose run reported the terminal takes it. The two below it
    # are drained by the run end, deepest first, as plain completions.
    assert terminals == [
        (terminal, "run-inner"),
        ("SUBAGENT_FINISHED", "run-scout"),
        ("SUBAGENT_FINISHED", "run-middle"),
    ]
    _assert_the_child_resolved_after_its_parent(violation)


def _open_lanes_at_run_end_chunks() -> List[Any]:
    """A nested team and its member never reach their own terminals."""
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    member = _member_kwargs("scout", "run-scout", parent="run-inner")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamRunStartedEvent(**inner),
        RunStartedEvent(**member),
        _agent_said("scouting", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_the_run_end_drain_terminates_open_member_lanes_deepest_first(collect):
    events = await collect(_open_lanes_at_run_end_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_FINISHED, 2)
    # The drain closes the child before its parent and the run terminal is last,
    # with nothing after it.
    assert [(str(e.type).removeprefix("EventType."), _lane(e)) for e in events[-3:]] == [
        ("SUBAGENT_FINISHED", "run-scout"),
        ("SUBAGENT_FINISHED", "run-inner"),
        ("RUN_FINISHED", None),
    ]
    # A lane the run terminated carries no result: the member never reported one.
    # Read as a declared field, so a renamed or removed result field is a failure
    # here rather than two Nones comparing equal.
    assert in_emitted_order(events, EventType.SUBAGENT_FINISHED, "subagent_run_id", "result") == [
        ("run-scout", None),
        ("run-inner", None),
    ]
    assert not _of_type(events, EventType.SUBAGENT_ERROR)


def _two_lanes_holding_a_message_and_a_tool_call_chunks() -> List[Any]:
    """A sub-team and its member each reach the run end mid-sentence with a call still open.

    The tool call goes out before the words in each lane, and the lane has no
    message open when it does: the call opens an empty parent message of its own
    and closes it in the same breath, and the words that follow open a second
    one. Given the other way round the call would close the message the words
    opened, and only the call would still be open when the run ends, which is
    not the two-spans-per-lane shape this run end is about.
    """
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    member = _member_kwargs("scout", "run-scout", parent="run-inner")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamRunStartedEvent(**inner),
        RunStartedEvent(**member),
        TeamToolCallStartedEvent(tool=ToolExecution(tool_call_id="tc-inner-plan", tool_name="plan"), **inner),
        _team_said("inner speaking", **inner),
        ToolCallStartedEvent(tool=ToolExecution(tool_call_id="tc-scout-look", tool_name="look"), **member),
        _agent_said("scout speaking", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_the_run_end_closes_every_lanes_messages_then_its_tool_calls_then_terminates_it(collect):
    """One sweep per kind across all lanes, rather than one lane emptied at a time.

    Emptying a lane at a time would put the deeper lane's terminal ahead of the
    shallower lane's message end, which lands a terminal inside another lane's
    open span, and would put a member's terminal ahead of the tool call end it
    is still holding. Both orders are ones the shared checker accepts.
    """
    events = await collect(_two_lanes_holding_a_message_and_a_tool_call_chunks(), attributed())

    assert_stream_contains(events, EventType.TOOL_CALL_END, 2)
    assert [(str(e.type).removeprefix("EventType."), _lane(e)) for e in events[-7:]] == [
        ("TEXT_MESSAGE_END", "run-scout"),
        ("TEXT_MESSAGE_END", "run-inner"),
        ("TOOL_CALL_END", "run-scout"),
        ("TOOL_CALL_END", "run-inner"),
        ("SUBAGENT_FINISHED", "run-scout"),
        ("SUBAGENT_FINISHED", "run-inner"),
        ("RUN_FINISHED", None),
    ]
    # The ends name the calls each lane really opened, so the pairing above is
    # not two ends of one lane's making.
    assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id", _lane) == [
        ("tc-scout-look", "run-scout"),
        ("tc-inner-plan", "run-inner"),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_tool_call_opened_after_its_members_terminal_is_still_closed(collect):
    member = _member_kwargs("scout", "run-scout")
    late = ToolExecution(tool_call_id="tc-late", tool_name="cleanup", tool_args={})

    chunks = [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        RunCompletedEvent(content="scout done", **member),
        # Output trailing the member's own terminal: the lane is closed but the
        # tool call it opens still has to be ended before the run terminal.
        ToolCallStartedEvent(tool=late, **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]

    events = await collect(chunks, attributed(), exempt=[TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL])

    assert_stream_contains(events, EventType.TOOL_CALL_END)
    assert _tool_call_lanes_in_order(events) == [("tc-late", "run-scout")]
    assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id", _lane) == [("tc-late", "run-scout")]
    # A terminal is final for the lane it names, so the trailing output does not
    # earn the member a second one.
    assert [e.subagent_run_id for e in _of_type(events, EventType.SUBAGENT_FINISHED)] == ["run-scout"]  # type: ignore[attr-defined]
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)


def _member_content_after_its_terminal_chunks() -> List[Any]:
    """A member says one more thing after its own terminal, while its delegation is still open."""
    delegation = _delegation("tc-delegate-scout", "scout", "scout the topic", result="scout done")
    member = _member_kwargs("scout", "run-scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=delegation),
        RunStartedEvent(**member),
        RunCompletedEvent(content="scout done", **member),
        _agent_said("one more thing", **member),
        TeamToolCallCompletedEvent(run_id=TOP_LEVEL_RUN, tool=delegation),
        _team_said("Final synthesis.", **_TOP_LEVEL),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_content_trailing_a_members_terminal_stays_attributed_without_holding_a_span_open(collect):
    events = await collect(
        _member_content_after_its_terminal_chunks(),
        attributed(),
        exempt=[TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL],
    )

    assert_stream_contains(events, EventType.TOOL_CALL_RESULT)
    # The attribution is kept: the trailing text is still the member's.
    assert _messages_in_order(events) == [(None, ""), ("Scout", "one more thing"), (None, "Final synthesis.")]
    trailing = [e for e in _of_type(events, EventType.TEXT_MESSAGE_START) if _lane(e) == "run-scout"]
    assert len(trailing) == 1
    closed_at = [
        index
        for index, event in enumerate(events)
        if event.type == EventType.TEXT_MESSAGE_END and event.message_id == trailing[0].message_id  # type: ignore[attr-defined]
    ]
    result_at = [index for index, event in enumerate(events) if event.type == EventType.TOOL_CALL_RESULT]
    assert closed_at and result_at
    assert closed_at[0] < result_at[0], (
        "the member's trailing message was still open when the leader's tool result arrived, "
        "so a client renders that result inside the member's bubble"
    )


def _closed_lane_trailing_spans_chunks() -> List[Any]:
    """A member and its sub-team both emit new spans after their own run completed."""
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    member = _member_kwargs("scout", "run-scout", parent="run-inner")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamRunStartedEvent(**inner),
        RunStartedEvent(**member),
        RunCompletedEvent(content="scout done", **member),
        TeamRunCompletedEvent(content="inner done", **inner),
        # Trailing output from lanes whose own terminal has already been emitted.
        ReasoningStartedEvent(**member),
        _agent_said("scout afterword", **member),
        _team_said("inner afterword", **inner),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_no_lane_is_left_with_an_open_span_at_the_end_of_the_run(collect_entity):
    events = await collect_entity(_two_member_team(InMemoryDb()), attributed())
    assert_stream_contains(events, EventType.TEXT_MESSAGE_START, 3)
    assert_stream_contains(events, EventType.TOOL_CALL_START, 4)
    _assert_every_span_closed(events)


@needs_lineage_events
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunk_factory,reasoning_spans,exempt",
    [
        (_reasoning_team_chunks, 2, ()),
        (_text_then_reasoning_and_tool_chunks, 1, ()),
        (_open_lanes_at_run_end_chunks, 0, ()),
        # This one streams chunks from members whose own runs already completed,
        # so its stamped events deliberately outlive their member terminals.
        (_closed_lane_trailing_spans_chunks, 1, (TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL,)),
    ],
    ids=["two_members_reasoning", "one_member_interleaving", "open_lanes_at_run_end", "trailing_spans"],
)
@chunk_mappers
async def test_every_reasoning_and_message_span_is_closed_before_the_run_ends(
    collect, chunk_factory, reasoning_spans, exempt
):
    events = await collect(chunk_factory(), attributed(), exempt=exempt)
    # How much reasoning this particular stream carries is stated per case, as a
    # count, so the case that carries none says so rather than stating a bound
    # that holds for every stream there is.
    assert_stream_contains(events, EventType.TEXT_MESSAGE_START)
    assert_stream_carries_exactly(events, EventType.REASONING_START, reasoning_spans)
    _assert_every_span_closed(events)


def _assert_every_span_closed(events: List[BaseEvent]) -> None:
    """Every span the stream opened was closed, by id, before the run terminal."""
    for start, end in (
        (EventType.TEXT_MESSAGE_START, EventType.TEXT_MESSAGE_END),
        (EventType.REASONING_START, EventType.REASONING_END),
        (EventType.REASONING_MESSAGE_START, EventType.REASONING_MESSAGE_END),
    ):
        opened, closed = _span_pairs(events, start, end)
        assert sorted(opened) == sorted(closed), f"{start} ids {opened} do not match {end} ids {closed}"

    open_tool_calls = [e.tool_call_id for e in _of_type(events, EventType.TOOL_CALL_START)]  # type: ignore[attr-defined]
    ended_tool_calls = [e.tool_call_id for e in _of_type(events, EventType.TOOL_CALL_END)]  # type: ignore[attr-defined]
    assert sorted(open_tool_calls) == sorted(ended_tool_calls)

    # A conforming client rejects a run that ends inside a span, so the terminal
    # really is the last thing on the wire.
    assert str(events[-1].type) in {str(EventType.RUN_FINISHED), str(EventType.RUN_ERROR)}


# --- Visibility -------------------------------------------------------------

# The stream a two-member Team produced before lineage existed. Under the default
# inline visibility it must still be exactly this.
_INLINE_TEAM_SEQUENCE = [
    "EventType.RAW",  # TeamRunStarted
    "EventType.RAW",  # TeamModelRequestStarted
    "EventType.RAW",  # TeamModelRequestCompleted
    "EventType.TEXT_MESSAGE_START",  # empty parent for the first delegation
    "EventType.TEXT_MESSAGE_END",
    "EventType.TOOL_CALL_START",  # delegate to Researcher
    "EventType.TOOL_CALL_ARGS",
    "EventType.RAW",  # Researcher RunStarted
    "EventType.RAW",  # Researcher ModelRequestStarted
    "EventType.RAW",  # Researcher ModelRequestCompleted
    "EventType.TOOL_CALL_START",  # search_docs
    "EventType.TOOL_CALL_ARGS",
    "EventType.TOOL_CALL_END",
    "EventType.TOOL_CALL_RESULT",
    "EventType.RAW",  # Researcher ModelRequestStarted
    "EventType.TEXT_MESSAGE_START",
    "EventType.TEXT_MESSAGE_CONTENT",  # "Found three sources."
    "EventType.RAW",  # Researcher ModelRequestCompleted
    "EventType.RAW",  # Researcher RunContentCompleted
    "EventType.TOOL_CALL_END",  # delegation to Researcher returns
    "EventType.TOOL_CALL_RESULT",
    "EventType.RAW",  # TeamModelRequestStarted
    "EventType.RAW",  # TeamModelRequestCompleted
    "EventType.TEXT_MESSAGE_END",
    "EventType.TOOL_CALL_START",  # delegate to Writer
    "EventType.TOOL_CALL_ARGS",
    "EventType.RAW",  # Writer RunStarted
    "EventType.RAW",  # Writer ModelRequestStarted
    "EventType.RAW",  # Writer ModelRequestCompleted
    "EventType.TOOL_CALL_START",  # spell_check
    "EventType.TOOL_CALL_ARGS",
    "EventType.TOOL_CALL_END",
    "EventType.TOOL_CALL_RESULT",
    "EventType.RAW",  # Writer ModelRequestStarted
    "EventType.TEXT_MESSAGE_START",
    "EventType.TEXT_MESSAGE_CONTENT",  # "Here is the brief."
    "EventType.RAW",  # Writer ModelRequestCompleted
    "EventType.RAW",  # Writer RunContentCompleted
    "EventType.TOOL_CALL_END",  # delegation to Writer returns
    "EventType.TOOL_CALL_RESULT",
    "EventType.RAW",  # TeamModelRequestStarted
    "EventType.TEXT_MESSAGE_CONTENT",  # the leader's reply joins the Writer's message
    "EventType.RAW",  # TeamModelRequestCompleted
    "EventType.RAW",  # TeamRunContentCompleted
    "EventType.TEXT_MESSAGE_END",
    "EventType.RUN_FINISHED",
]


@pytest.mark.asyncio
@entity_mappers
async def test_inline_is_the_default_and_leaves_the_team_stream_unchanged(collect_entity):
    default_events = await collect_entity(_two_member_team(InMemoryDb()))
    inline_events = await collect_entity(_two_member_team(InMemoryDb()), SUBAGENT_VISIBILITY_INLINE)

    assert _type_sequence(default_events) == _INLINE_TEAM_SEQUENCE
    assert _normalized_payloads(default_events) == _normalized_payloads(inline_events)
    assert all(_lane(e) is None for e in default_events)
    assert not [e for e in default_events if "SUBAGENT" in str(e.type)]


@pytest.mark.asyncio
@malformed_mappers
async def test_the_default_keeps_the_duplicate_prompt_a_paused_tool_listed_twice_produced(collect_malformed):
    """Part of the same claim: the default stream is what it was, defect and all.

    The fixture has to carry a tool listed twice or the claim is vacuous: before
    member attribution existed a paused tool was prompted once per listing,
    duplicate tool call id and all. That duplicate is a defect the default keeps
    rather than a stream the default is allowed to change, which is why it is
    pinned here as the invariant violation it is.
    """

    async def paused(visibility):
        return await collect_malformed(
            _paused_tool_listed_in_both_places_chunks(),
            visibility,
            thread_id=THREAD_ID,
            run_id=TOP_LEVEL_RUN,
        )

    default_paused, default_error, violation = await paused(None)
    inline_paused, inline_error, inline_violation = await paused(SUBAGENT_VISIBILITY_INLINE)

    assert default_error is None and inline_error is None
    assert _normalized_payloads(default_paused) == _normalized_payloads(inline_paused)
    assert in_emitted_order(default_paused, EventType.TOOL_CALL_START, "tool_call_id", _lane) == [
        ("tc-shared-confirm", None),
        ("tc-shared-confirm", None),
    ]
    # The duplicate itself is pinned above, in order. This states that the
    # shared checker still calls such a stream malformed, without pinning the
    # sentence it says so in.
    assert violation is not None and "tc-shared-confirm" in violation
    assert inline_violation == violation


@pytest.mark.asyncio
@entity_mappers
async def test_hidden_withholds_member_internals_but_keeps_the_delegation(collect_entity):
    events = await collect_entity(_two_member_team(InMemoryDb()), SUBAGENT_VISIBILITY_HIDDEN)

    # Only the leader's own delegations, only the leader's own reply, and nothing
    # a member produced: no member tool call, no member text, no lineage at all.
    assert_stream_contains(events, EventType.TOOL_CALL_RESULT, 2)
    assert _tool_call_lanes_in_order(events) == [("tc-delegate-researcher", None), ("tc-delegate-writer", None)]
    # The empty entry is the assistant message the delegation calls are parented
    # to; ordered, so it stays visible rather than being folded away by content.
    assert _messages_in_order(events) == [(None, ""), (None, "Final synthesis.")]
    assert in_emitted_order(events, EventType.TOOL_CALL_RESULT, "tool_call_id", lambda e: json.loads(e.content)) == [
        ("tc-delegate-researcher", "Found three sources."),
        ("tc-delegate-writer", "Here is the brief."),
    ]
    assert not [e for e in events if "SUBAGENT" in str(e.type)]
    assert not [e for e in events if _lane(e) is not None]


@pytest.mark.asyncio
@entity_mappers
async def test_hidden_keeps_the_delegation_calls_own_arguments_which_name_the_member(collect_entity):
    """What hidden withholds is the member surface, not the team's own delegation call.

    Those arguments are the team's own work, and the default puts exactly the
    same ones on the wire, so no account of hidden may say nothing reaching the
    client names a member.
    """
    events = await collect_entity(_two_member_team(InMemoryDb()), SUBAGENT_VISIBILITY_HIDDEN)

    assert_stream_contains(events, EventType.TOOL_CALL_ARGS, 2)
    assert in_emitted_order(events, EventType.TOOL_CALL_ARGS, "tool_call_id", lambda e: json.loads(e.delta)) == [
        ("tc-delegate-researcher", {"member_id": "researcher", "task": "research the topic"}),
        ("tc-delegate-writer", {"member_id": "writer", "task": "write the brief"}),
    ]
    # Withheld all the same: nothing tells the client which member produced what.
    assert not [e for e in events if "SUBAGENT" in str(e.type)]
    assert not [e for e in events if _lane(e) is not None]


@pytest.mark.asyncio
@chunk_mappers
async def test_hidden_withholds_a_nested_teams_members_too(collect):
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    member = _member_kwargs("scout", "run-scout", parent="run-inner")
    delegation = _delegation("tc-delegate-inner", "inner-team", "run inner", result="inner finished")
    scout_tool = ToolExecution(tool_call_id="tc-scout-search", tool_name="search_docs", tool_args={"query": "x"})

    chunks = [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=delegation),
        TeamRunStartedEvent(**inner),
        RunStartedEvent(**member),
        ToolCallStartedEvent(tool=scout_tool, **member),
        _agent_said("Scout says hello.", **member),
        _team_said("Inner says hello.", **inner),
        TeamToolCallCompletedEvent(run_id=TOP_LEVEL_RUN, tool=delegation),
        _team_said("Final synthesis.", **_TOP_LEVEL),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]

    events = await collect(chunks, SUBAGENT_VISIBILITY_HIDDEN)

    # Nesting does not earn a grandchild any exposure the direct member lacks.
    assert _tool_call_lanes_in_order(events) == [("tc-delegate-inner", None)]
    # The empty entry is the assistant message the delegation calls are parented
    # to; ordered, so it stays visible rather than being folded away by content.
    assert _messages_in_order(events) == [(None, ""), (None, "Final synthesis.")]
    assert not [e for e in events if _lane(e) is not None]
    assert not [e for e in events if "SUBAGENT" in str(e.type)]
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)


@pytest.mark.asyncio
@entity_mappers
@pytest.mark.parametrize(
    # Resolved inside the test rather than at collection: naming the attributed
    # setting is what skips on a release that cannot serve it.
    "setting",
    [
        lambda: None,
        lambda: SUBAGENT_VISIBILITY_INLINE,
        attributed,
        lambda: SUBAGENT_VISIBILITY_HIDDEN,
    ],
    ids=["default", "inline", "attributed", "hidden"],
)
async def test_a_single_agent_is_unaffected_by_the_visibility_setting(collect_entity, setting):
    """Each setting against the unset default, which is the stream a released client reads.

    The baseline is the setting left unset rather than any named one, so the
    default arm compares that stream with a second run of itself. That arm is
    the run-to-run determinism control the other three rest on rather than a
    claim about the setting: without it a difference between two runs of the
    same code would read as a difference the setting made.
    """
    visibility = setting()
    baseline = await collect_entity(_researcher(InMemoryDb()), prompt="Research agno")
    events = await collect_entity(_researcher(InMemoryDb()), visibility, prompt="Research agno")

    assert _normalized_payloads(events) == _normalized_payloads(baseline)
    assert all(_lane(e) is None for e in events)
    assert not [e for e in events if "SUBAGENT" in str(e.type)]


_SINGLE_AGENT: Dict[str, Any] = {"agent_id": "assistant", "agent_name": "Assistant", "run_id": TOP_LEVEL_RUN}


def _pending(tool_call_id: str, **flags: Any) -> ToolExecution:
    return ToolExecution(tool_call_id=tool_call_id, tool_name="send_email", tool_args={"to": "ops"}, **flags)


def _paused_single_agent_chunks() -> List[Any]:
    """One Agent, no inner agent, pausing on a tool call it already streamed a start for."""
    return [
        RunStartedEvent(**_SINGLE_AGENT),
        ToolCallStartedEvent(tool=_pending("tc-confirm"), **_SINGLE_AGENT),
        AgentRunPausedEvent(
            tools=[_pending("tc-confirm", requires_confirmation=True)], content="Send it?", **_SINGLE_AGENT
        ),
    ]


def _flags_that_list_a_pending_call() -> List[str]:
    """Every ToolExecution flag that puts a pending call on a list the pause prompt reads.

    Asked of the paused event itself, one candidate flag at a time, rather than
    written out here. A flag added to the framework, or a list added to the ones
    the prompt reads, is a new way for one pending call to be reported twice,
    and the cases below are generated from whatever this finds so that such an
    addition arrives already covered instead of quietly widening the gap this
    test exists to close.
    """
    found: List[str] = []
    for candidate in fields(ToolExecution):
        probe = ToolExecution(tool_call_id="probe", tool_name="probe")
        setattr(probe, candidate.name, True)
        paused = AgentRunPausedEvent(tools=[probe])
        if any(getattr(paused, list_name, None) for list_name in handlers._PAUSE_TOOL_LISTS):
            found.append(candidate.name)
    return found


def _ways_one_pending_call_is_reported_twice() -> Dict[str, Callable[[], List[Any]]]:
    """The shapes in which one paused Agent reports the same pending call more than once.

    Two of them are hand-written: a call the run already streamed a start for,
    and two separate pending records sharing one id. The rest are generated,
    one per combination of the flags discovered above, because a call flagged
    for several lists is listed by each of them. Generating that part is what
    makes a flag added to the framework arrive covered; the two hand-written
    shapes are the ones that were reported, and nothing here proves they are
    the only two.
    """
    flags = _flags_that_list_a_pending_call()
    ways: Dict[str, Callable[[], List[Any]]] = {
        "already-streamed": _paused_single_agent_chunks,
        "two-records-one-id": lambda: [
            RunStartedEvent(**_SINGLE_AGENT),
            AgentRunPausedEvent(
                tools=[
                    _pending("tc-twice", requires_confirmation=True),
                    _pending("tc-twice", requires_confirmation=True),
                ],
                **_SINGLE_AGENT,
            ),
        ],
    }
    for size in range(2, len(flags) + 1):
        for combination in combinations(flags, size):
            ways["+".join(combination)] = partial(_paused_on_every_flag, combination)
    return ways


def _paused_on_every_flag(flags: Tuple[str, ...]) -> List[Any]:
    """One Agent pausing on a single pending call carrying several pause flags at once."""
    return [
        RunStartedEvent(**_SINGLE_AGENT),
        AgentRunPausedEvent(
            tools=[_pending("tc-many-flags", **{flag: True for flag in flags})], content="Send it?", **_SINGLE_AGENT
        ),
    ]


_WAYS_REPORTED_TWICE = _ways_one_pending_call_is_reported_twice()


def test_the_pause_prompt_reads_more_than_one_list_of_pending_calls():
    """Otherwise the generated cases below collapse to the two hand-written ones."""
    assert len(_flags_that_list_a_pending_call()) >= 2, (
        "the pause prompt reads one list of pending calls at most, so no generated case reports one twice"
    )


@pytest.mark.parametrize("paused", [AgentRunPausedEvent, TeamRunPausedEvent], ids=["agent", "team"])
def test_every_list_the_pause_prompt_reads_is_one_the_paused_event_carries(paused):
    """A name the event does not carry is read as an empty list, so it has to be checked here.

    The prompt reaches these by name and treats a missing one as no pending
    calls, because a paused run may not be told what the client cannot render
    by raising at it. That tolerance is what makes a misnamed entry silently
    drop everything on that list, which is what this refuses.
    """
    missing = [name for name in handlers._PAUSE_TOOL_LISTS if not hasattr(paused(tools=[]), name)]
    assert not missing, f"{paused.__name__} carries no such list of pending calls: {missing}"


@pytest.mark.asyncio
@malformed_mappers
@pytest.mark.parametrize(
    "setting",
    [lambda: None, attributed, lambda: SUBAGENT_VISIBILITY_HIDDEN],
    ids=["default", "attributed", "hidden"],
)
@pytest.mark.parametrize("way", sorted(_WAYS_REPORTED_TWICE), ids=sorted(_WAYS_REPORTED_TWICE))
async def test_a_paused_single_agent_is_unaffected_by_the_visibility_setting(collect_malformed, setting, way):
    """A run with no member on the wire streams the same events whatever the setting.

    A pause is where that is easiest to lose, and every way one pending call can
    be reported twice is a way to lose it: the prompt de-duplicates by tool call
    id, and a de-duplication the default does not do makes an Agent alone stream
    one thing under the default and another under either lineage setting. So the
    cases are the whole class rather than the one shape that was reported.

    The default's stream here is the duplicate prompt it has always emitted, so
    the shared checker calls it malformed. That is what these settings have to
    match, defect and all, which is why it is driven through the collector that
    records the violation instead of failing on it. The duplicate is asserted on
    the baseline first, so a case that stopped producing one fails here rather
    than passing on three identical well-formed streams.
    """

    async def paused(visibility):
        return await collect_malformed(
            _WAYS_REPORTED_TWICE[way](), visibility, thread_id=THREAD_ID, run_id=TOP_LEVEL_RUN
        )

    baseline, baseline_error, baseline_violation = await paused(SUBAGENT_VISIBILITY_INLINE)
    events, error, violation = await paused(setting())

    assert baseline_error is None and error is None
    prompted = in_emitted_order(baseline, EventType.TOOL_CALL_START, "tool_call_id", _lane)
    assert len(prompted) > len(set(prompted)), f"the {way} case prompts no call twice, so it tests nothing"
    assert _normalized_payloads(events) == _normalized_payloads(baseline)
    assert violation == baseline_violation
    assert not [e for e in events if "SUBAGENT" in str(e.type)]


def test_visibility_is_validated():
    assert validate_subagent_visibility(None) == SUBAGENT_VISIBILITY_INLINE
    assert validate_subagent_visibility(SUBAGENT_VISIBILITY_HIDDEN) == SUBAGENT_VISIBILITY_HIDDEN
    with pytest.raises(ValueError, match="subagent_visibility must be one of"):
        validate_subagent_visibility("loud")


def test_attributed_is_refused_when_the_protocol_lacks_the_lineage_events(monkeypatch):
    """Named without the usual skip: on such a release this is the behavior under test."""
    monkeypatch.setattr(handlers, "SUBAGENT_EVENTS_AVAILABLE", False)
    with pytest.raises(ValueError, match="ag-ui-protocol"):
        validate_subagent_visibility(ATTRIBUTED_EVEN_WHEN_REFUSED)
    # Every other setting keeps working on an older protocol.
    assert validate_subagent_visibility(SUBAGENT_VISIBILITY_HIDDEN) == SUBAGENT_VISIBILITY_HIDDEN


# --- A real member that pauses ----------------------------------------------


@tool(requires_confirmation=True)
def send_email(to: str) -> str:
    return f"emailed {to}"


def _emailer(db: InMemoryDb) -> Agent:
    """A member whose only tool needs a confirmation, so its run really pauses."""
    return Agent(
        name="Emailer",
        id="emailer",
        model=ScriptedModel(
            "m-emailer",
            [("tool", "send_email", {"to": "ops"}, "tc-send"), ("content", "Email sent.")],
        ),
        tools=[send_email],
        db=db,
        telemetry=False,
    )


def _team_whose_member_pauses(db: InMemoryDb) -> Team:
    return _team(db, [_emailer(db)], [({"member_id": "emailer", "task": "email ops"}, "tc-delegate-emailer")])


@needs_lineage_events
@pytest.mark.asyncio
@entity_mappers
async def test_a_real_member_that_pauses_is_prompted_on_its_own_lane(collect_entity):
    """A genuine member pause, from a real team run rather than a hand-built chunk list.

    The framework decides the member's run id here, so the lane is read off the
    announcement rather than written down. What the hand-built pauses still
    cover is the shapes one scripted run cannot produce: a leader and a member
    paused at once, a pause naming a member whose lane already terminated, a
    paused grandchild, and a pause reported only through requirements.
    """
    events = await collect_entity(_team_whose_member_pauses(InMemoryDb()), attributed(), prompt="Email ops")

    announced = _announcements(events)
    assert [(e.name, e.parent_tool_call_id) for e in announced] == [("Emailer", "tc-delegate-emailer")]  # type: ignore[attr-defined]
    lane = announced[0].subagent_run_id  # type: ignore[attr-defined]

    assert_stream_contains(events, EventType.TOOL_CALL_ARGS, 2)
    assert in_emitted_order(events, EventType.TOOL_CALL_ARGS, "tool_call_id", "delta", _lane) == [
        ("tc-delegate-emailer", '{"member_id": "emailer", "task": "email ops"}', None),
        ("tc-send", '{"to": "ops"}', lane),
    ]
    # The pending call is prompted before the lane's own terminal, and pausing
    # is not finishing, so the terminal carries no result.
    assert [(e.subagent_run_id, e.result) for e in _of_type(events, EventType.SUBAGENT_FINISHED)] == [(lane, None)]  # type: ignore[attr-defined]
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)


# --- Over the wire ----------------------------------------------------------


@needs_lineage_events
def test_lineage_reaches_the_wire_through_the_agui_interface():
    """The AGUI constructor option must survive all the way to the SSE stream."""
    from fastapi.testclient import TestClient

    from agno.os import AgentOS
    from agno.os.interfaces.agui import AGUI

    team = _two_member_team(InMemoryDb())
    agent_os = AgentOS(
        id="lineage-os",
        teams=[team],
        interfaces=[AGUI(team=team, subagent_visibility=attributed())],
        telemetry=False,
    )
    client = TestClient(agent_os.get_app())

    response = client.post(
        "/agui",
        json={
            "thread_id": "wire-thread",
            "run_id": "wire-run",
            "state": {"approved": False},
            "messages": [{"id": "m1", "role": "user", "content": "Write a brief"}],
            "tools": [],
            "context": [],
            "forwarded_props": {},
        },
    )
    assert response.status_code == 200

    events = sse_events(response.text)
    # The body is the whole deliverable here, so it has to end the way every
    # other stream in this module ends. Without this the run terminal could go
    # missing from the response and every payload assertion below would still
    # hold on the truncated body.
    types = [event["type"] for event in events]
    assert types[-1] == "RUN_FINISHED", f"the response body does not end on the run terminal: {types[-3:]}"
    assert "RUN_ERROR" not in types, (
        f"the run reached the wire as a failure: {[e for e in events if e['type'] == 'RUN_ERROR']}"
    )

    started = [e for e in events if e["type"] == "SUBAGENT_STARTED"]
    assert [(e["name"], e["parentToolCallId"]) for e in started] == [
        ("Researcher", "tc-delegate-researcher"),
        ("Writer", "tc-delegate-writer"),
    ]

    # A set is the right shape for this one claim: every lane that appears on
    # the wire was announced. Which events carry it is asserted in order below.
    lanes = {e["subagentRunId"] for e in events if e.get("subagentRunId")}
    assert lanes == {e["subagentRunId"] for e in started}

    name_of_lane = {e["subagentRunId"]: e["name"] for e in started}
    deltas: Dict[str, str] = {}
    for event in events:
        if event["type"] == "TEXT_MESSAGE_CONTENT":
            deltas[event["messageId"]] = deltas.get(event["messageId"], "") + event["delta"]
    # Ordered over the message starts, so a member's message never disappears
    # into another's key and an empty parent message stays visible.
    said = [
        (name_of_lane.get(event.get("subagentRunId")), deltas.get(event["messageId"], ""))
        for event in events
        if event["type"] == "TEXT_MESSAGE_START"
    ]
    assert said == [
        (None, ""),
        ("Researcher", ""),
        ("Researcher", "Found three sources."),
        ("Writer", ""),
        ("Writer", "Here is the brief."),
        (None, "Final synthesis."),
    ]

    # A team's session state is one shared document, so state events are left
    # unattributed on purpose: a client filtering by member must not lose state
    # written during a delegation.
    state_events = [e for e in events if e["type"].startswith("STATE_")]
    assert {e["type"] for e in state_events} == {"STATE_SNAPSHOT", "STATE_DELTA"}
    assert [e.get("subagentRunId") for e in state_events] == [None] * len(state_events)
    assert [e["snapshot"]["approved"] for e in state_events if e["type"] == "STATE_SNAPSHOT"] == [False, False]


def test_the_agui_interface_defaults_to_inline():
    from agno.os.interfaces.agui import AGUI

    team = _two_member_team(InMemoryDb())
    assert AGUI(team=team).subagent_visibility == SUBAGENT_VISIBILITY_INLINE
    with pytest.raises(ValueError, match="subagent_visibility must be one of"):
        AGUI(team=team, subagent_visibility="loud")


# --- Lane lifecycle ---------------------------------------------------------


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_spans_opened_after_a_lane_terminated_are_still_closed_before_the_run_ends(collect):
    events = await collect(
        _closed_lane_trailing_spans_chunks(),
        attributed(),
        exempt=[TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL],
    )

    assert_stream_contains(events, EventType.REASONING_END)
    # Ordered on both sides, so a span opened or closed twice cannot hide behind
    # a shared message id.
    assert in_emitted_order(events, EventType.TEXT_MESSAGE_START, "message_id", _lane) == in_emitted_order(
        events, EventType.TEXT_MESSAGE_END, "message_id", _lane
    )
    assert in_emitted_order(events, EventType.TEXT_MESSAGE_START, _lane) == [("run-scout",), ("run-inner",)]

    assert in_emitted_order(events, EventType.REASONING_START, "message_id", _lane) == in_emitted_order(
        events, EventType.REASONING_END, "message_id", _lane
    )
    assert in_emitted_order(events, EventType.REASONING_START, _lane) == [("run-scout",)]

    # A child lane's spans close before its parent's.
    ends = [_lane(e) for e in _of_type(events, EventType.TEXT_MESSAGE_END)]
    assert ends.index("run-scout") < ends.index("run-inner")
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)


def test_closing_the_root_lane_ignores_whichever_lane_is_current():
    state = StreamState(subagent_visibility=attributed(), root_run_id=TOP_LEVEL_RUN)
    state.current_lane = ROOT_LANE
    root_message_id = state.open_text_message()
    state.current_lane = "run-scout"
    state.open_text_message()

    closed = handlers._close_lane_spans(state, ROOT_LANE)

    assert [(str(e.type), e.message_id, _lane(e)) for e in closed] == [  # type: ignore[attr-defined]
        (str(EventType.TEXT_MESSAGE_END), root_message_id, None)
    ]
    # The subagent lane is untouched by a root-lane close.
    assert state.lane("run-scout").text_message_open is True


@needs_lineage_events
def test_open_tool_calls_close_in_the_order_the_run_opened_them():
    """The close order is part of the wire, so it may not be left to set iteration.

    The 24 ids go out interleaved from both ends, lowest then highest then next
    lowest, an order that is neither ascending nor descending and so is not the
    output of sorting them either way. The three orders that would pass without
    the run's own order being kept are refused below before the ids are opened.
    """
    state = StreamState(subagent_visibility=attributed(), root_run_id=TOP_LEVEL_RUN)
    state.current_lane = ROOT_LANE
    ends = [f"tc-{index:02d}" for index in range(24)]
    opened = [ends[index // 2] if index % 2 == 0 else ends[-1 - index // 2] for index in range(24)]
    assert sorted(opened) == ends, "the interleave dropped or repeated an id"
    assert opened != ends, "an ascending sort reproduces this order"
    assert opened != ends[::-1], "a descending sort reproduces this order"
    for tool_call_id in opened:
        state.start_tool_call(tool_call_id)
    assert list(state.active_tool_call_ids) != opened, "this interpreter's set iteration reproduces this order"

    closed = [e.tool_call_id for e in handlers._close_all_lane_spans(state)]  # type: ignore[attr-defined]

    assert closed == opened


@needs_lineage_events
def test_an_open_tool_call_is_closed_even_when_its_lane_holds_no_other_span():
    """The run-end close reaches a lane through the tool call it owns, not only through its spans."""
    state = StreamState(subagent_visibility=attributed(), root_run_id=TOP_LEVEL_RUN)
    state.current_lane = "run-scout"
    state.start_tool_call("tc-only")
    assert state.lanes == {}, "the lane must hold nothing else for this to test what it claims"

    closed = handlers._close_all_lane_spans(state)

    assert [(str(e.type), e.tool_call_id, _lane(e)) for e in closed] == [  # type: ignore[attr-defined]
        (str(EventType.TOOL_CALL_END), "tc-only", "run-scout")
    ]
    assert "tc-only" not in state.active_tool_call_ids


def _paused_member_chunks() -> List[Any]:
    """A member pauses for a confirmation while the leader also has one of its own."""
    member_tool = ToolExecution(
        tool_call_id="tc-member-confirm",
        tool_name="send_email",
        tool_args={"to": "ops"},
        requires_confirmation=True,
    )
    requirement = _requirement(member_tool, "scout", "run-scout")
    leader_tool = ToolExecution(
        tool_call_id="tc-leader-confirm",
        tool_name="publish",
        tool_args={"channel": "blog"},
        requires_confirmation=True,
    )
    member = _member_kwargs("scout", "run-scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        _agent_said("I need approval.", **member),
        AgentRunPausedEvent(tools=[member_tool], **member),
        TeamRunPausedEvent(tools=[leader_tool], requirements=[requirement], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_member_gets_one_plain_terminal_after_all_of_its_events(collect):
    events = await collect(_paused_member_chunks(), attributed())
    assert_stream_contains(events, EventType.SUBAGENT_FINISHED)
    finished = _of_type(events, EventType.SUBAGENT_FINISHED)

    # Pausing is not finishing, so the lane stays open until the run-end drain
    # closes it. No suspended outcome either: the run-level interrupt outcome is
    # opt-in and this stream did not ask for one, and a suspended lane only ever
    # travels with it.
    assert [(e.subagent_run_id, e.result) for e in finished] == [("run-scout", None)]  # type: ignore[attr-defined]
    assert _suspended_outcomes(finished) == [None]
    terminal_at = events.index(finished[0])
    assert [str(e.type) for i, e in enumerate(events) if _lane(e) == "run-scout" and i > terminal_at] == []
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_tool_is_attributed_to_the_member_that_owns_it(collect):
    events = await collect(_paused_member_chunks(), attributed())

    assert_stream_contains(events, EventType.TOOL_CALL_START, 2)
    assert_stream_contains(events, EventType.TOOL_CALL_ARGS, 2)
    assert _tool_call_lanes_in_order(events) == [("tc-leader-confirm", None), ("tc-member-confirm", "run-scout")]
    assert in_emitted_order(events, EventType.TOOL_CALL_ARGS, "tool_call_id", lambda e: json.loads(e.delta)) == [
        ("tc-leader-confirm", {"channel": "blog"}),
        ("tc-member-confirm", {"to": "ops"}),
    ]

    # The confirmation prompt the client must render arrives inside the lane, so
    # it precedes that member's terminal, and it opens a message of the member's
    # own rather than borrowing the leader's.
    lane_events = _lane_sequence(events, "run-scout")
    assert lane_events[-6:] == [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_END",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "SUBAGENT_FINISHED",
    ]

    # A tool call and the message carrying it name the same member. One message
    # cannot name two, so each lane's pending calls get a message of their own.
    parent_of = {e.tool_call_id: e.parent_message_id for e in _of_type(events, EventType.TOOL_CALL_START)}  # type: ignore[attr-defined]
    lane_of_message = _lane_of_message_id(events)
    assert lane_of_message[parent_of["tc-member-confirm"]] == "run-scout"
    assert lane_of_message[parent_of["tc-leader-confirm"]] is None
    assert parent_of["tc-member-confirm"] != parent_of["tc-leader-confirm"]


@pytest.mark.asyncio
@chunk_mappers
async def test_hidden_does_not_attribute_a_paused_member_tool(collect):
    events = await collect(_paused_member_chunks(), SUBAGENT_VISIBILITY_HIDDEN)

    assert _tool_call_lanes_in_order(events) == [("tc-leader-confirm", None), ("tc-member-confirm", None)]
    assert not [e for e in events if _lane(e) is not None]


def _grandchild_announced_first_chunks() -> List[Any]:
    """A grandchild whose first chunk precedes its parent sub-team's first chunk."""
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    member = _member_kwargs("scout", "run-scout", parent="run-inner")
    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        _agent_said("Scout first.", **member),
        _team_said("Inner second.", **inner),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


def _grandchild_under_an_announced_parent_chunks() -> List[Any]:
    """The same nesting, with the parent sub-team streaming before its member."""
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    member = _member_kwargs("scout", "run-scout", parent="run-inner")
    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        _team_said("Inner first.", **inner),
        _agent_said("Scout second.", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_grandchild_is_placed_under_a_parent_the_client_already_has(collect):
    """A parent link resolves against an announcement the client has already read."""
    events = await collect(_grandchild_under_an_announced_parent_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED, 2)
    assert [(e.subagent_run_id, e.parent_subagent_run_id) for e in _announcements(events)] == [  # type: ignore[attr-defined]
        ("run-inner", None),
        ("run-scout", "run-inner"),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_grandchild_whose_parent_is_not_announced_yet_names_no_parent(collect):
    """A forward reference is refused: no announcement names a lane the client lacks.

    A grandchild's first event can outrun its parent's. Naming the parent anyway
    hands the client a link it cannot resolve at the moment it reads it, which a
    client validating the protocol rejects outright, so the lane is announced
    with no parent and drawn directly under the run instead.
    """
    events = await collect(_grandchild_announced_first_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED, 2)
    assert [(e.subagent_run_id, e.parent_subagent_run_id) for e in _announcements(events)] == [  # type: ignore[attr-defined]
        ("run-scout", None),
        ("run-inner", None),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_parent_this_stream_never_announces_is_not_well_formed(collect):
    """A parent named but never announced is malformed, and the checker says so.

    Driven by deleting one lane from a stream the interface really produced,
    which is what a client would be left with if an announcement went missing:
    the surviving child still names a parent, and nothing on the wire says what
    that parent is.
    """
    events = await collect(_grandchild_under_an_announced_parent_chunks(), attributed())
    without_the_parent = [event for event in events if _lane(event) != "run-inner"]

    assert [e.subagent_run_id for e in _announcements(without_the_parent)] == ["run-scout"]  # type: ignore[attr-defined]
    violation = stream_invariant_violation(without_the_parent)
    assert violation is not None, "a parent no announcement names passed as a well-formed stream"
    assert "names parent run-inner" in violation, violation
    assert "never announces" in violation, violation


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_no_parent_is_reported_while_the_top_level_run_is_still_unknown(collect):
    member = _member_kwargs("scout", "run-scout", parent="run-inner")

    chunks = [
        # No chunk reporting no parent has arrived yet, so the top-level run id
        # is unknown and naming a parent would be a guess.
        _agent_said("Scout first.", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]

    events = await collect(chunks, attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    assert [(e.subagent_run_id, e.parent_subagent_run_id) for e in _announcements(events)] == [("run-scout", None)]  # type: ignore[attr-defined]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_resumed_runs_member_is_not_mistaken_for_a_grandchild(collect):
    """On resume the entity runs under the stored paused run's id, not the request's."""
    stored = _team_kwargs("research-team", "Research Team", "stored-paused-run")
    member = _member_kwargs("scout", "run-scout", parent="stored-paused-run")

    chunks = [
        TeamRunStartedEvent(**stored),
        _agent_said("Scout resumed.", **member),
        _team_said("Leader resumed.", **stored),
        TeamRunCompletedEvent(**stored),
    ]

    # The request's run id differs from the stored paused run's on purpose.
    events = await collect(chunks, attributed(), run_id="wire-run")

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    assert [(e.subagent_run_id, e.parent_subagent_run_id) for e in _announcements(events)] == [("run-scout", None)]  # type: ignore[attr-defined]
    assert _messages_in_order(events) == [("Scout", "Scout resumed."), (None, "Leader resumed.")]


def _grandchild_of_a_lane_announced_first_chunks() -> List[Any]:
    """A sub-team's chunk opens the stream, and a member of that sub-team follows it.

    No chunk reporting no parent has arrived, so the top-level run id is still
    unknown when both lanes are announced.
    """
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    member = _member_kwargs("scout", "run-scout", parent="run-inner")

    return [
        TeamRunStartedEvent(**inner),
        _agent_said("Scout first.", **member),
        _team_said("Inner second.", **inner),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_lane_announced_before_the_top_level_run_is_known_still_parents_its_own_children(collect):
    """An announced lane is one the top-level run cannot be confused with, known or not.

    Reporting no parent for a member of it would flatten a grandchild into a
    direct child of the top-level entity, which is a delegation tree the run
    never had.
    """
    events = await collect(_grandchild_of_a_lane_announced_first_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED, 2)
    assert [(e.subagent_run_id, e.parent_subagent_run_id) for e in _announcements(events)] == [  # type: ignore[attr-defined]
        ("run-inner", None),
        ("run-scout", "run-inner"),
    ]
    assert _messages_in_order(events) == [("Scout", "Scout first."), ("Inner Team", "Inner second.")]


def _leader_tool_open_when_a_member_starts_chunks(tool: ToolExecution) -> List[Any]:
    member = _member_kwargs("scout", "run-scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=tool),
        RunStartedEvent(**member),
        RunCompletedEvent(content="scout done", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_leader_tool_that_is_not_a_delegation_is_never_reported_as_one(collect):
    tool = ToolExecution(tool_call_id="tc-leader-search", tool_name="search_docs", tool_args={"query": "x"})

    events = await collect(_leader_tool_open_when_a_member_starts_chunks(tool), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    assert [
        (e.subagent_run_id, e.parent_tool_call_id, e.description, e.parent_message_id)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-scout", None, None, None)]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_non_mapping_tool_arguments_do_not_break_the_announce_path(collect):
    tool = ToolExecution(
        tool_call_id="tc-weird",
        tool_name="delegate_task_to_member",
        tool_args="not a mapping",  # type: ignore[arg-type]
    )

    events = await collect(_leader_tool_open_when_a_member_starts_chunks(tool), attributed())

    # Arguments that are not a mapping name no member, so the link is left out
    # rather than guessed, and the run finishes either way.
    assert [
        (e.subagent_run_id, e.parent_tool_call_id, e.description)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-scout", None, None)]
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)


def _two_open_delegations_chunks(member_id: str, member_run: str) -> List[Any]:
    """Two delegation calls open at once, then one member's first event arrives."""

    def delegation(tool_call_id: str, target: str) -> ToolExecution:
        return _delegation(tool_call_id, target, f"work for {target}")

    member = _member_kwargs(member_id, member_run)

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=delegation("tc-alpha", "alpha")),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=delegation("tc-beta", "beta")),
        RunStartedEvent(**member),
        RunCompletedEvent(content=f"{member_id} done", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_the_delegation_that_names_the_member_wins_when_several_are_open(collect):
    events = await collect(_two_open_delegations_chunks("beta", "run-beta"), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    assert [
        (e.subagent_run_id, e.parent_tool_call_id, e.description)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-beta", "tc-beta", "work for beta")]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_the_delegation_link_is_omitted_rather_than_guessed_when_no_open_call_names_the_member(collect):
    events = await collect(_two_open_delegations_chunks("gamma", "run-gamma"), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    # Two candidates, neither naming this member: the link is left out, not
    # picked at random, and the description that would come with it goes too.
    assert [
        (e.subagent_run_id, e.parent_tool_call_id, e.description, e.parent_message_id)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-gamma", None, None, None)]


def _member_tool_changes_state_chunks(session_state: Dict[str, Any], member: Dict[str, Any]) -> List[Any]:
    """A member runs two tools, each writing the team's shared session state.

    The writes are side effects driven by iteration: the mapper snapshots the
    state when the stream opens, so a write that happened while the chunk list
    was being built would produce no delta at all. Two writes rather than one,
    because one delta is the same whether or not the mapper banked the state it
    just reported: only the second says the baseline moved with it.
    """
    approve = ToolExecution(tool_call_id="tc-member-approve", tool_name="approve", tool_args={}, result="ok")
    notify = ToolExecution(tool_call_id="tc-member-notify", tool_name="notify", tool_args={}, result="sent")
    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        ToolCallStartedEvent(tool=approve, **member),
        SideEffect(lambda: session_state.__setitem__("approved", True)),
        ToolCallCompletedEvent(tool=approve, **member),
        ToolCallStartedEvent(tool=notify, **member),
        SideEffect(lambda: session_state.__setitem__("notified", True)),
        ToolCallCompletedEvent(tool=notify, **member),
        RunCompletedEvent(content="scout done", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


# The two deltas that fixture produces, in order. The second is what shows the
# mapper reports a change against the state it last sent rather than against the
# state the stream opened on, which would repeat the first change inside it.
_STATE_DELTAS_IN_ORDER = [
    ([{"op": "replace", "path": "/approved", "value": True}],),
    ([{"op": "add", "path": "/notified", "value": True}],),
]


@pytest.mark.asyncio
@chunk_mappers
async def test_hidden_still_delivers_a_state_change_a_member_tool_made(collect):
    session_state: Dict[str, Any] = {"approved": False}
    member = _member_kwargs("scout", "run-scout")

    events = await collect(
        _member_tool_changes_state_chunks(session_state, member),
        SUBAGENT_VISIBILITY_HIDDEN,
        run_state=session_state,
    )

    assert_stream_contains(events, EventType.STATE_DELTA, 2)
    assert in_emitted_order(events, EventType.STATE_DELTA, "delta") == _STATE_DELTAS_IN_ORDER
    # The member's own tool call is withheld: this fixture holds no delegation
    # call of the leader's, so nothing at all here is attributed or attributable.
    assert not [e for e in events if "TOOL_CALL" in str(e.type)]
    assert not [e for e in events if _lane(e) is not None]
    assert not _messages_in_order(events)


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_state_events_are_never_attributed_to_the_member_that_changed_them(collect):
    session_state: Dict[str, Any] = {"approved": False}
    member = _member_kwargs("scout", "run-scout")

    events = await collect(
        _member_tool_changes_state_chunks(session_state, member),
        attributed(),
        run_state=session_state,
    )

    assert_stream_contains(events, EventType.STATE_DELTA, 2)
    assert_stream_contains(events, EventType.STATE_SNAPSHOT)
    # The changes were made inside a member lane, yet the state events carry no
    # member: a team's session state is one shared document.
    state_events = [e for e in events if str(e.type).removeprefix("EventType.").startswith("STATE_")]
    assert [(str(e.type).removeprefix("EventType."), _lane(e)) for e in state_events] == [
        ("STATE_DELTA", None),
        ("STATE_DELTA", None),
        ("STATE_SNAPSHOT", None),
    ]
    assert in_emitted_order(events, EventType.STATE_DELTA, "delta") == _STATE_DELTAS_IN_ORDER


def _member_result_chunks(content: Any) -> List[Any]:
    """One member whose run reports ``content`` as its result."""
    member = _member_kwargs("scout", "run-scout")
    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        RunCompletedEvent(content=content, **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@pytest.mark.parametrize(
    # Built per case rather than at collection time, so the two mappers cannot
    # hand each other a result one of them has already been through.
    "content_factory,expected",
    [
        (lambda: {"headline": "found it", "sources": 3}, {"headline": "found it", "sources": 3}),
        (lambda: ["a", "b"], ["a", "b"]),
    ],
    ids=["mapping", "sequence"],
)
@chunk_mappers
async def test_a_non_text_member_result_is_serialized_rather_than_dropped(collect, content_factory, expected):
    events = await collect(_member_result_chunks(content_factory()), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_FINISHED)
    finished = _of_type(events, EventType.SUBAGENT_FINISHED)
    assert [e.subagent_run_id for e in finished] == ["run-scout"]  # type: ignore[attr-defined]
    assert json.loads(finished[0].result) == expected  # type: ignore[attr-defined]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_structured_member_result_is_serialized_rather_than_dropped(collect):
    class Brief(BaseModel):
        headline: str
        sources: int

    events = await collect(_member_result_chunks(Brief(headline="found it", sources=3)), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_FINISHED)
    finished = _of_type(events, EventType.SUBAGENT_FINISHED)
    assert json.loads(finished[0].result) == {"headline": "found it", "sources": 3}  # type: ignore[attr-defined]


# --- Optional dependency diagnostics ----------------------------------------


def _probe(script: str) -> str:
    """Run a snippet in a fresh interpreter that can see this checkout."""
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(path for path in sys.path if path)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_the_handlers_module_names_the_missing_optional_dependency():
    output = _probe(
        "import sys\n"
        "sys.modules['ag_ui'] = None\n"
        "sys.modules['ag_ui.core'] = None\n"
        "try:\n"
        "    import agno.os.interfaces.agui.handlers\n"
        "except ImportError as error:\n"
        "    print(error)\n"
    )
    assert "ag-ui-protocol" in output


def test_missing_subagent_lineage_events_are_reported_at_debug_level():
    output = _probe(
        "import logging, sys\n"
        "import agno.utils.log as agno_log\n"
        "probe = logging.getLogger('probe')\n"
        "probe.setLevel(logging.DEBUG)\n"
        "handler = logging.StreamHandler(sys.stdout)\n"
        # The level is written into the line, so the level itself is read back
        # below rather than only the text, which any log helper would produce.
        "handler.setFormatter(logging.Formatter('%(levelname)s %(message)s'))\n"
        "probe.addHandler(handler)\n"
        "agno_log.logger = probe\n"
        "agno_log.debug_on = True\n"
        "agno_log.debug_level = 1\n"
        "import ag_ui.core as core\n"
        "for name in ('SubagentStartedEvent', 'SubagentFinishedEvent', 'SubagentErrorEvent'):\n"
        # Conditional, because the install this probe describes is exactly the
        # one where these are already absent.
        "    if hasattr(core, name):\n"
        "        delattr(core, name)\n"
        "import agno.os.interfaces.agui.handlers as probed\n"
        "print('AVAILABLE', probed.SUBAGENT_EVENTS_AVAILABLE)\n"
    )
    assert "AVAILABLE False" in output
    reported = [line for line in output.splitlines() if "ag-ui-protocol" in line]
    assert reported, f"the missing lineage events were reported nowhere: {output}"
    assert all(line.startswith("DEBUG ") for line in reported), reported


# --- Which tool call is the delegation --------------------------------------


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_leader_tool_that_merely_takes_a_task_is_not_read_as_the_delegation(collect):
    """Agno's own ``update_user_memory`` takes a ``task``, and is not a delegation."""
    tool = ToolExecution(
        tool_call_id="tc-memory",
        tool_name="update_user_memory",
        tool_args={"task": "the user likes brevity"},
    )

    events = await collect(_leader_tool_open_when_a_member_starts_chunks(tool), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    assert [
        (e.subagent_run_id, e.parent_tool_call_id, e.description, e.parent_message_id)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-scout", None, None, None)]


@needs_lineage_events
@pytest.mark.asyncio
@pytest.mark.parametrize(
    # The two tasks-mode delegation tools differ in what they name: one takes
    # the member it hands the task to, the other takes only task ids, so only
    # the first can be shown to have spawned this member.
    "tool_name,tool_args,links",
    [
        ("execute_task", {"task_id": "t-1", "member_id": "scout"}, True),
        ("execute_tasks_parallel", {"task_ids": ["t-1"]}, False),
    ],
    ids=["execute_task", "execute_tasks_parallel"],
)
@chunk_mappers
async def test_a_tasks_mode_delegation_links_the_member_it_names(collect, tool_name, tool_args, links):
    tool = ToolExecution(tool_call_id="tc-task", tool_name=tool_name, tool_args=tool_args)

    events = await collect(_leader_tool_open_when_a_member_starts_chunks(tool), attributed())
    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    parent_of_tool_call = {
        e.tool_call_id: e.parent_message_id  # type: ignore[attr-defined]
        for e in _of_type(events, EventType.TOOL_CALL_START)
    }

    # A tasks-mode delegation carries no task text, so a link it does report
    # comes without a description rather than with an invented one. The parent
    # message it names has to be one this stream really opened: read back as
    # None on both sides, that field compares nothing.
    parent_message = parent_of_tool_call["tc-task"]
    if links:
        assert parent_message in _lane_of_message_id(events), parent_message
    expected = ("tc-task", None, parent_message) if links else (None, None, None)
    assert [
        (e.subagent_run_id, e.parent_tool_call_id, e.description, e.parent_message_id)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-scout", *expected)]


def test_an_open_tool_call_is_recorded_under_its_tool_name():
    """The name is a required part of the record, so a reader cannot fall back to argument shape."""
    delegating = StreamState(subagent_visibility=attributed())
    delegating.record_open_tool_call("tc-1", "delegate_task_to_member", {"member_id": "scout", "task": "go"}, "m-1")
    assert delegating.find_delegation_call(ROOT_LANE, "scout") == "tc-1"
    assert delegating.delegation_task(ROOT_LANE, "tc-1") == "go"

    # The unrelated call names a member, so the lookup is asked for that member
    # rather than for nothing: given a falsy member id it answers None without
    # ever reading the record, which is true of any tool at all.
    unrelated = StreamState(subagent_visibility=attributed())
    unrelated.record_open_tool_call("tc-2", "update_user_memory", {"member_id": "scout", "task": "remember"}, "m-1")
    assert unrelated.find_delegation_call(ROOT_LANE, "scout") is None
    assert unrelated.delegation_task(ROOT_LANE, "tc-2") is None


def _delegation_args(member: str) -> Dict[str, Any]:
    return {"member_id": member, "task": f"{member}, do the leader's task"}


def _state_with_a_delegation_in_every_kind_of_lane() -> StreamState:
    """A state where the root lane and two member lanes each hold a delegation to ``scout``.

    Three lanes, so a lookup that reaches past the lane it was asked about lands
    on somebody else's call rather than on nothing.
    """
    state = StreamState(subagent_visibility=attributed())
    state.resolve_lane(TOP_LEVEL_RUN, None)
    state.record_open_tool_call("tc-root", "delegate_task_to_member", _delegation_args("scout"), "m-root")

    for run_id, tool_call_id in (("run-open", "tc-open"), ("run-closed", "tc-closed")):
        state.open_subagent(run_id, name=run_id, parent_lane=ROOT_LANE)
        state.current_lane = run_id
        state.record_open_tool_call(tool_call_id, "delegate_task_to_member", _delegation_args("scout"), f"m-{run_id}")
    state.close_subagent("run-closed")
    state.current_lane = ROOT_LANE
    return state


# "No lane can be named" is spelled with a marker of its own rather than with
# None, which is what the root lane is spelled with: written as None the two
# expectations would be one, and a case expecting no lane would pass on an
# answer of the root lane's own delegation call.
_UNNAMEABLE = "<no lane can be named>"

# The parent kinds this module drives, one per state a named run can be in as
# far as the lane table is concerned, and the lane each resolves to. Written out
# rather than derived from anything, so it is what is covered rather than a
# proof that nothing else exists: the property below is stated over all of them
# so that a new reason a lane cannot be named inherits the check, but a kind
# nobody adds here still goes undriven.
_PARENTS_A_CHUNK_CAN_NAME: Dict[str, Tuple[Optional[str], Optional[str]]] = {
    "no parent at all": (None, ROOT_LANE),
    "the top-level run": (TOP_LEVEL_RUN, ROOT_LANE),
    "an announced lane still open": ("run-open", "run-open"),
    "an announced lane already terminated": ("run-closed", _UNNAMEABLE),
    "a lane this stream has never announced": ("run-unheard-of", _UNNAMEABLE),
}


@needs_lineage_events
@pytest.mark.parametrize("parent", sorted(_PARENTS_A_CHUNK_CAN_NAME), ids=sorted(_PARENTS_A_CHUNK_CAN_NAME))
def test_a_delegation_link_is_only_ever_read_from_the_parents_own_lane(parent):
    """Whatever lane comes back, the call beside it belongs to that lane and to that parent.

    Stated over each of the parent kinds above rather than over the one that was
    reported, and as a property rather than as an expected pair, so a new reason
    a lane cannot be named inherits the check instead of needing a case of its
    own. What it forbids is the reach: answering with the top-level
    entity's own open call for a parent that is not the top-level entity, which
    hands a grandchild the leader's call, the leader's parent message and the
    leader's task text as its own description.
    """
    parent_run_id, resolves_to = _PARENTS_A_CHUNK_CAN_NAME[parent]
    state = _state_with_a_delegation_in_every_kind_of_lane()

    lane, delegation_call_id = state.delegating_lane_for(parent_run_id, "scout")

    if resolves_to == _UNNAMEABLE:
        assert (lane, delegation_call_id) == (None, None)
        assert state.delegation_task(lane, delegation_call_id) is None
        assert state.delegation_parent_message_id(lane, delegation_call_id) is None
        return
    assert lane == resolves_to
    assert delegation_call_id in (state.open_tool_calls.get(lane) or {}), (
        f"the call reported for {parent} belongs to some other lane"
    )


def _grandchild_whose_parent_was_never_announced_chunks() -> List[Any]:
    """A member appears under an inner team's run that this stream never saw start.

    The leader's own delegation names the same member id, which is what makes
    the reach visible: reaching past for it hands this member the leader's call.
    """
    delegation = _delegation("tc-delegate-scout", **_delegation_args("scout"))
    grandchild = _member_kwargs("scout", "run-grandchild", parent="run-inner-team")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(tool=delegation, **_TOP_LEVEL),
        _agent_said("Reporting in.", **grandchild),
        RunCompletedEvent(content="done", **grandchild),
        _team_said("Final synthesis.", **_TOP_LEVEL),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_member_under_an_unannounced_parent_carries_no_part_of_the_leaders_delegation(collect):
    """No parent means no parent call, no parent message and no description either.

    All three are read off the delegating lane's own open calls, so a lane that
    cannot be named leaves the announcement with none of them. Asserted on the
    payload, because the reported symptom was an announcement reporting no
    parent lane while carrying the leader's call id, the leader's parent message
    and the leader's task text.
    """
    events = await collect(_grandchild_whose_parent_was_never_announced_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    assert [
        (
            e.subagent_run_id,  # type: ignore[attr-defined]
            e.parent_subagent_run_id,  # type: ignore[attr-defined]
            e.parent_tool_call_id,  # type: ignore[attr-defined]
            e.parent_message_id,  # type: ignore[attr-defined]
            e.description,  # type: ignore[attr-defined]
        )
        for e in _announcements(events)
    ] == [("run-grandchild", None, None, None, None)]
    # The leader's own delegation call is still on the wire as the leader's.
    assert _tool_call_lanes_in_order(events) == [("tc-delegate-scout", None)]


# --- Paused members ---------------------------------------------------------


def _paused_on_two_members_chunks() -> List[Any]:
    """One pause waiting on a pending call from each of two different members."""

    def requirement(member: str, run: str, tool_call_id: str, tool_name: str) -> RunRequirement:
        return _requirement(
            ToolExecution(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_args={"for": member},
                requires_confirmation=True,
            ),
            member,
            run,
            member.capitalize(),
        )

    def delegation(member: str) -> ToolExecution:
        return _delegation(f"tc-delegate-{member}", member, f"{member} it")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(tool=delegation("scout"), **_TOP_LEVEL),
        TeamToolCallStartedEvent(tool=delegation("writer"), **_TOP_LEVEL),
        TeamRunPausedEvent(
            tools=[],
            requirements=[
                requirement("scout", "run-scout", "tc-scout-confirm", "send_email"),
                requirement("writer", "run-writer", "tc-writer-confirm", "publish"),
            ],
            **_TOP_LEVEL,
        ),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_pause_waiting_on_two_members_gives_each_a_message_of_its_own(collect):
    """One message cannot name two members, so the prompt is split per member.

    A tool call belongs to the message that carries it, so the two have to agree
    about whose call it is. With pending calls from two members under one
    message they cannot, whichever member that message were stamped with.
    """
    events = await collect(_paused_on_two_members_chunks(), attributed())

    assert_stream_contains(events, EventType.TEXT_MESSAGE_START, 2)
    assert _tool_call_lanes_in_order(events) == [
        ("tc-delegate-scout", None),
        ("tc-delegate-writer", None),
        ("tc-scout-confirm", "run-scout"),
        ("tc-writer-confirm", "run-writer"),
    ]

    lane_of_message = _lane_of_message_id(events)
    assert [
        (e.tool_call_id, _lane(e), lane_of_message[e.parent_message_id])  # type: ignore[attr-defined]
        for e in _of_type(events, EventType.TOOL_CALL_START)
        if _lane(e) is not None
    ] == [
        ("tc-scout-confirm", "run-scout", "run-scout"),
        ("tc-writer-confirm", "run-writer", "run-writer"),
    ]


# The events that open or close a message or a tool call. One of these landing
# inside somebody else's open span is a nesting a validating client rejects.
#
# Nothing else is read. RAW and CUSTOM are opaque passthroughs the source stream
# interleaves wherever it likes, and a delegation stays open for as long as the
# member it spawned is producing them. A member's announcement belongs inside
# that delegation too: the call it names in ``parentToolCallId`` is exactly the
# one still open around it.
_SPAN_LIFECYCLE_EVENTS = frozenset({"TEXT_MESSAGE_START", "TEXT_MESSAGE_END", "TOOL_CALL_START", "TOOL_CALL_END"})


def _spans_a_prompt_opens_inside(events: List[BaseEvent]) -> List[Tuple[str, str]]:
    """(what was emitted, what it landed inside) for every span event nested in another."""
    nested: List[Tuple[str, str]] = []
    open_messages: Set[str] = set()
    open_tool_calls: Set[str] = set()
    for event in events:
        kind = str(event.type).removeprefix("EventType.")
        own_message = getattr(event, "message_id", None)
        own_call = getattr(event, "tool_call_id", None)
        if kind in _SPAN_LIFECYCLE_EVENTS:
            nested.extend(
                (kind, f"TOOL_CALL {tool_call_id}") for tool_call_id in open_tool_calls if tool_call_id != own_call
            )
            nested.extend(
                (kind, f"TEXT_MESSAGE {message_id}") for message_id in open_messages if message_id != own_message
            )
        if kind == "TEXT_MESSAGE_START":
            open_messages.add(event.message_id)  # type: ignore[attr-defined]
        elif kind == "TEXT_MESSAGE_END":
            open_messages.discard(event.message_id)  # type: ignore[attr-defined]
        elif kind == "TOOL_CALL_START":
            open_tool_calls.add(event.tool_call_id)  # type: ignore[attr-defined]
        elif kind == "TOOL_CALL_END":
            open_tool_calls.discard(event.tool_call_id)  # type: ignore[attr-defined]
    return nested


def _paused_inside_one_open_delegation_chunks() -> List[Any]:
    """The run pauses on a member's call with the delegation that spawned it still open."""
    delegation = _delegation("tc-delegate-scout", "scout", "scout it")
    requirement = _requirement(
        ToolExecution(
            tool_call_id="tc-scout-confirm",
            tool_name="send_email",
            tool_args={"to": "ops"},
            requires_confirmation=True,
        ),
        "scout",
        "run-scout",
        "Scout",
    )

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(tool=delegation, **_TOP_LEVEL),
        RunStartedEvent(**_member_kwargs("scout", "run-scout")),
        TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL),
    ]


@pytest.mark.asyncio
@chunk_mappers
@pytest.mark.parametrize(
    "setting",
    [lambda: SUBAGENT_VISIBILITY_INLINE, attributed, lambda: SUBAGENT_VISIBILITY_HIDDEN],
    ids=["inline", "attributed", "hidden"],
)
async def test_a_pause_prompt_never_lands_inside_a_span_whichever_setting_is_set(collect, setting):
    """The three settings agree about nesting: the prompt goes out with nothing open.

    The leader's delegation call is open when the run pauses, and the prompt
    opens a message and a tool call of its own. A tool call carries only its own
    arguments and its end between start and end, so those have to follow the
    delegation's close, and they have to follow it under every setting: a client
    reading one stream correctly and another not is the same defect twice.
    """
    events = await collect(_paused_inside_one_open_delegation_chunks(), setting())

    assert_stream_contains(events, EventType.TOOL_CALL_START, 2)
    assert _spans_a_prompt_opens_inside(events) == []


def _paused_member_that_never_streamed_chunks() -> List[Any]:
    """A member pauses without ever having emitted an event of its own."""
    member_tool = ToolExecution(
        tool_call_id="tc-ghost-confirm",
        tool_name="send_email",
        tool_args={"to": "ops"},
        requires_confirmation=True,
    )
    requirement = _requirement(member_tool, "ghost", "run-ghost", "Ghost")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_members_lane_is_announced_before_anything_carries_it(collect):
    events = await collect(_paused_member_that_never_streamed_chunks(), attributed())

    assert_stream_contains(events, EventType.TOOL_CALL_START)
    assert _tool_call_lanes_in_order(events) == [("tc-ghost-confirm", "run-ghost")]
    assert [(e.subagent_run_id, e.name) for e in _announcements(events)] == [("run-ghost", "Ghost")]  # type: ignore[attr-defined]
    # A start and a terminal around the message and the tool call the client has
    # to render, both on the member's own lane so the two agree about whose call
    # it is.
    assert _lane_sequence(events, "run-ghost") == [
        "SUBAGENT_STARTED",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_END",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "SUBAGENT_FINISHED",
    ]
    carrying = [e.parent_message_id for e in _of_type(events, EventType.TOOL_CALL_START)]  # type: ignore[attr-defined]
    assert [_lane_of_message_id(events)[message_id] for message_id in carrying] == ["run-ghost"]


def _paused_tool_listed_in_both_places_chunks() -> List[Any]:
    """One paused tool call reported both on the terminal event and in a member's requirement."""
    shared = ToolExecution(
        tool_call_id="tc-shared-confirm",
        tool_name="send_email",
        tool_args={"to": "ops"},
        requires_confirmation=True,
    )
    requirement = _requirement(shared, "scout", "run-scout", "Scout")
    member = _member_kwargs("scout", "run-scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        TeamRunPausedEvent(tools=[shared], requirements=[requirement], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_tool_listed_twice_is_prompted_once_on_its_members_lane(collect):
    events = await collect(_paused_tool_listed_in_both_places_chunks(), attributed())

    assert_stream_contains(events, EventType.TOOL_CALL_START)
    assert _tool_call_lanes_in_order(events) == [("tc-shared-confirm", "run-scout")]
    assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id", _lane) == [
        ("tc-shared-confirm", "run-scout")
    ]


@pytest.mark.asyncio
@chunk_mappers
async def test_hidden_prompts_a_paused_tool_listed_twice_once_and_names_no_member(collect):
    """Hidden de-duplicates the prompt as attributed does, without attributing it.

    Only the default keeps the duplicate, because only the default's stream has
    to be what it was before member attribution existed.
    """
    events = await collect(_paused_tool_listed_in_both_places_chunks(), SUBAGENT_VISIBILITY_HIDDEN)

    assert_stream_contains(events, EventType.TOOL_CALL_START)
    assert _tool_call_lanes_in_order(events) == [("tc-shared-confirm", None)]
    assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id", _lane) == [("tc-shared-confirm", None)]
    assert not [e for e in events if "SUBAGENT" in str(e.type)]
    assert not [e for e in events if _lane(e) is not None]


# --- The terminal's interrupts against the calls the prompt showed ----------

# The interrupt-aware lifecycle arrived after the lineage events, so an install
# that serves member attribution can still have no terminal to advertise an
# interrupt on.
needs_interrupt_outcome = pytest.mark.skipif(
    not interrupts.INTERRUPT_OUTCOME_AVAILABLE,
    reason="the installed ag_ui.core has no interrupt-aware run lifecycle",
)


def _encoded(event: BaseEvent) -> Dict[str, Any]:
    """One event as the bytes a client receives, through the protocol's own encoder.

    A field the installed models do not declare still sets an attribute, so
    reading the object says nothing about what reached the client.
    """
    return json.loads(EventEncoder().encode(event)[len("data: ") :])


def _prompted_call_ids(events: List[BaseEvent]) -> List[str]:
    """Every pending call the prompt sent, in the order a client reads them."""
    return [_encoded(event)["toolCallId"] for event in _of_type(events, EventType.TOOL_CALL_START)]


def _advertised_interrupts(events: List[BaseEvent]) -> List[Dict[str, Any]]:
    """The interrupts the run terminal carried, in the order it advertised them."""
    finished = _of_type(events, EventType.RUN_FINISHED)
    assert len(finished) == 1, f"expected one run terminal, got {[str(event.type) for event in events]}"
    outcome = _encoded(finished[0]).get("outcome")
    assert outcome is not None, "the run terminal carried no interrupt outcome"
    return list(outcome["interrupts"])


def _confirmable(tool_call_id: str, tool_name: str) -> ToolExecution:
    """A pending call waiting on a confirmation a client can answer."""
    return ToolExecution(
        tool_call_id=tool_call_id, tool_name=tool_name, tool_args={"to": "ops"}, requires_confirmation=True
    )


def _two_requirements_on_one_call_chunks() -> Tuple[List[Any], List[str]]:
    """A pause whose requirements wait on one call, with the ids it needs answered.

    The ids come back alongside because they are minted per requirement: they
    are what tells the two apart once they are on the wire, the call they share
    cannot.
    """
    shared = _confirmable("tc-shared", "send_email")
    other = _confirmable("tc-other", "publish")
    reported = [RunRequirement(shared), RunRequirement(shared), RunRequirement(other)]
    solo = {"agent_id": "solo", "agent_name": "Solo", "run_id": TOP_LEVEL_RUN}

    return (
        [RunStartedEvent(**solo), AgentRunPausedEvent(tools=[shared, other], requirements=reported, **solo)],
        [requirement.id for requirement in reported],
    )


@needs_interrupt_outcome
@pytest.mark.asyncio
@chunk_mappers
async def test_two_requirements_waiting_on_one_call_are_both_advertised(collect):
    """Neither answer the run needs is displaced by the other naming the same call.

    The terminal advertises what the run cannot continue without, and both of
    these are that, so a client told about one of them answers what it was told
    and the resume refuses it over the requirement nobody named. They go out in
    the order the pause reported them, at the place the prompt showed the call
    they share.

    Driven on the default visibility: no member is involved, so this is a run
    any supported protocol release serves.
    """
    chunks, needed = _two_requirements_on_one_call_chunks()

    events = await collect(chunks, emit_interrupt_outcome=True)

    advertised = _advertised_interrupts(events)
    assert _prompted_call_ids(events) == ["tc-shared", "tc-other"]
    assert [interrupt["id"] for interrupt in advertised] == needed
    assert [interrupt["toolCallId"] for interrupt in advertised] == ["tc-shared", "tc-shared", "tc-other"]


def _pause_interleaving_two_members_chunks() -> Tuple[List[Any], List[str]]:
    """Two members' pending calls, reported in an order that returns to the first."""
    reported = [
        _requirement(_confirmable("tc-1", "send_email"), "scout", "run-scout", "Scout"),
        _requirement(_confirmable("tc-2", "publish"), "writer", "run-writer", "Writer"),
        _requirement(_confirmable("tc-3", "archive"), "scout", "run-scout", "Scout"),
    ]

    return (
        [TeamRunStartedEvent(**_TOP_LEVEL), TeamRunPausedEvent(tools=[], requirements=reported, **_TOP_LEVEL)],
        [requirement.id for requirement in reported],
    )


@needs_lineage_events
@needs_interrupt_outcome
@pytest.mark.asyncio
@chunk_mappers
async def test_the_terminal_advertises_in_the_order_the_prompt_sent_the_calls(collect):
    """The prompt sends one message per member, so a member's calls arrive together.

    A client renders the pending calls in the order they arrived and reads the
    terminal's interrupts beside them, so the terminal follows what the wire
    showed rather than the order the pause happened to list its requirements in.
    """
    chunks, reported = _pause_interleaving_two_members_chunks()

    events = await collect(chunks, attributed(), emit_interrupt_outcome=True)

    advertised = _advertised_interrupts(events)
    assert _prompted_call_ids(events) == ["tc-1", "tc-3", "tc-2"]
    assert [interrupt["toolCallId"] for interrupt in advertised] == ["tc-1", "tc-3", "tc-2"]
    # Named by id too, which is what a client answers under, and in an order the
    # pause did not report: the middle requirement is advertised last.
    assert [interrupt["id"] for interrupt in advertised] == [reported[0], reported[2], reported[1]]


def _pause_while_a_member_tool_is_still_running_chunks() -> List[Any]:
    """A member's own tool call is open, and the run pauses on the leader's instead."""
    member = _member_kwargs("scout", "run-scout")
    working = ToolExecution(tool_call_id="tc-scout-work", tool_name="search_docs", tool_args={"query": "agno"})
    leader_tool = ToolExecution(
        tool_call_id="tc-leader-confirm", tool_name="publish", tool_args={"channel": "blog"}, requires_confirmation=True
    )

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        ToolCallStartedEvent(tool=working, **member),
        TeamRunPausedEvent(tools=[leader_tool], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_pause_still_closes_a_member_tool_call_left_running(collect):
    """A pause ends the run's stream, so a member call nobody is waiting on still needs an end.

    A member's terminal ends no tool call, so the end is written by the run's
    final sweep. The sweep runs before that member's terminal, so the call is
    put away while its lane is still open, and it is still the member's call,
    which is what the client needs to put it away.
    """
    events = await collect(_pause_while_a_member_tool_is_still_running_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_FINISHED)
    assert _tool_call_lanes_in_order(events) == [("tc-scout-work", "run-scout"), ("tc-leader-confirm", None)]
    assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id", _lane) == [
        ("tc-scout-work", "run-scout"),
        ("tc-leader-confirm", None),
    ]
    # The member's own call carries no result: it never reported one.
    assert not _of_type(events, EventType.TOOL_CALL_RESULT)
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)


def _pause_naming_a_member_that_already_terminated_chunks() -> List[Any]:
    """The paused requirement names a member whose own terminal has already gone out."""
    member = _member_kwargs("scout", "run-scout")
    late = ToolExecution(
        tool_call_id="tc-late-confirm", tool_name="send_email", tool_args={"to": "ops"}, requires_confirmation=True
    )
    requirement = _requirement(late, "scout", "run-scout", "Scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        RunCompletedEvent(content="scout done", **member),
        TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_pause_naming_a_closed_member_prompts_on_the_root_lane(collect):
    """A terminal is final for the id it names, so the prompt cannot be put in that lane.

    Stamping it there would hand the client a tool call inside a member it has
    already closed, and announcing the lane again would give one invocation two
    lifecycles. The prompt goes out unattributed instead, which is a call the
    client can still render and answer.
    """
    events = await collect(_pause_naming_a_member_that_already_terminated_chunks(), attributed())

    assert_stream_contains(events, EventType.TOOL_CALL_START)
    assert _tool_call_lanes_in_order(events) == [("tc-late-confirm", None)]
    assert [e.subagent_run_id for e in _announcements(events)] == ["run-scout"]  # type: ignore[attr-defined]
    assert in_emitted_order(events, EventType.SUBAGENT_FINISHED, "subagent_run_id") == [("run-scout",)]
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)


def _paused_member_with_nothing_to_show_chunks() -> List[Any]:
    """A member pauses on a tool the client cannot be shown: it carries no name.

    The pause carries the run's own words, as a real one does, so what the client
    is left with when the call is dropped is a message that says why the run
    stopped rather than an empty bubble.
    """
    nameless = _nameless_tool()
    requirement = _requirement(nameless, "ghost", "run-ghost", "Ghost")
    paused = TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL)
    paused.content = "Waiting on an approval."

    return [TeamRunStartedEvent(**_TOP_LEVEL), paused]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_lane_is_not_announced_when_the_prompt_it_was_for_is_dropped(collect):
    """A dropped prompt must not leave the client a terminal for a member it never saw start."""
    events = await collect(_paused_member_with_nothing_to_show_chunks(), attributed())

    assert not [e for e in events if "SUBAGENT" in str(e.type)]
    assert not [e for e in events if _lane(e) is not None]
    assert not _of_type(events, EventType.TOOL_CALL_START)
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_pause_the_client_cannot_act_on_is_recorded(collect, caplog):
    """A pause prompting nothing has to be logged, and as the kind of pause it is.

    Here the terminal listed a pending call and the client cannot be shown it,
    so the client is told the run is waiting and given nothing to answer with.
    That is not the same as a terminal that listed nothing, which is the case
    below, so the two do not share a line.
    """
    with captured_agno_logs(caplog, "WARNING"):
        events = await collect(_paused_member_with_nothing_to_show_chunks(), attributed())

    assert not _of_type(events, EventType.TOOL_CALL_START)
    assert_stream_contains(events, EventType.TEXT_MESSAGE_CONTENT)
    # The joined text, not merely that a message opened: an empty bubble tells
    # the client nothing about why the run stopped. Unattributed, because the
    # lane the prompt was for is not announced when its call is dropped.
    assert joined_text_in_emitted_order(events) == [(None, "Waiting on an approval.")]
    # Matched on a phrase the line about the dropped call itself does not carry,
    # so this cannot pass on that one instead.
    assert [r.message for r in caplog.records if "the run is waiting" in r.message], (
        "a pause the client was told about but cannot answer left no trace at all"
    )


def _paused_listing_no_pending_call_chunks() -> List[Any]:
    """A run pauses without listing a pending tool call at all."""
    paused = AgentRunPausedEvent(agent_id="solo", agent_name="Solo", run_id=TOP_LEVEL_RUN, tools=[])
    paused.content = "Confirm before I send this."

    return [RunStartedEvent(agent_id="solo", agent_name="Solo", run_id=TOP_LEVEL_RUN), paused]


@pytest.mark.asyncio
@chunk_mappers
async def test_a_pause_that_lists_nothing_reaches_the_client_as_a_finished_run_and_says_so(collect, caplog):
    """Nothing announces this pause, so the log is the only place it exists.

    The prompt turns on the terminal having listed a pending call at all, which
    this one did not, so the pause's own content goes out nowhere either. A
    terminal that listed a call the client cannot be shown still carries the
    content, which is the pre-change stream and is pinned separately.

    Driven on the default visibility: no member is involved, so this is a run
    any supported protocol release serves.
    """
    chunks = _paused_listing_no_pending_call_chunks()
    # The pause does carry content, so the silence below is that content being
    # dropped rather than a fixture with nothing to say.
    assert any(getattr(chunk, "content", None) for chunk in chunks)
    with captured_agno_logs(caplog, "WARNING"):
        events = await collect(chunks)

    assert_stream_carries_exactly(events, EventType.TEXT_MESSAGE_START, 0)
    assert not _of_type(events, EventType.TOOL_CALL_START)
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)
    assert [r.message for r in caplog.records if "plain finished run" in r.message], (
        "a pause the client cannot tell from a completion left no trace at all"
    )


def _paused_member_carrying_one_unusable_tool_chunks(unusable: ToolExecution) -> List[Any]:
    """Two members pause, and one of them waits on a tool the client cannot be shown."""
    ghost = _requirement(unusable, "ghost", "run-ghost", "Ghost")

    usable = ToolExecution(
        tool_call_id="tc-scout-confirm", tool_name="send_email", tool_args={"to": "ops"}, requires_confirmation=True
    )
    scout = _requirement(usable, "scout", "run-scout", "Scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamRunPausedEvent(tools=[], requirements=[ghost, scout], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_only_the_members_the_prompt_names_are_announced(collect):
    """A lane the prompt carries nothing for tells the client about a member it never hears from."""
    events = await collect(_paused_member_carrying_one_unusable_tool_chunks(_nameless_tool()), attributed())

    assert_stream_contains(events, EventType.TOOL_CALL_START)
    assert [(e.subagent_run_id, e.name) for e in _announcements(events)] == [("run-scout", "Scout")]  # type: ignore[attr-defined]
    assert _tool_call_lanes_in_order(events) == [("tc-scout-confirm", "run-scout")]


def _paused_tool_that_already_completed_chunks() -> List[Any]:
    """The paused requirement repeats a member tool call that already streamed to its end."""
    member = _member_kwargs("scout", "run-scout")
    streamed = ToolExecution(tool_call_id="tc-member-search", tool_name="search_docs", tool_args={"query": "agno"})
    completed = ToolExecution(
        tool_call_id="tc-member-search", tool_name="search_docs", tool_args={"query": "agno"}, result="three sources"
    )
    repeated = ToolExecution(
        tool_call_id="tc-member-search",
        tool_name="search_docs",
        tool_args={"query": "agno"},
        requires_confirmation=True,
    )
    requirement = _requirement(repeated, "scout", "run-scout", "Scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        ToolCallStartedEvent(tool=streamed, **member),
        ToolCallCompletedEvent(tool=completed, **member),
        TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_tool_that_already_ended_is_not_given_a_second_lifecycle(collect):
    events = await collect(_paused_tool_that_already_completed_chunks(), attributed())

    assert_stream_contains(events, EventType.TOOL_CALL_RESULT)
    assert in_emitted_order(events, EventType.TOOL_CALL_START, "tool_call_id", _lane) == [
        ("tc-member-search", "run-scout")
    ]
    assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id", _lane) == [
        ("tc-member-search", "run-scout")
    ]


def _paused_grandchild_chunks() -> List[Any]:
    """A sub-team's member pauses, and the requirement reaches the top-level terminal."""
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    outer_delegation = _delegation("tc-delegate-inner", "inner-team", "run the inner team")
    inner_delegation = _delegation("tc-delegate-scout", "scout", "scout the topic")
    member_tool = ToolExecution(
        tool_call_id="tc-scout-confirm",
        tool_name="send_email",
        tool_args={"to": "ops"},
        requires_confirmation=True,
    )
    requirement = _requirement(member_tool, "scout", "run-scout", "Scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=outer_delegation),
        TeamRunStartedEvent(**inner),
        TeamToolCallStartedEvent(tool=inner_delegation, **inner),
        TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_grandchild_is_announced_under_the_member_that_delegated_to_it(collect):
    events = await collect(_paused_grandchild_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED, 2)
    assert [
        (e.subagent_run_id, e.parent_subagent_run_id, e.parent_tool_call_id, e.description)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [
        ("run-inner", None, "tc-delegate-inner", "run the inner team"),
        ("run-scout", "run-inner", "tc-delegate-scout", "scout the topic"),
    ]
    # The grandchild resolves inside its real parent, so its terminal comes first.
    assert in_emitted_order(events, EventType.SUBAGENT_FINISHED, "subagent_run_id") == [("run-scout",), ("run-inner",)]


def _paused_inner_agent_chunks() -> List[Any]:
    """A single Agent pauses on a tool call its own inner agent is waiting on.

    An agent that runs an inner agent reports what that run is waiting on the
    way a team reports a member's: on the paused event's requirements, which
    name the run waiting and carry the pending call itself.
    """
    outer = {"agent_id": "assistant", "agent_name": "Assistant", "run_id": TOP_LEVEL_RUN}
    inner_tool = ToolExecution(
        tool_call_id="tc-inner-confirm",
        tool_name="send_email",
        tool_args={"to": "ops"},
        requires_confirmation=True,
    )
    requirement = _requirement(inner_tool, "memory-agent", "run-inner-agent", "Memory")

    return [
        RunStartedEvent(**outer),
        AgentRunPausedEvent(tools=[], requirements=[requirement], **outer),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_inner_agents_pending_tool_call_is_prompted_on_its_own_lane(collect):
    """The run cannot be resumed past a call the client was never shown."""
    events = await collect(_paused_inner_agent_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    assert [(e.subagent_run_id, e.name) for e in _announcements(events)] == [("run-inner-agent", "Memory")]  # type: ignore[attr-defined]
    assert _tool_call_lanes_in_order(events) == [("tc-inner-confirm", "run-inner-agent")]
    assert in_emitted_order(events, EventType.TOOL_CALL_ARGS, "tool_call_id", lambda e: json.loads(e.delta)) == [
        ("tc-inner-confirm", {"to": "ops"})
    ]
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)


@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_inner_agents_pending_tool_call_reaches_the_client_unattributed_too(collect):
    """Hidden does not name the inner run and still has to render the call it is waiting on."""
    events = await collect(_paused_inner_agent_chunks(), SUBAGENT_VISIBILITY_HIDDEN)

    assert_stream_contains(events, EventType.TOOL_CALL_START)
    assert _tool_call_lanes_in_order(events) == [("tc-inner-confirm", None)]
    assert in_emitted_order(events, EventType.TOOL_CALL_ARGS, "tool_call_id", lambda e: json.loads(e.delta)) == [
        ("tc-inner-confirm", {"to": "ops"})
    ]
    assert not [e for e in events if "SUBAGENT" in str(e.type)]


@pytest.mark.asyncio
@chunk_mappers
async def test_the_default_prompts_nothing_for_an_agent_pause_reported_only_through_requirements(collect):
    """The default stream is the pre-change one, which read requirements on a team's pause only.

    Losing the call is a real defect, and it is the pre-change default's, not
    this one's: the default is defined as that stream, so the pending call
    reaching the wire here would be a tool call a released client never
    received, and one it may auto-execute.
    """
    expected = [
        (str(EventType.RAW), {"event": "RunStarted"}),
        (str(EventType.RUN_FINISHED), {"threadId": THREAD_ID, "runId": TOP_LEVEL_RUN}),
    ]

    assert _normalized_payloads(await collect(_paused_inner_agent_chunks())) == expected
    assert _normalized_payloads(await collect(_paused_inner_agent_chunks(), SUBAGENT_VISIBILITY_INLINE)) == expected


# --- A lane whose terminal has already gone out -----------------------------

_INNER_TEAM = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)


def _sub_team_that_finished_holding_its_delegation_chunks(*tail: Any) -> List[Any]:
    """A sub-team reaches its own terminal with the delegation it made still open.

    A lane's terminal ends none of its tool calls, so that delegation outlives
    the lane, and it is the only open call naming the member below it.
    """
    delegation = _delegation("tc-delegate-scout", "scout", "scout the topic")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamRunStartedEvent(**_INNER_TEAM),
        TeamToolCallStartedEvent(tool=delegation, **_INNER_TEAM),
        TeamRunCompletedEvent(content="inner done", **_INNER_TEAM),
        *tail,
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_member_that_starts_after_its_parent_lane_terminated_is_not_announced_under_it(collect):
    """A lane the client has already closed can neither gain a child nor resolve after one."""
    member = _member_kwargs("scout", "run-scout", parent="run-inner")
    chunks = _sub_team_that_finished_holding_its_delegation_chunks(
        _agent_said("Scout speaking.", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    )

    # The delegation the sub-team left open is ended by the run-end sweep, which
    # is after that lane's own terminal: a lane's terminal ends no tool call.
    events = await collect(chunks, attributed(), exempt=[TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL])

    assert_stream_contains(events, EventType.SUBAGENT_STARTED, 2)
    assert [
        (e.subagent_run_id, e.parent_subagent_run_id, e.parent_tool_call_id, e.description)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-inner", None, None, None), ("run-scout", None, None, None)]
    # The empty entry is the sub-team's own parent message for its delegation.
    assert _messages_in_order(events) == [("Inner Team", ""), ("Scout", "Scout speaking.")]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_member_is_not_announced_under_a_parent_lane_that_terminated(collect):
    """The delegation that named the member outlives the lane that made it, and cannot speak for it."""
    tool = ToolExecution(
        tool_call_id="tc-scout-confirm",
        tool_name="send_email",
        tool_args={"to": "ops"},
        requires_confirmation=True,
    )
    requirement = _requirement(tool, "scout", "run-scout", "Scout")
    chunks = _sub_team_that_finished_holding_its_delegation_chunks(
        TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL),
    )

    events = await collect(chunks, attributed(), exempt=[TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL])

    assert_stream_contains(events, EventType.SUBAGENT_STARTED, 2)
    assert [
        (e.subagent_run_id, e.parent_subagent_run_id, e.parent_tool_call_id, e.description)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-inner", None, None, None), ("run-scout", None, None, None)]
    # The prompt itself is still the member's, on the member's own lane.
    assert _tool_call_lanes_in_order(events) == [
        ("tc-delegate-scout", "run-inner"),
        ("tc-scout-confirm", "run-scout"),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_member_is_still_linked_to_a_delegation_its_parent_lane_is_still_running(collect):
    """The other half of that rule: a live lane's open delegation is the link it always was."""
    tool = ToolExecution(
        tool_call_id="tc-scout-confirm",
        tool_name="send_email",
        tool_args={"to": "ops"},
        requires_confirmation=True,
    )
    requirement = _requirement(tool, "scout", "run-scout", "Scout")
    delegation = _delegation("tc-delegate-scout", "scout", "scout the topic")

    chunks = [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamRunStartedEvent(**_INNER_TEAM),
        TeamToolCallStartedEvent(tool=delegation, **_INNER_TEAM),
        TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL),
    ]

    events = await collect(chunks, attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED, 2)
    assert [
        (e.subagent_run_id, e.parent_subagent_run_id, e.parent_tool_call_id, e.description)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-inner", None, None, None), ("run-scout", "run-inner", "tc-delegate-scout", "scout the topic")]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_members_own_pause_is_not_dumped_to_the_wire(collect):
    events = await collect(_paused_member_chunks(), attributed())

    assert_stream_contains(events, EventType.RAW)
    assert_stream_contains(events, EventType.TOOL_CALL_START, 2)
    # The member's other chunks do reach the wire as RAW, on its own lane, so
    # the absence below is this one event being withheld rather than the whole
    # lane going unmapped. The name is the framework's own rather than a literal.
    raw = in_emitted_order(events, EventType.RAW, lambda e: e.event.get("event"), _lane)  # type: ignore[attr-defined]
    assert (RunEvent.run_started.value, "run-scout") in raw, raw
    assert RunEvent.run_paused.value not in [name for name, _ in raw]
    # The pending call still reaches the client once, from the team's requirement.
    assert [e.tool_call_id for e in _of_type(events, EventType.TOOL_CALL_START)] == [  # type: ignore[attr-defined]
        "tc-leader-confirm",
        "tc-member-confirm",
    ]


def _pause_reported_by_a_member_whose_lane_closed_chunks() -> List[Any]:
    """A member finishes, and then its own pause is the last thing the stream carries.

    The pause is reported from the member's run, so the run terminal is built
    out of a chunk whose lane the wire has already terminated.
    """
    member = _member_kwargs("scout", "run-scout")
    pending = ToolExecution(
        tool_call_id="tc-member-confirm", tool_name="send_email", tool_args={"to": "ops"}, requires_confirmation=True
    )
    paused = AgentRunPausedEvent(tools=[pending], **member)
    paused.content = "I need approval to email ops."
    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=_delegation("tc-delegate-scout", "scout", "scout it")),
        RunStartedEvent(**member),
        _agent_said("half a sen", **member),
        RunCompletedEvent(content="scout done", **member),
        paused,
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_pause_a_member_reports_after_its_own_terminal_is_prompted_on_the_root_lane(collect):
    """A terminal is final for the lane it names, and this prompt is what would break that.

    The pause is the run terminal here, so the prompt is built out of a chunk of
    the member's. Named after it, every event of the prompt would carry that
    member: the message, the words on it, and the three the pending call takes,
    all of them after the lane's own terminal.
    """
    events = await collect(_pause_reported_by_a_member_whose_lane_closed_chunks(), attributed())

    finished = _of_type(events, EventType.SUBAGENT_FINISHED)
    assert [event.subagent_run_id for event in finished] == ["run-scout"]  # type: ignore[attr-defined]
    after = events[events.index(finished[0]) + 1 :]
    assert [(str(event.type), _lane(event)) for event in after if _lane(event) is not None] == []
    # The pending call still reaches the client, unattributed, because no resume
    # gets past a call nobody was shown.
    assert _tool_call_lanes_in_order(events) == [("tc-delegate-scout", None), ("tc-member-confirm", None)]
    # The member's own words are not relabeled as the leader's on the way out.
    assert "I need approval to email ops." not in [
        event.delta  # type: ignore[attr-defined]
        for event in _of_type(events, EventType.TEXT_MESSAGE_CONTENT)
    ]


def _paused_member_the_run_names_by_id_alone_chunks() -> List[Any]:
    """A pause whose requirement carries the member's id and no name of its own."""
    pending = ToolExecution(
        tool_call_id="tc-scout-confirm", tool_name="send_email", tool_args={"to": "ops"}, requires_confirmation=True
    )
    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamRunPausedEvent(tools=[], requirements=[_requirement(pending, "scout", "run-scout")], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_member_with_no_name_is_announced_under_its_id(collect):
    """The id is what the framework always has, and a lane announced under nothing is unreadable.

    The streamed announcement falls back the same way and is pinned elsewhere.
    This is the pause path's own copy of that fallback, which nothing reached.
    """
    events = await collect(_paused_member_the_run_names_by_id_alone_chunks(), attributed())

    assert [(e.subagent_run_id, e.name) for e in _announcements(events)] == [("run-scout", "scout")]  # type: ignore[attr-defined]
    assert _tool_call_lanes_in_order(events) == [("tc-scout-confirm", "run-scout")]


# --- Run-end ordering -------------------------------------------------------


def _member_open_inside_a_delegation_chunks(fail: bool) -> List[Any]:
    """The leader is mid-sentence with a delegation open and its member still running."""
    delegation = _delegation("tc-delegate-scout", "scout", "scout it")
    member = _member_kwargs("scout", "run-scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=delegation),
        _team_said("Delegating now.", **_TOP_LEVEL),
        RunStartedEvent(**member),
        _agent_said("scouting", **member),
        TeamRunErrorEvent(content="team blew up", error_type="RuntimeError", **_TOP_LEVEL)
        if fail
        else TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


def _member_terminal_index(events: List[BaseEvent]) -> int:
    terminals = [index for index, event in enumerate(events) if _is_terminal(event)]
    assert len(terminals) == 1, f"expected one member terminal, got {len(terminals)}"
    return terminals[0]


@needs_lineage_events
@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True], ids=["run_completed", "run_errored"])
@chunk_mappers
async def test_a_member_terminal_lands_outside_every_span_the_stream_had_open(collect, fail):
    """The run end closes what is open first, so no terminal is nested in anything.

    A tool call admits only its own arguments and its end between the two, and a
    message admits only its own content, so a member terminal landing inside
    either is a stream a validating client rejects. That covers the delegation
    call the member was running inside, which closes before the terminal rather
    than after it.
    """
    events = await collect(_member_open_inside_a_delegation_chunks(fail), attributed())
    terminal_at = _member_terminal_index(events)

    delegation_close_at = [
        index
        for index, event in enumerate(events)
        if event.type == EventType.TOOL_CALL_END and getattr(event, "tool_call_id", None) == "tc-delegate-scout"  # type: ignore[attr-defined]
    ]
    assert delegation_close_at, "the delegation tool call was never closed"
    assert delegation_close_at[0] < terminal_at

    open_messages: Set[str] = set()
    open_tool_calls: Set[str] = set()
    for index, event in enumerate(events):
        if index == terminal_at:
            assert not open_messages, f"a member terminal landed inside open messages {sorted(open_messages)}"
            assert not open_tool_calls, f"a member terminal landed inside open tool calls {sorted(open_tool_calls)}"
        if event.type == EventType.TEXT_MESSAGE_START:
            open_messages.add(event.message_id)  # type: ignore[attr-defined]
        elif event.type == EventType.TEXT_MESSAGE_END:
            open_messages.discard(event.message_id)  # type: ignore[attr-defined]
        elif event.type == EventType.TOOL_CALL_START:
            open_tool_calls.add(event.tool_call_id)  # type: ignore[attr-defined]
        elif event.type == EventType.TOOL_CALL_END:
            open_tool_calls.discard(event.tool_call_id)  # type: ignore[attr-defined]


# --- Cancellation -----------------------------------------------------------


def _cancelled_member_chunks() -> List[Any]:
    member = _member_kwargs("scout", "run-scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        RunCancelledEvent(reason="user cancelled the run", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_cancelled_member_is_not_reported_as_a_success(collect):
    events = await collect(_cancelled_member_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_ERROR)
    assert not _of_type(events, EventType.SUBAGENT_FINISHED)
    assert [(e.subagent_run_id, e.message, e.code) for e in _of_type(events, EventType.SUBAGENT_ERROR)] == [  # type: ignore[attr-defined]
        ("run-scout", "user cancelled the run", "cancelled")
    ]
    # The member's other chunks do reach the wire as RAW, on its own lane, so
    # the absence below is this one event being withheld rather than the whole
    # lane going unmapped. The name is the framework's own rather than a literal.
    assert_stream_contains(events, EventType.RAW)
    raw = in_emitted_order(events, EventType.RAW, lambda e: e.event.get("event"), _lane)  # type: ignore[attr-defined]
    assert (RunEvent.run_started.value, "run-scout") in raw, raw
    assert RunEvent.run_cancelled.value not in [name for name, _ in raw]


# --- Withheld failures are still recorded -----------------------------------


def _failing_member_chunks() -> List[Any]:
    member = _member_kwargs("scout", "run-scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        RunErrorEvent(
            content="member exploded",
            error_type="RuntimeError",
            error_id="err-42",
            additional_data={"attempt": 2},
            **member,
        ),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunk_factory,expected",
    [
        (_failing_member_chunks, "member exploded"),
        (_cancelled_member_chunks, "user cancelled the run"),
    ],
    ids=["error", "cancellation"],
)
@chunk_mappers
async def test_hidden_records_a_member_failure_it_withholds(collect, caplog, chunk_factory, expected):
    with captured_agno_logs(caplog, "WARNING"):
        events = await collect(chunk_factory(), SUBAGENT_VISIBILITY_HIDDEN)

    # Hidden withholds what identifies the member, not the fact that it failed.
    assert not [e for e in events if "SUBAGENT" in str(e.type)]
    assert not [e for e in events if _lane(e) is not None]
    assert [r.message for r in caplog.records if expected in r.message]


_SCOUT = _member_kwargs("scout", "run-scout")
_WRITER = _member_kwargs("writer", "run-writer")

# One chunk per way a member's run stops, with the text that member carried.
# Keyed by the normalized event name so the coverage check below can compare
# them with the events the interface itself treats as ending a member: a
# terminal kind added there without a case here fails that check rather than
# going unexamined by everything generated from this table.
_MEMBER_RUN_TERMINALS: Dict[str, Tuple[Callable[[], Any], str]] = {
    RunEvent.run_completed.value: (lambda: RunCompletedEvent(content="scout finished", **_SCOUT), "scout finished"),
    RunEvent.run_error.value: (lambda: RunErrorEvent(content="scout exploded", **_SCOUT), "scout exploded"),
    RunEvent.run_cancelled.value: (
        lambda: RunCancelledEvent(reason="operator stopped scout", **_SCOUT),
        "operator stopped scout",
    ),
    RunEvent.run_paused.value: (
        lambda: AgentRunPausedEvent(
            tools=[_pending("tc-scout-confirm", requires_confirmation=True)], content="scout is waiting", **_SCOUT
        ),
        "scout is waiting",
    ),
}


def test_every_way_a_member_run_stops_has_a_case():
    """The cases generated from the table are the class, checked against the interface's list."""
    missing = sorted(handlers._SUBAGENT_RUN_ENDING_EVENTS.difference(_MEMBER_RUN_TERMINALS))
    assert not missing, f"these member terminals have no case: {missing}"


def _member_run_ending_chunks(terminal: Any) -> List[Any]:
    """A run whose last chunk is one member terminal, so that terminal is the run's."""
    return [TeamRunStartedEvent(**_TOP_LEVEL), RunStartedEvent(**_SCOUT), terminal]


_WAYS_A_MEMBER_STOPS_UNDER_HIDDEN: Dict[str, Tuple[Callable[[], List[Any]], str]] = {
    name: (lambda build=build: _member_run_ending_chunks(build()), text)  # type: ignore[misc]
    for name, (build, text) in _MEMBER_RUN_TERMINALS.items()
}
# Not a way a member's run stops, and here for the contrast: a tool call
# failure ends no run, so nothing of it can reach the client and its record
# must not say otherwise.
_WAYS_A_MEMBER_STOPS_UNDER_HIDDEN[RunEvent.tool_call_error.value] = (
    lambda: _member_run_ending_chunks(
        ToolCallErrorEvent(
            tool=ToolExecution(tool_call_id="tc-boom", tool_name="search_docs"),
            error="scout's tool exploded",
            **_SCOUT,
        )
    ),
    "scout's tool exploded",
)


@pytest.mark.asyncio
@chunk_mappers
@pytest.mark.parametrize(
    "way", sorted(_WAYS_A_MEMBER_STOPS_UNDER_HIDDEN), ids=sorted(_WAYS_A_MEMBER_STOPS_UNDER_HIDDEN)
)
async def test_a_hidden_record_claims_the_reason_reached_the_client_exactly_when_it_did(collect, caplog, way):
    """``hidden`` withholds the member's identity, and its record may not overstate that.

    A member's terminal can be the only account the stream carries of how the
    run ended, and is then read as the run's, so the text that member carried
    reaches the client as the reason the run stopped even though nothing on the
    wire names the member. Whether the record says so is checked against
    whether the terminal really carries that text, over every way a member's
    run can stop rather than over the one that was reported, so a terminal kind
    added later cannot arrive with a record that claims the client was told
    nothing while the client is reading the member's own words.
    """
    build, text = _WAYS_A_MEMBER_STOPS_UNDER_HIDDEN[way]
    with captured_agno_logs(caplog, "WARNING"):
        events = await collect(build(), SUBAGENT_VISIBILITY_HIDDEN)

    assert not [e for e in events if "SUBAGENT" in str(e.type)]
    assert not [e for e in events if _lane(e) is not None]
    reason_on_the_wire = getattr(events[-1], "message", None)
    claims = [r.message for r in caplog.records if handlers._REASON_STILL_REACHES_THE_CLIENT in r.message]

    if reason_on_the_wire == text:
        assert claims, f"the {way} record does not say the client is reading this member's own words"
        assert all(text in claim for claim in claims)
    else:
        assert not claims, f"the {way} record claims a reason reached the client, and {reason_on_the_wire!r} did"


@pytest.mark.asyncio
@malformed_mappers
@pytest.mark.parametrize(
    "setting",
    [lambda: None, lambda: SUBAGENT_VISIBILITY_INLINE, attributed, lambda: SUBAGENT_VISIBILITY_HIDDEN],
    ids=["default", "inline", "attributed", "hidden"],
)
@pytest.mark.parametrize("stopped", sorted(_MEMBER_RUN_TERMINALS), ids=sorted(_MEMBER_RUN_TERMINALS))
async def test_the_last_member_terminal_is_the_one_the_run_terminal_is_built_from(collect_malformed, setting, stopped):
    """No member terminal outranks a later one, whichever way the earlier member stopped.

    A run that reported no terminal of its own is described by the last member
    terminal the stream carried and by nothing else. So a member that fails, and
    then another member that completes, ends the run as a completion, and a
    member that pauses followed by another member completing loses the pending
    call the pause was waiting on: a completion carries none to prompt with.
    Both hold under every setting, the default included, which is why the whole
    class runs against all four rather than being described as a lineage
    difference.

    Driven through the collector that records violations, because the paused
    arm leaves the member's own pending call opened by the stream and never
    prompted, which the shared checker has an opinion about.
    """
    build, _ = _MEMBER_RUN_TERMINALS[stopped]
    chunks = [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**_SCOUT),
        build(),
        RunStartedEvent(**_WRITER),
        RunCompletedEvent(content="writer finished", **_WRITER),
    ]

    events, error, _ = await collect_malformed(chunks, setting(), thread_id=THREAD_ID, run_id=TOP_LEVEL_RUN)

    assert error is None
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)
    assert getattr(events[-1], "message", None) is None
    # Nothing the run stopped for is prompted: the completion the terminal is
    # built from asks the client to resolve nothing.
    assert not _of_type(events, EventType.TOOL_CALL_START)


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_member_failure_is_logged_once_and_that_line_carries_the_ids(collect, caplog):
    """One line, carrying everything an operator needs to find the failure again.

    Read off the single record rather than off every record joined together: an
    operator reads one line at a time, so identifiers scattered across separate
    lines are identifiers that line does not have.
    """
    with captured_agno_logs(caplog, "ERROR"):
        events = await collect(_failing_member_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_ERROR)
    assert [(e.subagent_run_id, e.message, e.code) for e in _of_type(events, EventType.SUBAGENT_ERROR)] == [  # type: ignore[attr-defined]
        ("run-scout", "member exploded", "RuntimeError")
    ]
    failures = [r.message for r in caplog.records if "member exploded" in r.message]
    assert len(failures) == 1, f"one failure was recorded {len(failures)} times: {failures}"
    assert "err-42" in failures[0], failures[0]
    assert "attempt" in failures[0], failures[0]


def _member_error_after_its_terminal_chunks() -> List[Any]:
    """A member reports a failure after its own terminal has already gone out."""
    member = _member_kwargs("scout", "run-scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        RunCompletedEvent(content="scout done", **member),
        RunErrorEvent(content="too late", error_type="RuntimeError", error_id="err-99", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_failure_arriving_after_its_members_terminal_is_recorded_and_sends_no_second_terminal(collect, caplog):
    """A terminal is final for the lane it names, so the late failure is recorded instead.

    A second terminal for the same id would be a protocol violation, so the log
    line is the only account of this failure and has to carry what an operator
    needs from it: which lane failed, that the lane had already terminated so
    the client was told nothing, and the identifiers the failure was reported
    with.
    """
    with captured_agno_logs(caplog, "ERROR"):
        events = await collect(_member_error_after_its_terminal_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_FINISHED)
    # The one terminal the lane owns is its own, carrying what its run reported
    # before the failure, and no error terminal joins it.
    assert in_emitted_order(events, EventType.SUBAGENT_FINISHED, "subagent_run_id", "result") == [
        ("run-scout", "scout done")
    ]
    assert in_emitted_order(events, EventType.SUBAGENT_ERROR, "subagent_run_id", "message") == []

    recorded = [r.message for r in caplog.records if "too late" in r.message]
    assert len(recorded) == 1, f"the late failure was recorded {len(recorded)} times: {recorded}"
    assert "run-scout" in recorded[0], recorded[0]
    assert "already terminated" in recorded[0], recorded[0]
    assert "RuntimeError" in recorded[0], recorded[0]
    assert "err-99" in recorded[0], recorded[0]


# --- Serializing a member's result ------------------------------------------


class _ExplodingDump:
    """A result whose model dump raises, as a partly-built pydantic object can."""

    def model_dump_json(self) -> str:
        raise RuntimeError("dump exploded")

    def __str__(self) -> str:
        return "exploding result"


@needs_lineage_events
@pytest.mark.asyncio
@pytest.mark.parametrize(
    # Built per case rather than at collection time, so the two mappers cannot
    # hand each other a result one of them has already mutated. What each falls
    # back to is stated: an expectation of "some string" holds for every result
    # the interface could possibly report. Every route that gave way on the way
    # there is stated too, because a fallback nobody is told about is a member
    # result quietly replaced by something else.
    "content_factory,expected,recorded",
    [
        (
            _ExplodingDump,
            "exploding result",
            ("could not dump a subagent result", "could not serialize a subagent result"),
        ),
        (circular, "{'self': {...}}", ("could not serialize a subagent result",)),
    ],
    ids=["model_dump_raises", "cyclic_content"],
)
@chunk_mappers
async def test_an_unserializable_member_result_never_fails_the_run(
    collect, caplog, content_factory, expected, recorded
):
    with captured_agno_logs(caplog, "WARNING"):
        events = await collect(_member_result_chunks(content_factory()), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_FINISHED)
    finished = _of_type(events, EventType.SUBAGENT_FINISHED)

    assert [e.subagent_run_id for e in finished] == ["run-scout"]  # type: ignore[attr-defined]
    assert finished[0].result == expected  # type: ignore[attr-defined]
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)
    assert not _of_type(events, EventType.RUN_ERROR)
    logged = [record.message for record in caplog.records]
    for fragment in recorded:
        assert [message for message in logged if fragment in message], (
            f"the result the interface could not serialize left no trace of {fragment!r}: {logged}"
        )


# --- The lane stamp ---------------------------------------------------------

_SCOUT_LANE = "run-scout"


def _member_alone_chunks(*inner: Any) -> List[Any]:
    """A team whose only speaker is one member, with no delegation call of the leader's.

    The leader stays silent so that every event of a given type on the stream is
    the member's, which is what lets the lanes below be stated as an exact list
    rather than as a set with the leader's copies filtered out.
    """
    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**_SCOUT),
        *inner,
        RunCompletedEvent(content="scout done", **_SCOUT),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


def _a_member_spoke() -> List[Any]:
    return _member_alone_chunks(_agent_said("scouting", **_SCOUT))


def _a_member_called_a_tool() -> List[Any]:
    tool = ToolExecution(tool_call_id="tc-scout", tool_name="search_docs", tool_args={"query": "agno"}, result="three")
    return _member_alone_chunks(ToolCallStartedEvent(tool=tool, **_SCOUT), ToolCallCompletedEvent(tool=tool, **_SCOUT))


def _a_member_reasoned() -> List[Any]:
    delta = ReasoningContentDeltaEvent(**_SCOUT)
    delta.reasoning_content = "first I "
    return _member_alone_chunks(ReasoningStartedEvent(**_SCOUT), delta, ReasoningCompletedEvent(**_SCOUT))


def _a_member_emitted_a_custom_event() -> List[Any]:
    chunk = CustomEvent(**_SCOUT)
    chunk.to_dict = lambda: {"event": "Custom", "payload": {"progress": 1}}  # type: ignore[method-assign]
    return _member_alone_chunks(chunk)


# One stream per attributable event type, with the lanes that type's events
# carry on it, in order. Keyed by event name and checked against the stamp's own
# set below, so an event type added to that set is driven here or named.
_ATTRIBUTED_ON_A_MEMBER_LANE: Dict[str, Tuple[Callable[[], List[Any]], Tuple[Optional[str], ...]]] = {
    # The team's own run-started chunk is unmapped too, and it is the leading
    # unstamped RAW here; the member's is the stamped one.
    "RAW": (_member_alone_chunks, (None, _SCOUT_LANE)),
    "TEXT_MESSAGE_START": (_a_member_spoke, (_SCOUT_LANE,)),
    "TEXT_MESSAGE_CONTENT": (_a_member_spoke, (_SCOUT_LANE,)),
    "TEXT_MESSAGE_END": (_a_member_spoke, (_SCOUT_LANE,)),
    # A tool call opens a message of the member's own to hang itself off, which
    # is why this stream carries a text span with no content in it.
    "TOOL_CALL_START": (_a_member_called_a_tool, (_SCOUT_LANE,)),
    "TOOL_CALL_ARGS": (_a_member_called_a_tool, (_SCOUT_LANE,)),
    "TOOL_CALL_END": (_a_member_called_a_tool, (_SCOUT_LANE,)),
    "TOOL_CALL_RESULT": (_a_member_called_a_tool, (_SCOUT_LANE,)),
    "REASONING_START": (_a_member_reasoned, (_SCOUT_LANE,)),
    "REASONING_MESSAGE_START": (_a_member_reasoned, (_SCOUT_LANE,)),
    "REASONING_MESSAGE_CONTENT": (_a_member_reasoned, (_SCOUT_LANE,)),
    "REASONING_MESSAGE_END": (_a_member_reasoned, (_SCOUT_LANE,)),
    "REASONING_END": (_a_member_reasoned, (_SCOUT_LANE,)),
    "CUSTOM": (_a_member_emitted_a_custom_event, (_SCOUT_LANE,)),
}


def test_every_event_type_the_stamp_attributes_is_driven_onto_a_member_lane():
    """The coverage is derived from the stamp's own set, so a type added to it lands here.

    Named per event type rather than counted: a type nothing here puts on a
    member's lane is one the stamp could skip with every test in this folder
    still green, which is exactly what CUSTOM was.
    """
    attributable = _enumerated_by_the_interface(
        {event_type.value for event_type in handlers._SUBAGENT_ATTRIBUTABLE_EVENT_TYPES},
        EventType.CUSTOM.value,
        described="the event types the lane stamp attributes",
    )
    assert set(_ATTRIBUTED_ON_A_MEMBER_LANE) == attributable, (
        "these event types are attributable and no stream here puts one on a member's lane: "
        f"{sorted(attributable - set(_ATTRIBUTED_ON_A_MEMBER_LANE))}; and these are driven here and no "
        f"longer attributable: {sorted(set(_ATTRIBUTED_ON_A_MEMBER_LANE) - attributable)}"
    )


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
@pytest.mark.parametrize("event_name", sorted(_ATTRIBUTED_ON_A_MEMBER_LANE))
async def test_an_attributable_event_a_member_produced_carries_that_member(collect, event_name):
    """Every attributable type, on the member that produced it, by payload and in order."""
    chunks, expected = _ATTRIBUTED_ON_A_MEMBER_LANE[event_name]
    event_type = event_type_named(event_name)
    events = await collect(chunks(), attributed())

    assert_stream_contains(events, event_type)
    assert [lane for (lane,) in in_emitted_order(events, event_type, _lane)] == list(expected)


class _EventWithoutLineage(BaseModel):
    """An attributable event from a protocol release that cannot express a lane."""

    model_config = {"extra": "allow"}

    type: EventType = EventType.TEXT_MESSAGE_START


@needs_lineage_events
def test_a_protocol_that_cannot_carry_a_lane_is_refused_before_the_run_starts(monkeypatch):
    """The refusal belongs at startup: mid-stream it would abort a run a client is already reading.

    Gated, because this is the refusal for a release that HAS the lineage events
    and not the field. A release with neither is refused for the missing events,
    which is the test above.
    """
    visibility = attributed()
    monkeypatch.setitem(handlers._ATTRIBUTABLE_EVENT_CLASSES, EventType.TEXT_MESSAGE_START, _EventWithoutLineage)

    with pytest.raises(ValueError, match="subagent_run_id"):
        validate_subagent_visibility(visibility)
    # The settings that never stamp an event keep working on such a release.
    assert validate_subagent_visibility(SUBAGENT_VISIBILITY_INLINE) == SUBAGENT_VISIBILITY_INLINE
    assert validate_subagent_visibility(SUBAGENT_VISIBILITY_HIDDEN) == SUBAGENT_VISIBILITY_HIDDEN


class _AnnouncementWithoutADescription(BaseModel):
    """An announcement from a protocol release that declares no description field."""

    model_config = {"extra": "allow"}

    subagent_run_id: str = ""
    name: str = ""
    parent_subagent_run_id: Optional[str] = None
    parent_tool_call_id: Optional[str] = None
    parent_message_id: Optional[str] = None


def _one_of_the_protocols_events(name: str) -> bool:
    """Whether this class is one of the protocol's events rather than an outcome.

    Resolved against the installed release, because what separates the two is
    where the discriminator comes from: an event inherits it from the base every
    release declares, and an outcome brought its own with it.
    """
    import ag_ui.core

    candidate = getattr(ag_ui.core, name, None)
    return isinstance(candidate, type) and issubclass(candidate, BaseEvent)


def _lineage_fields_the_interface_writes(event_class_names: Set[str]) -> Dict[str, Set[str]]:
    """The arguments the interface really passes to each lineage event class.

    Every module of the interface package is read, not just the one that happens
    to construct these today, and the call sites are matched against the exact
    class names the startup check enumerates rather than against a name prefix:
    the state module declares its own ``Subagent`` record, which a prefix match
    would count as a protocol event and compare its fields against the wire's.

    Positional and starred arguments are refused rather than skipped. This scan
    can put no name to either, so a field written that way would be missing from
    what it returns and read as a field the interface does not write at all.
    """
    package = Path(handlers.__file__).parent
    written: Dict[str, Set[str]] = {}
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in event_class_names:
                continue
            assert not node.args, (
                f"{path.name} builds a {node.func.id} with positional arguments, which this scan cannot name"
            )
            assert all(keyword.arg is not None for keyword in node.keywords), (
                f"{path.name} builds a {node.func.id} from a starred mapping, which this scan cannot read"
            )
            # ``type`` on an event is the protocol's own discriminator, declared
            # by the base every release carries, so it is not one of the fields
            # at issue. On an outcome it is the tag the union is read by, and it
            # arrived with the outcome itself, so it is one of them: excluding it
            # everywhere is how a tag written by two builders stayed invisible to
            # both this scan and the check it feeds.
            written.setdefault(node.func.id, set()).update(
                keyword.arg
                for keyword in node.keywords
                if keyword.arg is not None
                and not (keyword.arg == "type" and _one_of_the_protocols_events(node.func.id))
            )
    return written


# The suspended outcome's own contribution to what the interface writes. The
# interrupt round trip builds both of these behind its suspension probe, so a
# release without that outcome detects neither while the source still reads as
# writing them and nothing can reach the wire under either name. Named here so
# the comparison below holds on such a release, and checked against the probe's
# own table wherever it is served, so the two cannot drift.
_SUSPENDED_OUTCOME_WRITES: Dict[str, Set[str]] = {
    "SubagentFinishedEvent": {"outcome"},
    "SubagentFinishedSuspendedOutcome": {"type", "interrupt_ids"},
}


@needs_lineage_events
def test_the_startup_check_feature_detects_every_lineage_field_the_interface_writes():
    """A field nothing detects is one an older protocol takes as an undeclared attribute.

    The protocol models accept what they do not declare, so a release missing
    one of these does not raise: the value rides out under the name written
    here instead of the one the wire format defines, and the client reads a lane
    with no description, no parent or no result.
    """
    lineage: Dict[str, Set[str]] = {
        event_class.__name__: set(field_names) for event_class, field_names in handlers._lineage_event_fields().items()
    }
    # The scan below is handed the very names this table is keyed by, so an
    # empty table leaves it scanning for nothing and the comparison is between
    # two empty mappings. The three classes the interface builds are the floor.
    scanned_for = _enumerated_by_the_interface(
        lineage,
        "SubagentStartedEvent",
        "SubagentFinishedEvent",
        "SubagentErrorEvent",
        described="the lineage classes the startup check feature-detects fields on",
    ) | set(_SUSPENDED_OUTCOME_WRITES)
    # The interrupt round trip's own check, kept separate because the protocol
    # added the suspended outcome after the lineage events: a release carrying
    # that outcome has to detect exactly the fields written for it, and a
    # release without it has no class to key them by and detects none.
    suspension = {
        event_class.__name__: set(field_names)
        for event_class, field_names in interrupts.subagent_suspension_fields().items()
    }
    assert suspension == (_SUSPENDED_OUTCOME_WRITES if interrupts.SUBAGENT_SUSPENDED_OUTCOME_AVAILABLE else {})
    detected = {name: set(field_names) for name, field_names in lineage.items()}
    for name, field_names in _SUSPENDED_OUTCOME_WRITES.items():
        detected.setdefault(name, set()).update(field_names)

    assert _lineage_fields_the_interface_writes(scanned_for) == detected


@needs_lineage_events
def test_a_protocol_missing_a_field_an_announcement_carries_is_refused_before_the_run_starts(monkeypatch):
    visibility = attributed()
    # The release accepts the write and keeps it as an undeclared attribute,
    # which is why the field has to be detected rather than trusted.
    silently_accepted = _AnnouncementWithoutADescription(description="scout the topic")
    assert silently_accepted.description == "scout the topic"  # type: ignore[attr-defined]

    monkeypatch.setattr(handlers, "SubagentStartedEvent", _AnnouncementWithoutADescription)

    # The refusal names the class this install really carries, not the one the
    # protocol would have provided.
    with pytest.raises(ValueError, match=rf"{_AnnouncementWithoutADescription.__name__}\.description"):
        validate_subagent_visibility(visibility)
    # The settings that emit no lineage event keep working on such a release.
    assert validate_subagent_visibility(SUBAGENT_VISIBILITY_INLINE) == SUBAGENT_VISIBILITY_INLINE
    assert validate_subagent_visibility(SUBAGENT_VISIBILITY_HIDDEN) == SUBAGENT_VISIBILITY_HIDDEN


def test_the_lane_stamp_cannot_fail_a_run_that_has_already_started():
    stamped = handlers._stamp_lane([_EventWithoutLineage()], "run-scout")  # type: ignore[list-item]

    assert [_lane(e) for e in stamped] == [None]


def test_the_startup_check_covers_every_event_type_the_stamp_attributes():
    """Feature-detecting a class the stamp never writes to would leave the mid-stream path exposed.

    The set the stamp tests against is derived from the classes the startup
    check reads, so the two cannot disagree and nothing here compares them.
    What can drift is a class registered under an event type it does not carry:
    the stamp would then skip an event the startup check cleared.
    """
    attributable = handlers._ATTRIBUTABLE_EVENT_CLASSES
    # A registry that lost its entries stamps nothing and leaves the startup
    # check nothing to feature-detect, and the assertion below holds for it, so
    # the floor is stated first.
    _enumerated_by_the_interface(
        attributable, EventType.TEXT_MESSAGE_START, described="the event classes the lane stamp attributes"
    )
    mismatched = {
        event_type: event_class.__name__
        for event_type, event_class in attributable.items()
        if event_class.model_fields["type"].default is not event_type
    }
    assert not mismatched, f"these classes do not carry the event type they are registered under: {mismatched}"


@needs_lineage_events
def test_the_lane_stamp_writes_the_declared_field_and_keeps_an_explicit_one():
    from ag_ui.core import TextMessageStartEvent

    plain = TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id="m-1", role="assistant")
    (stamped,) = handlers._stamp_lane([plain], "run-scout")
    assert stamped.subagent_run_id == "run-scout"  # type: ignore[attr-defined]

    explicit = TextMessageStartEvent(
        type=EventType.TEXT_MESSAGE_START, message_id="m-2", role="assistant", subagent_run_id="run-other"
    )
    (kept,) = handlers._stamp_lane([explicit], "run-scout")
    assert kept.subagent_run_id == "run-other"  # type: ignore[attr-defined]


# --- Where the setting is validated -----------------------------------------


def test_the_routes_refuse_an_invalid_visibility_when_they_are_mounted():
    from fastapi import APIRouter

    from agno.os.interfaces.agui.router import attach_routes

    with pytest.raises(ValueError, match="subagent_visibility must be one of"):
        attach_routes(APIRouter(), team=_two_member_team(InMemoryDb()), subagent_visibility="loud")


def test_the_stream_state_refuses_an_invalid_visibility():
    with pytest.raises(ValueError, match="subagent_visibility must be one of"):
        StreamState(subagent_visibility="loud")


def test_a_missing_agent_or_team_is_reported_before_the_visibility():
    from agno.os.interfaces.agui import AGUI

    with pytest.raises(ValueError, match="requires an agent or a team"):
        AGUI(subagent_visibility="loud")


# --- What the docs claim ----------------------------------------------------


def _inner_agent_of_a_single_agent_chunks() -> List[Any]:
    """A context provider runs an agent inside the outer run and stamps the outer run as its parent."""
    outer = {"agent_id": "assistant", "agent_name": "Assistant", "run_id": TOP_LEVEL_RUN}
    inner = {
        "agent_id": "memory-agent",
        "agent_name": "Memory",
        "run_id": "run-inner-agent",
        "parent_run_id": TOP_LEVEL_RUN,
    }

    return [
        RunStartedEvent(**outer),
        _agent_said("inner agent speaking", **inner),
        _agent_said("outer agent speaking", **outer),
        RunCompletedEvent(**outer),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_single_agents_inner_agent_becomes_a_lane_under_attributed(collect):
    events = await collect(_inner_agent_of_a_single_agent_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    assert [(e.subagent_run_id, e.name) for e in _announcements(events)] == [("run-inner-agent", "Memory")]  # type: ignore[attr-defined]
    assert _messages_in_order(events) == [("Memory", "inner agent speaking"), (None, "outer agent speaking")]


@pytest.mark.asyncio
@chunk_mappers
async def test_a_single_agents_inner_agent_is_withheld_under_hidden(collect):
    events = await collect(_inner_agent_of_a_single_agent_chunks(), SUBAGENT_VISIBILITY_HIDDEN)

    assert _messages_in_order(events) == [(None, "outer agent speaking")]


def test_a_direct_child_lane_reports_the_same_depth_as_the_root():
    state = StreamState(subagent_visibility=attributed(), root_run_id=TOP_LEVEL_RUN)
    state.open_subagent("run-child", name="Child", parent_lane=None)
    state.open_subagent("run-grandchild", name="Grandchild", parent_lane="run-child")

    assert (state.lane_depth(ROOT_LANE), state.lane_depth("run-child"), state.lane_depth("run-grandchild")) == (0, 0, 1)


def _within(seconds: float, described: str, call: Callable[[], Any]) -> Any:
    """The call's result, failing rather than hanging when it does not return.

    A parent chain that closes on itself is walked by the ordering helpers
    below, and a walk that looped would wedge a run with no output and no
    failure anywhere. The wait is therefore bounded, and the thread is a
    daemon so a wedged walk cannot hold the suite open either.

    Whatever the call raised is re-raised here rather than left in the worker:
    reading the result by index instead would turn every exception inside the
    walk into a bare IndexError on an empty list, which names neither the walk
    nor what went wrong in it.
    """
    outcome: Dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["returned"] = call()
        except BaseException as raised:  # noqa: BLE001 - re-raised below, in the calling thread
            outcome["raised"] = raised

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    assert not worker.is_alive(), (
        f"{described} did not return within {seconds}s, so a parent chain that closes on itself is walked forever"
    )
    if "raised" in outcome:
        raise AssertionError(f"{described} raised {outcome['raised']!r}") from outcome["raised"]
    return outcome["returned"]


def test_a_parent_chain_that_closes_on_itself_is_walked_once_and_stops():
    """No run produces this, and every ordering helper has to survive one that did.

    Each of these walks the parent chain, so a guard that stops guarding turns a
    run into a hang, which is a failure no assertion about its output can catch.
    """
    state = StreamState(subagent_visibility=attributed(), root_run_id=TOP_LEVEL_RUN)
    state.open_subagent("run-a", name="A", parent_lane="run-c")
    state.open_subagent("run-b", name="B", parent_lane="run-a")
    state.open_subagent("run-c", name="C", parent_lane="run-b")
    state.open_subagent("run-self", name="Self", parent_lane="run-self")
    for lane in ("run-a", "run-b", "run-c", "run-self"):
        state.lane(lane)

    # The walk stops on the first lane it has already passed, so each chain
    # reports the lanes above it once and the lane itself never again.
    assert _within(5, "the ancestor walk", lambda: state.ancestor_lanes("run-a")) == ["run-c", "run-b"]
    assert _within(5, "the ancestor walk", lambda: state.ancestor_lanes("run-self")) == []
    assert _within(5, "the lane depth", lambda: (state.lane_depth("run-a"), state.lane_depth("run-self"))) == (2, 0)
    assert _within(5, "the member terminal order", lambda: state.subagents_deepest_first()) == [
        "run-a",
        "run-b",
        "run-c",
        "run-self",
    ]
    assert _within(5, "the lane sweep", lambda: state.lanes_deepest_first()) == [
        "run-a",
        "run-b",
        "run-c",
        "run-self",
        ROOT_LANE,
    ]


def _docstring(owner: Any, described: str) -> str:
    """The docstring, refusing an absent one.

    Falling back to an empty string makes every claim below trivially absent the
    moment a docstring is deleted, which leaves these assertions pinning the
    absence of prose in a docstring that no longer exists.
    """
    text = owner.__doc__
    assert text, f"{described} carries no docstring, so nothing here can check what it claims"
    return text


# --- What a lane terminal must not take with it -----------------------------


def _live_descendant_tool_when_its_parent_terminates_chunks(session_state: Dict[str, Any]) -> List[Any]:
    """A sub-team reaches its own terminal while its member's tool call is still running."""
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    member = _member_kwargs("scout", "run-scout", parent="run-inner")
    tool = ToolExecution(tool_call_id="tc-scout-approve", tool_name="approve", tool_args={}, result="approved")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamRunStartedEvent(**inner),
        RunStartedEvent(**member),
        ToolCallStartedEvent(tool=tool, **member),
        TeamRunCompletedEvent(content="inner done", **inner),
        SideEffect(lambda: session_state.__setitem__("approved", True)),
        ToolCallCompletedEvent(tool=tool, **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@malformed_mappers
async def test_a_lane_terminal_leaves_a_live_descendants_tool_call_to_its_own_completion(collect_malformed):
    """The tool goes on running, so its call keeps its own end, result and state change.

    Closing that call from the ancestor's terminal would mark it ended, which
    makes the completion that follows read as a repeat and be dropped whole,
    taking the result and the session state the tool wrote with it.
    """
    session_state: Dict[str, Any] = {"approved": False}

    events, error, violation = await collect_malformed(
        _live_descendant_tool_when_its_parent_terminates_chunks(session_state),
        attributed(),
        thread_id=THREAD_ID,
        run_id=TOP_LEVEL_RUN,
        run_state=session_state,
    )

    assert error is None, f"the source stream raised {error!r}"
    assert_stream_contains(events, EventType.TOOL_CALL_RESULT)
    assert in_emitted_order(events, EventType.TOOL_CALL_RESULT, "tool_call_id", "content") == [
        ("tc-scout-approve", '"approved"')
    ]
    # Closed once, by the completion, and still attributed to the member.
    assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id", _lane) == [
        ("tc-scout-approve", "run-scout")
    ]
    assert_stream_contains(events, EventType.STATE_DELTA)
    assert in_emitted_order(events, EventType.STATE_DELTA, "delta") == [
        ([{"op": "replace", "path": "/approved", "value": True}],)
    ]
    _assert_the_child_resolved_after_its_parent(violation)


@needs_lineage_events
@pytest.mark.asyncio
@malformed_mappers
async def test_a_live_descendants_tool_call_that_never_completes_is_still_closed(collect_malformed):
    """Left open for its own completion, and closed by the run end if that never comes.

    The run end closes every open tool call before it terminates the members
    that still hold one, so the end goes out while the lane is still open and the
    member's terminal is the last thing that lane carries.
    """
    session_state: Dict[str, Any] = {"approved": False}
    chunks = [
        chunk
        for chunk in _live_descendant_tool_when_its_parent_terminates_chunks(session_state)
        if not isinstance(chunk, (ToolCallCompletedEvent, SideEffect))
    ]

    events, error, violation = await collect_malformed(
        chunks,
        attributed(),
        thread_id=THREAD_ID,
        run_id=TOP_LEVEL_RUN,
        run_state=session_state,
    )

    assert error is None, f"the source stream raised {error!r}"
    assert_stream_contains(events, EventType.TOOL_CALL_END)
    assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id", _lane) == [
        ("tc-scout-approve", "run-scout")
    ]
    assert not _of_type(events, EventType.TOOL_CALL_RESULT)
    # The member's terminal, read off the two terminal types: a substring match
    # on SUBAGENT takes the announcement instead, which precedes everything the
    # lane carries, and the ordering below then holds whatever the sweep does.
    terminal_at = [index for index, event in enumerate(events) if _lane(event) == "run-scout" and _is_terminal(event)]
    closed_at = [index for index, event in enumerate(events) if event.type == EventType.TOOL_CALL_END]
    assert terminal_at and closed_at and closed_at[0] < terminal_at[0], (closed_at, terminal_at)
    _assert_the_child_resolved_after_its_parent(violation)


def _member_tool_completes_after_its_own_terminal_chunks(session_state: Dict[str, Any]) -> List[Any]:
    """A member's own tool call completes after that member's run already ended."""
    member = _member_kwargs("scout", "run-scout")
    tool = ToolExecution(tool_call_id="tc-scout-approve", tool_name="approve", tool_args={}, result="approved")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        ToolCallStartedEvent(tool=tool, **member),
        RunCompletedEvent(content="scout done", **member),
        SideEffect(lambda: session_state.__setitem__("approved", True)),
        ToolCallCompletedEvent(tool=tool, **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_tool_result_arriving_after_its_members_terminal_still_reaches_the_client(collect):
    """A member's terminal ends no tool call, so the one it left open keeps its own lifecycle.

    Ending that call with the terminal would mark it ended, which makes the
    completion that follows read as a repeat and be dropped whole, taking the
    result and the session state the tool wrote with it.
    """
    session_state: Dict[str, Any] = {"approved": False}

    events = await collect(
        _member_tool_completes_after_its_own_terminal_chunks(session_state),
        attributed(),
        run_state=session_state,
        exempt=[TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL],
    )

    assert_stream_contains(events, EventType.TOOL_CALL_RESULT)
    assert in_emitted_order(events, EventType.TOOL_CALL_RESULT, "tool_call_id", "content", _lane) == [
        ("tc-scout-approve", '"approved"', "run-scout")
    ]
    # Closed once, by the completion, and still the member's.
    assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id", _lane) == [
        ("tc-scout-approve", "run-scout")
    ]
    assert_stream_contains(events, EventType.STATE_DELTA)
    assert in_emitted_order(events, EventType.STATE_DELTA, "delta") == [
        ([{"op": "replace", "path": "/approved", "value": True}],)
    ]
    # The member's own terminal still carries what its run reported.
    assert in_emitted_order(events, EventType.SUBAGENT_FINISHED, "subagent_run_id", "result") == [
        ("run-scout", "scout done")
    ]


def _descendant_still_open_when_its_parent_terminates_chunks(fail: bool) -> List[Any]:
    """A sub-team reaches its own terminal with its member still running."""
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    member = _member_kwargs("scout", "run-scout", parent="run-inner")
    parent_terminal = (
        TeamRunErrorEvent(content="inner exploded", error_type="RuntimeError", **inner)
        if fail
        else TeamRunCompletedEvent(content="inner done", **inner)
    )

    chunks: List[Any] = [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamRunStartedEvent(**inner),
        RunStartedEvent(**member),
        _agent_said("scouting", **member),
        parent_terminal,
    ]
    if not fail:
        # The member goes on working and reports its own result afterwards.
        chunks.append(RunCompletedEvent(content="scout done", **member))
    chunks.append(TeamRunCompletedEvent(**_TOP_LEVEL))
    return chunks


@needs_lineage_events
@pytest.mark.asyncio
@malformed_mappers
async def test_a_member_still_running_reports_its_own_result_when_the_member_above_it_finishes(collect_malformed):
    """A parent's terminal terminates the parent, so the child still delivers what it produced.

    Terminating the child here instead would send a terminal with no result,
    after which the child's own completion is read as a second terminal and
    dropped, so the member's real content reaches nobody.
    """
    events, error, violation = await collect_malformed(
        _descendant_still_open_when_its_parent_terminates_chunks(fail=False),
        attributed(),
        thread_id=THREAD_ID,
        run_id=TOP_LEVEL_RUN,
        exempt=[TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL],
    )

    assert error is None, f"the source stream raised {error!r}"
    assert_stream_contains(events, EventType.SUBAGENT_FINISHED, 2)
    assert in_emitted_order(events, EventType.SUBAGENT_FINISHED, "subagent_run_id", "result") == [
        ("run-inner", "inner done"),
        ("run-scout", "scout done"),
    ]
    # The member's own words still reached the client, in its own lane.
    assert joined_text_in_emitted_order(events) == [("run-scout", "scouting")]
    _assert_the_child_resolved_after_its_parent(violation)


@needs_lineage_events
@pytest.mark.asyncio
@malformed_mappers
async def test_a_member_that_never_failed_carries_no_error_from_the_member_above_it(collect_malformed, caplog):
    """The failure belongs to the run that reported it, and to no lane below it."""
    with captured_agno_logs(caplog, "ERROR"):
        events, error, violation = await collect_malformed(
            _descendant_still_open_when_its_parent_terminates_chunks(fail=True),
            attributed(),
            thread_id=THREAD_ID,
            run_id=TOP_LEVEL_RUN,
            exempt=[TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL],
        )

    assert error is None, f"the source stream raised {error!r}"
    assert_stream_contains(events, EventType.SUBAGENT_ERROR)
    assert in_emitted_order(events, EventType.SUBAGENT_ERROR, "subagent_run_id", "message", "code") == [
        ("run-inner", "inner exploded", "RuntimeError")
    ]
    # The member never failed, so the run end finishes it, without a code and
    # without the message of the failure above it.
    assert in_emitted_order(events, EventType.SUBAGENT_FINISHED, "subagent_run_id", "result") == [("run-scout", None)]
    assert [record.message for record in caplog.records if "run-scout" in record.message] == []
    _assert_the_child_resolved_after_its_parent(violation)


def _pause_repeating_a_members_open_tool_call_chunks() -> List[Any]:
    """The paused requirement repeats a member tool call that is still open."""
    member = _member_kwargs("scout", "run-scout")
    streaming = ToolExecution(tool_call_id="tc-member-confirm", tool_name="send_email", tool_args={"to": "ops"})
    repeated = ToolExecution(
        tool_call_id="tc-member-confirm",
        tool_name="send_email",
        tool_args={"to": "ops"},
        requires_confirmation=True,
    )
    requirement = _requirement(repeated, "scout", "run-scout", "Scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        ToolCallStartedEvent(tool=streaming, **member),
        TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_pause_does_not_open_a_second_start_for_a_call_the_client_already_has(collect):
    """A call still open has had its start: prompting it again opens one span twice."""
    events = await collect(_pause_repeating_a_members_open_tool_call_chunks(), attributed())

    assert in_emitted_order(events, EventType.TOOL_CALL_START, "tool_call_id", _lane) == [
        ("tc-member-confirm", "run-scout")
    ]
    assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id", _lane) == [
        ("tc-member-confirm", "run-scout")
    ]

    # Nothing survived the prompt, and every call it would have carried is
    # already on the wire, so the prompt says nothing rather than adding an
    # assistant message with neither words nor a call under it. Every message
    # here is one a tool call is parented to.
    carrying = {e.parent_message_id for e in _of_type(events, EventType.TOOL_CALL_START)}  # type: ignore[attr-defined]
    assert [
        (_lane(e), e.message_id in carrying)  # type: ignore[attr-defined]
        for e in _of_type(events, EventType.TEXT_MESSAGE_START)
    ] == [("run-scout", True)]
    assert not _of_type(events, EventType.TEXT_MESSAGE_CONTENT)


# --- A member name the interface cannot read --------------------------------


class _UnreadableName:
    """A name whose stringification raises, as a proxy object's can."""

    def __str__(self) -> str:
        raise RuntimeError("name exploded")


def _member_with_an_unreadable_name_chunks() -> List[Any]:
    member = {"agent_name": _UnreadableName(), "run_id": "run-scout", "parent_run_id": TOP_LEVEL_RUN}

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        _agent_said("scouting", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_member_name_the_interface_cannot_read_does_not_end_the_run(collect, caplog):
    with captured_agno_logs(caplog, "WARNING"):
        events = await collect(_member_with_an_unreadable_name_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    # Nameable or not, the lane is announced, under the only name left: its run id.
    assert [(e.subagent_run_id, e.name) for e in _announcements(events)] == [("run-scout", "run-scout")]  # type: ignore[attr-defined]
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)
    # The client is shown a run id where a name belongs, so the raise that cost
    # it the name has to reach the operator. Recorded by type rather than by the
    # failure's own text: rendering that text runs the same name the read did,
    # which is the read raising a second time from inside its own record.
    assert "AG-UI could not read a subagent name from agent_name: RuntimeError" in [
        record.getMessage() for record in caplog.records
    ], "the member name the interface could not read left no trace at all"


@pytest.mark.parametrize(
    "value",
    [None, "", 0, 0.0, False, [], {}, ()],
    ids=["none", "empty_text", "zero", "zero_float", "false", "empty_list", "empty_mapping", "empty_tuple"],
)
def test_a_falsy_label_is_read_as_no_label_at_all(value):
    """Every falsy value is absent, not a label, which is what each caller falls back on.

    Stated over the falsy values a chunk can carry rather than over None alone,
    because the guard tests truthiness: a caller reading ``""`` or ``"0"`` off
    this would put it on the wire as a member's name or its id, and the next
    fallback would never be tried.
    """
    assert handlers._readable(value, "a label under test") is None


def test_a_label_that_is_present_is_read_as_its_text():
    """Otherwise the case above passes on a guard that discards everything."""
    assert handlers._readable("Scout", "a label under test") == "Scout"
    assert handlers._readable(7, "a label under test") == "7"


# --- The member id the framework delegates by -------------------------------


def _parallel_delegations_to_named_members_chunks() -> List[Any]:
    """Two delegations open at once, to members named but never given ids."""
    scout = {"agent_name": "Scout", "run_id": "run-scout", "parent_run_id": TOP_LEVEL_RUN}

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=_delegation("tc-scout", "scout", "scout the north")),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=_delegation("tc-ranger", "ranger", "range the south")),
        _agent_said("scouting", **scout),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_named_member_without_an_id_is_still_linked_to_its_delegation(collect):
    """The delegation argument carries the framework's derived member id, not the run's.

    A member given no id of its own is delegated to by the url-safe form of its
    name. Initializing a Team then assigns that same derived id to the member,
    so a locally built Team's chunks carry it and this branch never runs for
    one. It is there for the chunks that assignment does not stand behind, a
    remote entity's among them, which are rebuilt from what its stream sent:
    reading the run's own agent id alone would leave a member arriving with a
    name and no id unmatched, and a parallel delegation then has no single
    candidate to fall back on.
    """
    from agno.utils.team import get_member_id

    named = Agent(name="Scout", telemetry=False)
    assert named.id is None, "this fixture is about a member given no id of its own"
    assert get_member_id(named) == "scout", "the framework no longer derives a member id from the name"
    Team(name="Owner", members=[named], telemetry=False)._initialize_member(named)
    assert named.id == "scout", "a Team no longer assigns its members the id it delegates to them by"

    events = await collect(_parallel_delegations_to_named_members_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    announcement = _announcements(events)[0]
    assert (
        announcement.subagent_run_id,  # type: ignore[attr-defined]
        announcement.name,  # type: ignore[attr-defined]
        announcement.description,  # type: ignore[attr-defined]
        announcement.parent_tool_call_id,  # type: ignore[attr-defined]
    ) == ("run-scout", "Scout", "scout the north", "tc-scout")
    # The delegation's own parent message, resolved against the messages this
    # stream really opened: read back as None on both sides, that field compares
    # nothing, and an id no start ever carried is one a client cannot place.
    assert announcement.parent_message_id in _lane_of_message_id(events), (  # type: ignore[attr-defined]
        "the delegation's own parent message names no message this stream opened"
    )


def _two_delegations_naming_one_member_chunks() -> List[Any]:
    """Two open delegations name the same member, so neither can be shown to have spawned it."""
    member = _member_kwargs("scout", "run-scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=_delegation("tc-first", "scout", "scout the north")),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=_delegation("tc-second", "scout", "scout the south")),
        _agent_said("scouting", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_two_open_delegations_naming_one_member_report_no_link_rather_than_a_guess(collect):
    events = await collect(_two_delegations_naming_one_member_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    assert [
        (e.subagent_run_id, e.description, e.parent_tool_call_id, e.parent_message_id)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-scout", None, None, None)]


def _broadcast_delegation(tool_call_id: str, task: str) -> ToolExecution:
    """One of the delegation tools that names no member, because it targets them all."""
    return ToolExecution(
        tool_call_id=tool_call_id,
        tool_name="delegate_task_to_members",
        tool_args={"task": task},
    )


def _member_spawned_by_a_broadcast_chunks() -> List[Any]:
    """The only open delegation is a broadcast, so nothing on it names the member."""
    member = _member_kwargs("scout", "run-scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=_broadcast_delegation("tc-broadcast", "everyone work")),
        RunStartedEvent(**member),
        RunCompletedEvent(content="scout done", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_broadcast_delegation_names_no_member_so_no_link_is_reported(collect):
    """A lone open delegation is not evidence that it spawned this member.

    Returning it because it is the only candidate hands an unrelated lane, such
    as the inner run of a context provider, another member's parent call, task
    text and parent message.
    """
    events = await collect(_member_spawned_by_a_broadcast_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    assert [
        (e.subagent_run_id, e.parent_tool_call_id, e.description, e.parent_message_id)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-scout", None, None, None)]


def _paused_member_spawned_by_a_broadcast_chunks() -> List[Any]:
    """A member pauses, and the only open delegation is a broadcast that names nobody."""
    tool = ToolExecution(
        tool_call_id="tc-scout-confirm", tool_name="send_email", tool_args={"to": "ops"}, requires_confirmation=True
    )
    requirement = _requirement(tool, "scout", "run-scout", "Scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=_broadcast_delegation("tc-broadcast", "everyone work")),
        TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_member_a_broadcast_spawned_reports_no_link(collect):
    """The paused path resolves the parent the same way, so it borrows nothing either."""
    events = await collect(_paused_member_spawned_by_a_broadcast_chunks(), attributed())

    assert_stream_contains(events, EventType.TOOL_CALL_START, 2)
    assert [
        (e.subagent_run_id, e.parent_subagent_run_id, e.parent_tool_call_id, e.description, e.parent_message_id)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-scout", None, None, None, None)]


def _paused_grandchild_a_broadcast_delegated_chunks() -> List[Any]:
    """A sub-team broadcasts to its members, and one of them pauses."""
    inner = _team_kwargs("inner-team", "Inner Team", "run-inner", parent=TOP_LEVEL_RUN)
    outer_delegation = _delegation("tc-delegate-inner", "inner-team", "run the inner team")
    member_tool = ToolExecution(
        tool_call_id="tc-scout-confirm", tool_name="send_email", tool_args={"to": "ops"}, requires_confirmation=True
    )
    requirement = _requirement(member_tool, "scout", "run-scout", "Scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=outer_delegation),
        TeamRunStartedEvent(**inner),
        TeamToolCallStartedEvent(tool=_broadcast_delegation("tc-inner-broadcast", "everyone scout"), **inner),
        TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_grandchild_whose_parent_cannot_be_identified_reports_no_parent(collect):
    """No parent beats the leader: the sub-team's task and the leader's message are not this member's.

    Reaching past the sub-team for the leader's own open delegation also flattens
    the tree, which puts the grandchild at the same depth as the member that
    really delegated to it and reverses the order their terminals go out in.
    """
    events = await collect(_paused_grandchild_a_broadcast_delegated_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED, 2)
    parent_of_tool_call = {
        e.tool_call_id: e.parent_message_id  # type: ignore[attr-defined]
        for e in _of_type(events, EventType.TOOL_CALL_START)
    }
    # The sub-team's own link names a message this stream really opened: read
    # back as None on both sides, that field compares nothing.
    assert parent_of_tool_call["tc-delegate-inner"] in _lane_of_message_id(events), parent_of_tool_call
    assert [
        (e.subagent_run_id, e.parent_subagent_run_id, e.parent_tool_call_id, e.description, e.parent_message_id)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [
        ("run-inner", None, "tc-delegate-inner", "run the inner team", parent_of_tool_call["tc-delegate-inner"]),
        ("run-scout", None, None, None, None),
    ]


def _paused_member_named_by_two_delegations_chunks() -> List[Any]:
    """One lane holds two open delegations naming the member that then pauses."""
    tool = ToolExecution(
        tool_call_id="tc-scout-confirm", tool_name="send_email", tool_args={"to": "ops"}, requires_confirmation=True
    )
    requirement = _requirement(tool, "scout", "run-scout", "Scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=_delegation("tc-first", "scout", "scout the north")),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=_delegation("tc-second", "scout", "scout the south")),
        TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL),
    ]


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_paused_member_named_by_two_delegations_reports_no_link(collect):
    """The paused path resolves the parent the same way, so it omits the same links."""
    events = await collect(_paused_member_named_by_two_delegations_chunks(), attributed())

    assert_stream_contains(events, EventType.SUBAGENT_STARTED)
    assert [
        (e.subagent_run_id, e.description, e.parent_subagent_run_id, e.parent_tool_call_id)  # type: ignore[attr-defined]
        for e in _announcements(events)
    ] == [("run-scout", None, None, None)]


# --- Failures that have to reach somebody -----------------------------------


def _member_tool_call_fails_chunks() -> List[Any]:
    member = _member_kwargs("scout", "run-scout")
    tool = ToolExecution(tool_call_id="tc-member-search", tool_name="search_docs", tool_args={"query": "agno"})

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        ToolCallStartedEvent(tool=tool, **member),
        ToolCallErrorEvent(tool=tool, error="tool exploded", **member),
        RunCompletedEvent(content="scout done", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


@pytest.mark.asyncio
@chunk_mappers
async def test_hidden_records_a_member_tool_call_failure_it_withholds(collect, caplog):
    """Hidden withholds what identifies a member, never the fact that something failed."""
    with captured_agno_logs(caplog, "WARNING"):
        events = await collect(_member_tool_call_fails_chunks(), SUBAGENT_VISIBILITY_HIDDEN)

    assert not [e for e in events if _lane(e) is not None]
    assert not [e for e in events if "TOOL_CALL" in str(e.type)]
    assert [r.message for r in caplog.records if "tool exploded" in r.message], (
        "a member's tool call failed and neither the client nor the log was told"
    )


def _plain_member_failure_chunks() -> List[Any]:
    """A member failure carrying nothing beyond its message and type."""
    member = _member_kwargs("scout", "run-scout")

    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**member),
        RunErrorEvent(content="member exploded", error_type="RuntimeError", **member),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


async def _assert_the_failure_line_names_only_what_it_has(collect, caplog, visibility: Optional[str]) -> None:
    with captured_agno_logs(caplog, "ERROR"):
        await collect(_plain_member_failure_chunks(), visibility)

    failures = [r.message for r in caplog.records if "member exploded" in r.message]
    assert len(failures) == 1, f"one failure was recorded {len(failures)} times: {failures}"
    assert "None" not in failures[0], f"the failure line reports fields it does not have: {failures[0]}"


@needs_lineage_events
@pytest.mark.asyncio
@chunk_mappers
async def test_a_plain_member_failure_on_the_wire_is_recorded_without_empty_detail_fields(collect, caplog):
    await _assert_the_failure_line_names_only_what_it_has(collect, caplog, attributed())


@pytest.mark.asyncio
@chunk_mappers
async def test_a_plain_member_failure_hidden_from_the_wire_is_recorded_without_empty_detail_fields(collect, caplog):
    await _assert_the_failure_line_names_only_what_it_has(collect, caplog, SUBAGENT_VISIBILITY_HIDDEN)


@needs_lineage_events
@pytest.mark.asyncio
@pytest.mark.parametrize(
    # Built per case rather than at collection time, so the two mappers cannot
    # hand each other a pending call one of them has already been through.
    "unusable_factory,named",
    [(_nameless_tool, "tc-nameless"), (_idless_tool, "send_invoice")],
    ids=["no_name", "no_id"],
)
@chunk_mappers
async def test_a_paused_tool_the_client_cannot_be_shown_is_recorded_even_when_another_survives(
    collect, caplog, unusable_factory, named
):
    """A dropped pending call hangs the resume, so a partial drop cannot be silent."""
    with captured_agno_logs(caplog, "WARNING"):
        events = await collect(_paused_member_carrying_one_unusable_tool_chunks(unusable_factory()), attributed())

    assert_stream_contains(events, EventType.TOOL_CALL_START)
    assert [r.message for r in caplog.records if named in r.message], (
        f"the dropped pending call {named} left no trace in the log"
    )


# --- The default pause prompt -----------------------------------------------


def _paused_on_nothing_renderable_chunks() -> List[Any]:
    """A run pauses on a single tool the client cannot be shown: it carries no name."""
    nameless = _nameless_tool()
    paused = AgentRunPausedEvent(agent_id="solo", agent_name="Solo", run_id=TOP_LEVEL_RUN, tools=[nameless])
    paused.content = "Confirm before I send this."

    return [RunStartedEvent(agent_id="solo", agent_name="Solo", run_id=TOP_LEVEL_RUN), paused]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    # Resolved inside the test rather than at collection: naming the attributed
    # setting is what skips on a release that cannot serve it. It belongs here
    # because it is the setting this behavior was reworked for, and because the
    # prompt is now split one message per subagent, so a run with no subagent on
    # it has to come out as the single unattributed message the others produce.
    "setting",
    [lambda: None, lambda: SUBAGENT_VISIBILITY_INLINE, attributed, lambda: SUBAGENT_VISIBILITY_HIDDEN],
    ids=["default", "inline", "attributed", "hidden"],
)
@chunk_mappers
async def test_a_pause_carrying_only_unrenderable_tools_still_says_so(collect, setting):
    """The prompt message goes out whenever the terminal carries paused tools at all.

    Before member attribution existed the renderability of a pending call
    decided only whether that call was prompted, never whether the pause was
    announced, so a run that paused on nothing renderable still told the client
    why it stopped. It is the listing that decides: a terminal that listed no
    pending call at all carries no prompt and no content with it, which is that
    same stream and is pinned separately.
    """
    events = await collect(_paused_on_nothing_renderable_chunks(), setting())

    assert_stream_contains(events, EventType.TEXT_MESSAGE_CONTENT)
    # One message, unattributed, under every setting: no subagent is involved,
    # so the per-subagent split has nothing to split and nothing to announce.
    assert joined_text_in_emitted_order(events) == [(None, "Confirm before I send this.")]
    assert not [e for e in events if "SUBAGENT" in str(e.type)]
    assert not _of_type(events, EventType.TOOL_CALL_START)
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)


# --- The interface's own shape ----------------------------------------------


def _stream_state_attributes_read_outside(module_name: str) -> Set[str]:
    """Every attribute the rest of the interface reads off a ``StreamState``.

    Read off the syntax rather than by searching the source text for a bare
    ``.name``: the per-lane ``Lane`` object declares fields under the same names
    as the properties that front them, so a text search counts
    ``lane.text_message_id`` as a read of the property and goes on reporting one
    after every ``state.text_message_id`` is gone.
    """
    package = Path(handlers.__file__).parent
    read: Set[str] = set()
    for path in sorted(package.glob("*.py")):
        if path.name == module_name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        holders = {
            argument.arg
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for argument in node.args.args
            if isinstance(argument.annotation, ast.Name) and argument.annotation.id == StreamState.__name__
        }
        holders.update(
            target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == StreamState.__name__
            for target in node.targets
            if isinstance(target, ast.Name)
        )
        read.update(
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
            and isinstance(node.value, ast.Name)
            and node.value.id in holders
        )
    return read


def test_every_stream_state_property_is_read_somewhere_in_the_interface():
    """A property nothing reads is a second home for state with one truth.

    Each of these reads whichever lane is current, so one left unread outlives
    the reader that justified it and answers for the wrong lane if anything
    picks it up again.
    """
    # A walk that found no StreamState at all would report every property as
    # unread rather than pass, so what it did find is stated first.
    read = _enumerated_by_the_interface(
        _stream_state_attributes_read_outside("state.py"),
        "lane",
        described="the StreamState attributes the rest of the interface reads",
    )
    unread = sorted(
        name for name, member in vars(StreamState).items() if isinstance(member, property) if name not in read
    )
    assert not unread, f"nothing outside the state module reads these StreamState properties: {unread}"


def test_the_terminal_check_requires_the_state_it_classifies_against():
    """Its default is unreachable, and would read a member's terminal as the run's."""
    state_parameter = inspect.signature(handlers.is_completion_event).parameters["state"]
    assert state_parameter.default is inspect.Parameter.empty


def test_the_hidden_visibility_says_what_still_reaches_the_client():
    """Two things do, so neither the option nor the branch may claim it withholds all."""
    from agno.os.interfaces.agui import AGUI

    constructor_doc = _docstring(AGUI.__init__, "the AGUI constructor")
    for claim in ("session state", "pending tool call"):
        assert claim in constructor_doc, f"the documented hidden option does not mention the {claim} it delivers"
        assert claim in inspect.getsource(handlers.process_event), (
            f"the hidden branch does not mention the {claim} it delivers"
        )


def test_the_announcement_says_it_never_names_a_parent_the_stream_has_not_reached():
    """A refusal a reader has to be told about: the parent link is dropped, not deferred."""
    said = _docstring(handlers._announce_subagent, "the member announcement")
    assert "already announced" in said
    assert "forward reference" in said
