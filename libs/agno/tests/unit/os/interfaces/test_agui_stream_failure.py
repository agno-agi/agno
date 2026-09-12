"""AG-UI mapping of an Agno stream that ends badly, or ends somewhere unexpected.

A run's event stream can raise mid-flight: a model call dies, a tool raises, the
connection to a remote entity drops. Both mappers open spans as events flow, so
a failure that escapes without closing them leaves the client holding a text
bubble and tool cards that spin forever and, under ``attributed`` visibility,
member lanes that never resolve.

A stream can also stop on a subagent's own terminal, with the top-level entity
reporting none of its own. That chunk is then the only account of how the run
ended, so which chunk the run terminal is built from is pinned here too, under
every visibility: a run that died inside a member must not reach the client as a
success.

Every test here runs against the sync mapper and the async mapper, so the two
cannot drift apart.
"""

import inspect
import json
from typing import Any, AsyncGenerator, Iterable, List, Optional

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import BaseEvent, EventType

from agno.models.response import ToolExecution
from agno.os.interfaces.agui import handlers
from agno.os.interfaces.agui import stream as stream_module
from agno.os.interfaces.agui.state import SUBAGENT_VISIBILITY_HIDDEN, SUBAGENT_VISIBILITY_INLINE, StreamState
from agno.os.interfaces.agui.stream import (
    async_stream_agno_response_as_agui_events,
    stream_agno_response_as_agui_events,
)
from agno.run.agent import (
    RunCancelledEvent,
    RunCompletedEvent,
    RunErrorEvent,
    RunEvent,
    RunStartedEvent,
    ToolCallStartedEvent,
)
from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import RunStartedEvent as TeamRunStartedEvent
from agno.run.team import ToolCallStartedEvent as TeamToolCallStartedEvent

from .agui_stream_invariants import (
    ABANDONED_MID_STREAM,
    ABANDONED_WITH_A_MEMBER_STILL_OPEN,
    TOP_LEVEL_RUN,
    Collected,
    agent_said,
    assert_stream_contains,
    assert_well_formed_stream,
    async_source,
    attributed,
    captured_agno_logs,
    collect_async,
    collect_sync,
    event_type_named,
    field_of,
    in_emitted_order,
    lane_of,
    member_chunk_kwargs,
    of_type,
    short_type,
    sync_source,
)

THREAD_ID = "failure-session"


# --- Streams ----------------------------------------------------------------


class _Boom(RuntimeError):
    """The failure a source stream raises. Distinct so a test can match it exactly."""


# The member's lineage fields and the content chunk come from the shared module,
# which the attribution suite builds the same chunks from.
_member_kwargs = member_chunk_kwargs
_content = agent_said


def _open_text_message_chunks(message: str) -> List[Any]:
    """A run that opened a text message and then died."""
    return [
        RunStartedEvent(run_id=TOP_LEVEL_RUN),
        _content("half a sen", run_id=TOP_LEVEL_RUN),
        _Boom(message),
    ]


def _open_tool_call_chunks(message: str) -> List[Any]:
    """A run that started a tool call and then died before its result."""
    return [
        RunStartedEvent(run_id=TOP_LEVEL_RUN),
        ToolCallStartedEvent(
            run_id=TOP_LEVEL_RUN,
            tool=ToolExecution(tool_call_id="tc-search", tool_name="search_docs", tool_args={"query": "agno"}),
        ),
        _Boom(message),
    ]


def _delegation() -> ToolExecution:
    return ToolExecution(
        tool_call_id="tc-delegate-scout",
        tool_name="delegate_task_to_member",
        tool_args={"member_id": "scout", "task": "scout the topic"},
    )


def _open_member_lane_chunks(message: str) -> List[Any]:
    """A team whose member was mid-sentence inside a delegation when the stream died."""
    member = _member_kwargs("scout", "run-scout")
    return [
        TeamRunStartedEvent(team_id="research-team", team_name="Research Team", run_id=TOP_LEVEL_RUN),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=_delegation()),
        RunStartedEvent(**member),
        _content("scouting so", **member),
        _Boom(message),
    ]


_MEMBER = _member_kwargs("scout", "run-scout")


def _ends_on_the_members_terminal_chunks(*terminals: Any) -> List[Any]:
    """A team that reported no terminal of its own, so a member's is the last thing on it.

    The delegation the member ran inside is left open, so the run terminal is
    also what has to close the leader's own call.
    """
    return [
        TeamRunStartedEvent(team_id="research-team", team_name="Research Team", run_id=TOP_LEVEL_RUN),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=_delegation()),
        RunStartedEvent(**_MEMBER),
        _content("half a sen", **_MEMBER),
        *terminals,
    ]


def _member_failed() -> Any:
    return RunErrorEvent(content="member exploded", error_type="RuntimeError", **_MEMBER)


def _member_finished() -> Any:
    return RunCompletedEvent(content="scout done", **_MEMBER)


def _member_cancelled() -> Any:
    return RunCancelledEvent(reason="the operator stopped it", **_MEMBER)


def _pending_member_tool() -> ToolExecution:
    return ToolExecution(
        tool_call_id="tc-member-confirm",
        tool_name="send_email",
        tool_args={"to": "ops"},
        requires_confirmation=True,
    )


def _member_paused() -> Any:
    return AgentRunPausedEvent(tools=[_pending_member_tool()], **_MEMBER)


def _member_paused_saying_something() -> Any:
    """The same pause, with words of the member's own on it."""
    return AgentRunPausedEvent(tools=[_pending_member_tool()], content="I need approval to email ops.", **_MEMBER)


def _team_finished() -> Any:
    return TeamRunCompletedEvent(team_id="research-team", team_name="Research Team", run_id=TOP_LEVEL_RUN)


def _team_failed() -> Any:
    return TeamRunErrorEvent(
        content="the team blew up", error_type="RuntimeError", team_id="research-team", run_id=TOP_LEVEL_RUN
    )


def _visibilities() -> List[Any]:
    """The settings a stream is driven under, the attributed one resolved lazily.

    Named through the shared door, so an install that cannot serve member
    attribution skips those cases instead of failing them, and resolved inside
    the test rather than at collection time.
    """
    return [
        pytest.param(lambda: None, id="default"),
        pytest.param(lambda: SUBAGENT_VISIBILITY_INLINE, id="inline"),
        pytest.param(attributed, id="attributed"),
        pytest.param(lambda: SUBAGENT_VISIBILITY_HIDDEN, id="hidden"),
    ]


visibilities = pytest.mark.parametrize("visibility", _visibilities())


# --- Collectors -------------------------------------------------------------

# Both collectors run the shared stream-invariant helper before handing the
# events back, so every test in this module inherits the whole invariant set.


async def _collect_sync(chunks: Iterable[Any], visibility: Optional[str] = None) -> Collected:
    return await collect_sync(chunks, visibility, thread_id=THREAD_ID, run_id=TOP_LEVEL_RUN)


async def _collect_async(chunks: Iterable[Any], visibility: Optional[str] = None) -> Collected:
    return await collect_async(chunks, visibility, thread_id=THREAD_ID, run_id=TOP_LEVEL_RUN)


mappers = pytest.mark.parametrize("collect", [_collect_sync, _collect_async], ids=["sync", "async"])


# --- Assertions helpers -----------------------------------------------------

_lane = lane_of
_of_type = of_type


def _only(events: List[BaseEvent], described: str = "event") -> BaseEvent:
    assert len(events) == 1, f"expected exactly one {described}, got {len(events)}"
    return events[0]


def _one(events: List[BaseEvent], event_type: EventType) -> BaseEvent:
    return _only(_of_type(events, event_type), str(event_type))


def _terminals(events: List[BaseEvent]) -> List[str]:
    return [str(e.type) for e in events if e.type in (EventType.RUN_FINISHED, EventType.RUN_ERROR)]


# The field each closing event names its span by. Read through this rather than
# through the first of two attributes that happens to be set: that reads a
# renamed message_id as an absent one and falls through to the tool call id,
# which is the comparison passing while nothing is compared.
_SPAN_ID_FIELD = {
    EventType.TEXT_MESSAGE_END: "message_id",
    EventType.TOOL_CALL_END: "tool_call_id",
}


def _span_id(event: BaseEvent) -> Optional[str]:
    """The id of the span an event closes, or None for an event that closes none."""
    field = _SPAN_ID_FIELD.get(event.type)
    return None if field is None else field_of(event, field)


def _terminals_with_reason(events: List[BaseEvent]) -> List[tuple]:
    """(terminal, message, code) per run terminal, in order.

    One list for both terminals, so a run reported as finished where the client
    had to be told it failed is a diff here rather than an absence somewhere
    else. RUN_FINISHED declares neither field, so only the error terminal's are
    read, and those are read as declared fields.
    """
    rows: List[tuple] = []
    for event in events:
        if event.type == EventType.RUN_ERROR:
            rows.append((short_type(event), field_of(event, "message"), field_of(event, "code")))
        elif event.type == EventType.RUN_FINISHED:
            rows.append((short_type(event), None, None))
    return rows


# --- The failure path -------------------------------------------------------


@pytest.mark.asyncio
@mappers
async def test_an_open_text_message_is_ended_when_the_source_stream_fails(collect):
    events, error = await collect(_open_text_message_chunks("model connection dropped"))

    assert_stream_contains(events, EventType.TEXT_MESSAGE_END)
    started = _one(events, EventType.TEXT_MESSAGE_START)
    ended = _one(events, EventType.TEXT_MESSAGE_END)
    assert ended.message_id == started.message_id
    # The close is the last thing on the wire, after the partial content.
    assert [str(e.type) for e in events[-2:]] == [
        str(EventType.TEXT_MESSAGE_CONTENT),
        str(EventType.TEXT_MESSAGE_END),
    ]
    assert isinstance(error, _Boom) and str(error) == "model connection dropped"


@pytest.mark.asyncio
@mappers
async def test_an_open_tool_call_is_ended_when_the_source_stream_fails(collect):
    events, error = await collect(_open_tool_call_chunks("tool executor died"))

    assert_stream_contains(events, EventType.TOOL_CALL_END)
    # Ordered, so a call started or ended twice is a diff rather than a silence.
    assert in_emitted_order(events, EventType.TOOL_CALL_START, "tool_call_id") == [("tc-search",)]
    assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id") == [("tc-search",)]
    assert str(events[-1].type) == str(EventType.TOOL_CALL_END)
    assert isinstance(error, _Boom) and str(error) == "tool executor died"


# What a lane still open is told the run failed of. A failure carrying no text
# of its own is described by the type that raised, which is the only thing left
# to name it by: an empty message would leave the client a lane that errored for
# no stated reason.
_FAILURE_DESCRIPTIONS = [
    pytest.param("member exploded mid-stream", "member exploded mid-stream", id="with_a_message"),
    pytest.param("", "_Boom", id="with_no_message"),
]


@pytest.mark.asyncio
@mappers
@pytest.mark.parametrize("raised,described", _FAILURE_DESCRIPTIONS)
async def test_a_member_lane_still_open_is_errored_when_the_source_stream_fails(collect, raised, described):
    subagent_error = event_type_named("SUBAGENT_ERROR")
    events, error = await collect(_open_member_lane_chunks(raised), attributed())

    assert_stream_contains(events, subagent_error)
    # The other open message is the leader's empty parent for the delegation call.
    member_message = _only([e for e in _of_type(events, EventType.TEXT_MESSAGE_START) if _lane(e) == "run-scout"])

    # The member's span closes, then the leader's delegation call, and the
    # member's lane errors last: a terminal lands outside every span the stream
    # had open, never inside the delegation call that spawned it.
    assert [(str(e.type), _lane(e), _span_id(e)) for e in events[-3:]] == [
        (str(EventType.TEXT_MESSAGE_END), "run-scout", member_message.message_id),
        (str(EventType.TOOL_CALL_END), None, "tc-delegate-scout"),
        (str(subagent_error), "run-scout", None),
    ]

    assert in_emitted_order(events, subagent_error, "subagent_run_id", "message", "code") == [
        ("run-scout", described, None)
    ]
    # A lane that errored is not also reported as finished.
    assert not _of_type(events, event_type_named("SUBAGENT_FINISHED"))
    assert isinstance(error, _Boom) and str(error) == raised


# Each stream with the visibility its own shape needs. Driving the two that
# carry no member under ``attributed`` skipped them wholesale on a protocol
# release without the lineage events, which the packaged extra still permits,
# and neither has anything to do with member lanes.
_DEAD_STREAMS = [
    pytest.param(_open_text_message_chunks, lambda: None, id="text"),
    pytest.param(_open_tool_call_chunks, lambda: SUBAGENT_VISIBILITY_INLINE, id="tool_call"),
    pytest.param(_open_member_lane_chunks, attributed, id="member_lane"),
]


@pytest.mark.asyncio
@mappers
@pytest.mark.parametrize("chunk_factory,visibility", _DEAD_STREAMS)
async def test_the_failure_path_emits_no_terminal_of_its_own(collect, chunk_factory, visibility):
    # Built per case: a chunk list assembled at collection time would share one
    # exception instance, and its traceback, across every case that uses it.
    events, error = await collect(chunk_factory("boom"), visibility())

    # The caller writes the run terminal, and nothing may follow one on the wire.
    assert _terminals(events) == []
    assert isinstance(error, _Boom)


@pytest.mark.asyncio
@mappers
async def test_the_failure_propagates_unchanged(collect):
    boom = _Boom("keep me")
    events, error = await collect([RunStartedEvent(run_id=TOP_LEVEL_RUN), boom])

    assert error is boom
    assert _terminals(events) == []


@pytest.mark.asyncio
@mappers
async def test_a_stream_that_does_not_fail_still_gets_exactly_one_terminal(collect):
    events, error = await collect(
        [RunStartedEvent(run_id=TOP_LEVEL_RUN), _content("all done", run_id=TOP_LEVEL_RUN)],
        SUBAGENT_VISIBILITY_INLINE,
    )

    assert error is None
    assert_stream_contains(events, EventType.RUN_FINISHED)
    assert _terminals(events) == [str(EventType.RUN_FINISHED)]
    assert str(events[-1].type) == str(EventType.RUN_FINISHED)
    # The synthesized completion closes the open message, exactly as before.
    assert _one(events, EventType.TEXT_MESSAGE_END).message_id == _one(events, EventType.TEXT_MESSAGE_START).message_id


# --- A stream that stops on a member's own terminal -------------------------

# A source stream can end on a subagent's terminal without the top-level entity
# reporting one of its own. That terminal is then the only account of how the run
# ended, and every visibility has to read it the same way: the default already
# does, because it knows no member lanes.

_TERMINAL_CASES = [
    pytest.param(_member_failed, [("RUN_ERROR", "member exploded", "RuntimeError")], id="error"),
    pytest.param(_member_finished, [("RUN_FINISHED", None, None)], id="completed"),
]

_MEMBER_TERMINALS = [pytest.param(_member_failed, id="error"), pytest.param(_member_finished, id="completed")]


@pytest.mark.asyncio
@mappers
@visibilities
@pytest.mark.parametrize("terminal,expected", _TERMINAL_CASES)
async def test_a_stream_that_ends_on_a_members_terminal_reports_what_that_terminal_said(
    collect, visibility, terminal, expected
):
    events, error = await collect(_ends_on_the_members_terminal_chunks(terminal()), visibility())

    assert error is None, f"the source stream raised {error!r}"
    assert _terminals_with_reason(events) == expected
    # The terminal is the last thing on the wire, as it is on any other stream.
    assert short_type(events[-1]) == expected[0][0]


@pytest.mark.asyncio
@mappers
@visibilities
@pytest.mark.parametrize("terminal", _MEMBER_TERMINALS)
async def test_the_top_level_entitys_own_terminal_supersedes_a_members(collect, visibility, terminal):
    """The member ended, the run went on and finished, so the run finished."""
    events, error = await collect(_ends_on_the_members_terminal_chunks(terminal(), _team_finished()), visibility())

    assert error is None, f"the source stream raised {error!r}"
    assert _terminals_with_reason(events) == [("RUN_FINISHED", None, None)]


@pytest.mark.asyncio
@mappers
@pytest.mark.parametrize(
    "visibility",
    [pytest.param(attributed, id="attributed"), pytest.param(lambda: SUBAGENT_VISIBILITY_HIDDEN, id="hidden")],
)
async def test_a_member_terminal_after_the_top_level_entitys_own_does_not_replace_it(collect, visibility):
    """The run's own failure is what the client is told, whatever a member reports afterwards.

    The default is not driven here: it reads every terminal as the run's, so the
    last one on the stream wins there, which is the stream it has always emitted.
    """
    events, error = await collect(
        _ends_on_the_members_terminal_chunks(_team_failed(), _member_finished()), visibility()
    )

    assert error is None, f"the source stream raised {error!r}"
    assert _terminals_with_reason(events) == [("RUN_ERROR", "the team blew up", "RuntimeError")]


@pytest.mark.asyncio
@mappers
@visibilities
async def test_a_stream_that_ends_on_a_members_pause_still_prompts_the_client(collect, visibility):
    """A pause is a terminal too, and no resume can get past a call nobody was shown."""
    events, error = await collect(_ends_on_the_members_terminal_chunks(_member_paused()), visibility())

    assert error is None, f"the source stream raised {error!r}"
    assert _terminals_with_reason(events) == [("RUN_FINISHED", None, None)]
    assert in_emitted_order(events, EventType.TOOL_CALL_START, "tool_call_id") == [
        ("tc-delegate-scout",),
        ("tc-member-confirm",),
    ]
    assert in_emitted_order(events, EventType.TOOL_CALL_ARGS, "tool_call_id", lambda e: json.loads(e.delta)) == [
        ("tc-delegate-scout", {"member_id": "scout", "task": "scout the topic"}),
        ("tc-member-confirm", {"to": "ops"}),
    ]


@pytest.mark.asyncio
@mappers
async def test_the_member_whose_failure_ended_the_run_still_owns_its_own_terminal(collect):
    subagent_error = event_type_named("SUBAGENT_ERROR")
    events, error = await collect(_ends_on_the_members_terminal_chunks(_member_failed()), attributed())

    assert error is None, f"the source stream raised {error!r}"
    assert_stream_contains(events, subagent_error)
    assert in_emitted_order(events, subagent_error, "subagent_run_id", "message", "code") == [
        ("run-scout", "member exploded", "RuntimeError")
    ]
    # The member's lane resolves first, then the run reports the same failure.
    assert _terminals_with_reason(events) == [("RUN_ERROR", "member exploded", "RuntimeError")]


@pytest.mark.asyncio
@mappers
async def test_hidden_still_reports_a_run_that_ended_on_a_member_failure(collect):
    """Hidden withholds which member failed, never that the run failed."""
    events, error = await collect(_ends_on_the_members_terminal_chunks(_member_failed()), SUBAGENT_VISIBILITY_HIDDEN)

    assert error is None, f"the source stream raised {error!r}"
    assert _terminals_with_reason(events) == [("RUN_ERROR", "member exploded", "RuntimeError")]
    assert not [event for event in events if "SUBAGENT" in str(event.type)]
    assert not [event for event in events if _lane(event) is not None]


# --- Every terminal a member can end a stream on ----------------------------

# The chunk types that stop a member, each with the chunk that reports it and
# what the run terminal has to say when the stream ends there. The interface
# splits them in two: a terminal ends the member's lane, and a withheld chunk
# stops the member without ending it. Both halves are driven, one table each, so
# a type added to either is a stream ending on it rather than a set that grew.

_LINEAGE_RUN_TERMINAL = {
    RunEvent.run_completed.value: (_member_finished, ("RUN_FINISHED", None, None)),
    RunEvent.run_error.value: (_member_failed, ("RUN_ERROR", "member exploded", "RuntimeError")),
    RunEvent.run_cancelled.value: (_member_cancelled, ("RUN_ERROR", "the operator stopped it", "cancelled")),
}

_LINEAGE_WITHHELD = {
    RunEvent.run_paused.value: (_member_paused, ("RUN_FINISHED", None, None)),
}

_STOPS_A_SUBAGENT = {**_LINEAGE_RUN_TERMINAL, **_LINEAGE_WITHHELD}


def test_every_chunk_that_stops_a_subagent_is_driven_here():
    """Both halves of the set the stream reads, each against the table that drives it.

    Which chunks stop a member decides how a stream ending on one is read: the
    run terminal is built from that chunk rather than reported as a plain
    completion. The interface unions its terminal table with its withheld set to
    get there, so comparing the union against either half holds however the
    other grows, and adding a withheld type would end a lane with nothing here
    to say so. Each half is compared against the table this module drives, and
    the union against the two together.
    """
    handled = set(handlers._SUBAGENT_TERMINAL_HANDLERS)
    assert handled == set(_LINEAGE_RUN_TERMINAL), (
        "the subagent terminals the mapper handles and the ones driven here have diverged: "
        f"handled={sorted(handled)}, driven={sorted(_LINEAGE_RUN_TERMINAL)}"
    )
    withheld = set(handlers._SUBAGENT_WITHHELD_EVENTS)
    assert withheld == set(_LINEAGE_WITHHELD), (
        "the chunks the mapper withholds from a member's lane and the ones driven here have diverged: "
        f"withheld={sorted(withheld)}, driven={sorted(_LINEAGE_WITHHELD)}"
    )
    assert not handled & withheld, (
        f"these chunks both end a member's lane and are withheld from it: {sorted(handled & withheld)}"
    )
    assert set(handlers._SUBAGENT_RUN_ENDING_EVENTS) == set(_STOPS_A_SUBAGENT), (
        "the chunks the stream reads as stopping a subagent are no longer the terminals plus the "
        f"withheld ones: {sorted(handlers._SUBAGENT_RUN_ENDING_EVENTS)} against {sorted(_STOPS_A_SUBAGENT)}. "
        "A stream ending on one it no longer reads reports the run finished after saying the subagent did not."
    )


@pytest.mark.asyncio
@mappers
@pytest.mark.parametrize(
    "visibility",
    [pytest.param(attributed, id="attributed"), pytest.param(lambda: SUBAGENT_VISIBILITY_HIDDEN, id="hidden")],
)
@pytest.mark.parametrize("normalized", sorted(_STOPS_A_SUBAGENT))
async def test_a_lineage_stream_ending_on_a_member_terminal_reports_what_that_terminal_said(
    collect, visibility, normalized
):
    """A chunk that stopped a member is the run's only account of how it ended.

    Cancellation included, and a pause included: the run terminal is built from
    whichever of them the stream ended on, and is the last thing on the wire.
    """
    terminal, expected = _STOPS_A_SUBAGENT[normalized]
    events, error = await collect(_ends_on_the_members_terminal_chunks(terminal()), visibility())

    assert error is None, f"the source stream raised {error!r}"
    assert _terminals_with_reason(events) == [expected]
    assert short_type(events[-1]) == expected[0]


@pytest.mark.asyncio
@mappers
@visibilities
async def test_a_run_terminal_promoted_from_a_member_carries_no_chunk_of_that_members_own(collect, visibility):
    """The chunk names the member, its run and the run above it, so only the default embeds it.

    Hidden spends the whole stream keeping that identity off the wire and then
    logs that it withheld the failure, so shipping the member's own chunk in the
    very next event undoes both. Attributed has the member on the wire already,
    but the terminal is the run's and carries nothing of the member's. The
    default is the stream from before member attribution existed, raw event and
    all.
    """
    resolved = visibility()
    events, error = await collect(_ends_on_the_members_terminal_chunks(_member_failed()), resolved)

    assert error is None, f"the source stream raised {error!r}"
    raw_event = field_of(_one(events, EventType.RUN_ERROR), "raw_event")
    if resolved in (None, SUBAGENT_VISIBILITY_INLINE):
        assert raw_event is not None, "the default stream no longer embeds the chunk it always did"
        assert (raw_event.get("run_id"), raw_event.get("agent_id"), raw_event.get("parent_run_id")) == (
            "run-scout",
            "scout",
            TOP_LEVEL_RUN,
        )
    else:
        assert raw_event is None, f"a lineage terminal shipped the member's own chunk: {raw_event}"
    # Either way the run says why it stopped.
    assert _terminals_with_reason(events) == [("RUN_ERROR", "member exploded", "RuntimeError")]


@pytest.mark.asyncio
@mappers
async def test_a_members_pause_that_becomes_the_run_terminal_stays_that_members(collect):
    """The words and the pending call are the member's, so both go out on its lane."""
    subagent_finished = event_type_named("SUBAGENT_FINISHED")
    events, error = await collect(_ends_on_the_members_terminal_chunks(_member_paused_saying_something()), attributed())

    assert error is None, f"the source stream raised {error!r}"
    assert_stream_contains(events, subagent_finished)
    assert in_emitted_order(events, EventType.TEXT_MESSAGE_CONTENT, "delta", _lane) == [
        ("half a sen", "run-scout"),
        ("I need approval to email ops.", "run-scout"),
    ]
    assert in_emitted_order(events, EventType.TOOL_CALL_START, "tool_call_id", _lane) == [
        ("tc-delegate-scout", None),
        ("tc-member-confirm", "run-scout"),
    ]
    # The call and the message carrying it name the same member.
    lane_of_message = {
        event.message_id: _lane(event)  # type: ignore[attr-defined]
        for event in _of_type(events, EventType.TEXT_MESSAGE_START)
    }
    prompted = [e for e in _of_type(events, EventType.TOOL_CALL_START) if e.tool_call_id == "tc-member-confirm"]  # type: ignore[attr-defined]
    assert [lane_of_message[e.parent_message_id] for e in prompted] == ["run-scout"]  # type: ignore[attr-defined]


@pytest.mark.asyncio
@mappers
async def test_hidden_does_not_stream_a_paused_members_words_as_the_runs_own_reply(collect):
    """The pending call still reaches the client, because no resume gets past it.

    Its words do not: nothing a member produced is sent as the run's own work,
    and a prompt is not a licence to relabel the member's prose as the leader's.
    """
    events, error = await collect(
        _ends_on_the_members_terminal_chunks(_member_paused_saying_something()), SUBAGENT_VISIBILITY_HIDDEN
    )

    assert error is None, f"the source stream raised {error!r}"
    assert in_emitted_order(events, EventType.TOOL_CALL_START, "tool_call_id", _lane) == [
        ("tc-delegate-scout", None),
        ("tc-member-confirm", None),
    ]
    assert in_emitted_order(events, EventType.TEXT_MESSAGE_CONTENT, "delta") == []
    assert not [event for event in events if _lane(event) is not None]


# --- Abandonment ------------------------------------------------------------


_UP_TO_OPEN_MESSAGE = [
    str(EventType.RAW),
    str(EventType.TEXT_MESSAGE_START),
    str(EventType.TEXT_MESSAGE_CONTENT),
]

_AGEN_CLOSED = "closed"


def _async_generator_state(generator: AsyncGenerator[Any, None]) -> str:
    """Whether an async generator is closed, running, or still holding its frame.

    ``inspect.getasyncgenstate`` and its ``AGEN_CLOSED`` constant are Python
    3.12, and this package supports 3.9, so the state is read the way that
    helper reads it: a closed async generator has dropped its frame. The sync
    twin below keeps ``inspect.getgeneratorstate``, which has been there since
    3.2.
    """
    if generator.ag_running:
        return "running"
    return _AGEN_CLOSED if generator.ag_frame is None else "still holding its frame"


def _recorded_cleanups(monkeypatch) -> List[str]:
    """A spy on the mapper's own cleanup, so its absence can be observed rather than assumed.

    Collecting events up to the abandonment and inspecting the list afterwards
    cannot see a cleanup: whatever the closed generator does next is not written
    into any list the test still holds.
    """
    called: List[str] = []

    def spy(state: StreamState, error_message: str) -> List[BaseEvent]:
        called.append(error_message)
        return []

    monkeypatch.setattr(stream_module, "close_open_spans", spy)
    return called


def test_abandoning_the_sync_mapper_mid_message_emits_no_cleanup(monkeypatch):
    """A consumer that walks away is not a failure: the client is gone, so nothing is written to it."""
    cleanups = _recorded_cleanups(monkeypatch)
    generator = stream_agno_response_as_agui_events(
        sync_source(_open_text_message_chunks("never raised")), thread_id=THREAD_ID, run_id=TOP_LEVEL_RUN
    )
    seen = [next(generator) for _ in _UP_TO_OPEN_MESSAGE]

    generator.close()
    # A closed generator yields nothing ever, so draining it here would observe
    # nothing an abandonment wrote. The spy is what observes the cleanup's
    # absence; this pins that the close really left the generator closed rather
    # than resuming it into one.
    assert inspect.getgeneratorstate(generator) == inspect.GEN_CLOSED

    assert cleanups == []
    assert [str(e.type) for e in seen] == _UP_TO_OPEN_MESSAGE
    assert_well_formed_stream(seen, exempt=[ABANDONED_MID_STREAM])


@pytest.mark.asyncio
async def test_abandoning_the_async_mapper_mid_message_emits_no_cleanup(monkeypatch):
    cleanups = _recorded_cleanups(monkeypatch)
    generator = async_stream_agno_response_as_agui_events(
        async_source(_open_text_message_chunks("never raised")), thread_id=THREAD_ID, run_id=TOP_LEVEL_RUN
    )
    seen = [await generator.__anext__() for _ in _UP_TO_OPEN_MESSAGE]

    await generator.aclose()
    assert _async_generator_state(generator) == _AGEN_CLOSED

    assert cleanups == []
    assert [str(e.type) for e in seen] == _UP_TO_OPEN_MESSAGE
    assert_well_formed_stream(seen, exempt=[ABANDONED_MID_STREAM])


def _assert_the_abandoned_member_never_resolved(seen: List[BaseEvent], cleanups: List[str]) -> None:
    assert cleanups == []
    assert_stream_contains(seen, event_type_named("SUBAGENT_STARTED"))
    assert not _of_type(seen, event_type_named("SUBAGENT_ERROR"))
    assert not _of_type(seen, event_type_named("SUBAGENT_FINISHED"))
    assert_well_formed_stream(seen, exempt=[ABANDONED_MID_STREAM, ABANDONED_WITH_A_MEMBER_STILL_OPEN])


def test_abandoning_the_sync_mapper_inside_a_member_leaves_that_member_unterminated(monkeypatch):
    """The member is announced and then abandoned, so its lane never resolves either."""
    cleanups = _recorded_cleanups(monkeypatch)
    generator = stream_agno_response_as_agui_events(
        sync_source(_open_member_lane_chunks("never raised")),
        thread_id=THREAD_ID,
        run_id=TOP_LEVEL_RUN,
        subagent_visibility=attributed(),
    )
    seen: List[BaseEvent] = []
    for event in generator:
        seen.append(event)
        if event.type == EventType.TEXT_MESSAGE_CONTENT and _lane(event) == "run-scout":
            break

    generator.close()
    assert inspect.getgeneratorstate(generator) == inspect.GEN_CLOSED

    _assert_the_abandoned_member_never_resolved(seen, cleanups)


@pytest.mark.asyncio
async def test_abandoning_the_async_mapper_inside_a_member_leaves_that_member_unterminated(monkeypatch):
    cleanups = _recorded_cleanups(monkeypatch)
    generator = async_stream_agno_response_as_agui_events(
        async_source(_open_member_lane_chunks("never raised")),
        thread_id=THREAD_ID,
        run_id=TOP_LEVEL_RUN,
        subagent_visibility=attributed(),
    )
    seen: List[BaseEvent] = []
    async for event in generator:
        seen.append(event)
        if event.type == EventType.TEXT_MESSAGE_CONTENT and _lane(event) == "run-scout":
            break

    await generator.aclose()
    assert _async_generator_state(generator) == _AGEN_CLOSED

    _assert_the_abandoned_member_never_resolved(seen, cleanups)


# --- A cleanup that fails itself --------------------------------------------


def _explodes(state, error_message: str) -> List[BaseEvent]:
    raise RuntimeError("cleanup exploded")


def test_a_failed_cleanup_does_not_replace_the_sync_failure_it_followed(monkeypatch, caplog):
    """The failure the caller turns into the run terminal is the run's own, never the cleanup's."""
    visibility = attributed()
    monkeypatch.setattr(stream_module, "close_open_spans", _explodes)
    events: List[BaseEvent] = []

    with captured_agno_logs(caplog, "ERROR"):
        with pytest.raises(_Boom, match="keep me"):
            for event in stream_agno_response_as_agui_events(
                sync_source(_open_member_lane_chunks("keep me")),
                thread_id=THREAD_ID,
                run_id=TOP_LEVEL_RUN,
                subagent_visibility=visibility,
            ):
                events.append(event)

    assert _terminals(events) == []
    logged = "\n".join(r.message for r in caplog.records)
    assert "keep me" in logged
    assert "cleanup exploded" in logged


@pytest.mark.asyncio
async def test_a_failed_cleanup_does_not_replace_the_async_failure_it_followed(monkeypatch, caplog):
    visibility = attributed()
    monkeypatch.setattr(stream_module, "close_open_spans", _explodes)
    events: List[BaseEvent] = []

    with captured_agno_logs(caplog, "ERROR"):
        with pytest.raises(_Boom, match="keep me"):
            async for event in async_stream_agno_response_as_agui_events(
                async_source(_open_member_lane_chunks("keep me")),
                thread_id=THREAD_ID,
                run_id=TOP_LEVEL_RUN,
                subagent_visibility=visibility,
            ):
                events.append(event)

    assert _terminals(events) == []
    logged = "\n".join(r.message for r in caplog.records)
    assert "keep me" in logged
    assert "cleanup exploded" in logged


@pytest.mark.asyncio
@mappers
async def test_the_cleanup_after_a_failed_stream_is_recorded(collect, caplog):
    """The cleanup is invisible to the operator unless the failure it followed is logged."""
    subagent_error = event_type_named("SUBAGENT_ERROR")
    with captured_agno_logs(caplog, "ERROR"):
        events, error = await collect(_open_member_lane_chunks("member exploded mid-stream"), attributed())

    assert isinstance(error, _Boom)
    assert_stream_contains(events, subagent_error)
    logged = "\n".join(r.message for r in caplog.records)
    assert "member exploded mid-stream" in logged


@pytest.mark.asyncio
@mappers
async def test_the_recorded_mid_run_failure_names_its_type_and_carries_its_traceback(collect, caplog):
    """The message alone says where a failure surfaced, never what raised or from where.

    This package logs tracebacks only when they are switched on, so the one
    record an operator gets for a dead stream has to carry both by itself.
    """
    with captured_agno_logs(caplog, "ERROR"):
        events, error = await collect(_open_text_message_chunks("model connection dropped"))

    assert isinstance(error, _Boom)
    assert_stream_contains(events, EventType.TEXT_MESSAGE_END)
    recorded = [record for record in caplog.records if "model connection dropped" in record.message]
    assert len(recorded) == 1, f"the mid-run failure was recorded {len(recorded)} times"
    assert "_Boom" in recorded[0].message, f"the record does not name what raised: {recorded[0].message}"
    assert recorded[0].exc_info is not None, "the record carries no traceback, so the raise site is lost"


# --- A failure that cannot describe itself ----------------------------------


class _Unspeakable(RuntimeError):
    """A failure whose own text cannot be rendered, as a proxy object's cannot."""

    def __str__(self) -> str:
        raise RuntimeError("str exploded")


def _member_lane_open_when_an_unspeakable_failure_arrives() -> List[Any]:
    member = _member_kwargs("scout", "run-scout")
    return [
        TeamRunStartedEvent(team_id="research-team", team_name="Research Team", run_id=TOP_LEVEL_RUN),
        TeamToolCallStartedEvent(run_id=TOP_LEVEL_RUN, tool=_delegation()),
        RunStartedEvent(**member),
        _content("scouting so", **member),
        _Unspeakable(),
    ]


@pytest.mark.asyncio
@mappers
async def test_a_failure_whose_text_cannot_be_read_still_closes_every_span_it_left_open(collect, caplog):
    """Naming a failure must never become the failure.

    The message and the record are both built from the exception before any
    cleanup runs, so rendering one unguarded ends the stream with no record, no
    closed span, no terminated member lane, and the run's real failure replaced
    by whatever the attempt to describe it raised.
    """
    subagent_error = event_type_named("SUBAGENT_ERROR")
    with captured_agno_logs(caplog, "WARNING"):
        events, error = await collect(_member_lane_open_when_an_unspeakable_failure_arrives(), attributed())

    assert type(error) is _Unspeakable, f"the run's own failure was replaced by {type(error).__name__}"
    # The lane still resolves, under the name of what raised, since it has no
    # text of its own to report.
    assert_stream_contains(events, subagent_error)
    assert in_emitted_order(events, subagent_error, "subagent_run_id", "message", "code") == [
        ("run-scout", "_Unspeakable", None)
    ]
    assert_stream_contains(events, EventType.TEXT_MESSAGE_END)
    assert in_emitted_order(events, EventType.TOOL_CALL_END, "tool_call_id") == [("tc-delegate-scout",)]
    logged = "\n".join(record.message for record in caplog.records)
    assert "_Unspeakable" in logged, f"the failure was not recorded at all: {logged}"
