"""Hostile run content driven through every AG-UI event-building boundary.

A member result that could not be serialized once turned a successful run into a
failed one, so that one boundary was hardened to fall back rather than raise.
Nothing checked the others. This module drives one table of hostile values
through every place the interface builds an AG-UI event out of run content, and
pins, per cell, what actually happens today:

``TERMINATES``
    The run reaches its own terminal with the value rendered, dropped or
    replaced, the stream is well formed, and every event it carries is one the
    protocol's own encoder can put on a wire.
``TERMINATES_UNSENDABLE``
    The run reaches its terminal in memory, but the event THIS boundary built is
    one that encoder refuses. On a real wire the response body stops at that
    event: the client is left with a truncated stream and no terminal at all.
    Worse than a failed run, and reported as a finding rather than fixed here.
``dies_on(...)``
    The run reaches its terminal, this boundary's own event is one the encoder
    accepts, and the stream dies at some other event instead. The verdict names
    that event, because the same value can be harmless where this boundary
    reads it and fatal where another one does, and a cell that did not say
    which credited the wrong boundary with the failure.
``DROPPED_BEFORE_THE_BOUNDARY``
    The run terminates, every event it carries is sendable, and the event this
    boundary builds was never emitted: the value was discarded before the
    boundary was reached. Such a cell pins the extractor that swallowed it
    rather than the boundary, which is why it is named instead of counted as a
    success.
``dropped_and_dies_on(...)``
    The value was discarded before the boundary AND the stream is one the
    encoder refuses elsewhere, so the client never sees the run's terminal. Read
    without consulting the encoder, such a cell reported a truncated stream as a
    run that reached the client.
``ENDS_THE_RUN``
    Building the event raises, the mapper's own cleanup closes what it opened,
    and the failure propagates instead of the run terminal. The client sees a
    failed run rather than a rendered one, but nothing is left dangling.
``ENDS_THE_RUN_MALFORMED``
    Building the event raises AFTER the mapper recorded the span in its state,
    so the wire is left with a span the client can never resolve: a tool call
    with no end, a reasoning block ended without a start, or a text message left
    open. This is worse than a failed run and is reported as a finding rather
    than fixed here.

Five things keep a cell from going green, or red, for the wrong reason. Every
cell drives its boundary with content the boundary handles, so a verdict is
attributable to the value the case injected rather than to a broken fixture or a
misconfigured stream. Each fixture injects the value at one boundary only: a
fixture that put it in two places reported whichever the interface read first
under the name of the other. The verdict says whether the boundary's own event
reached the wire before it attributes a refusal, and it consults the encoder
either way, so a stream carrying some other unsendable event cannot stand in for
this boundary building one and a boundary that built nothing cannot hide one.
Every boundary is driven with every hostile value, checked against an
independent list of those values, so a row cannot quietly stop being swept and a
value added to the shared table cannot go undriven. And the set of boundaries
itself is recomputed from the interface's own source, per function AND per event
type: every event each scope of the package constructs is claimed by a row,
covered by a named test here, or justified as built out of no run content, so a
function that builds six events cannot be counted as driven because one row
drives one of them.

One row is not an event boundary at all: the identifiers a member's failure is
recorded with never reach the wire, so that row drives its value through the log
line the member's terminal is accompanied by, and pins the terminal it must not
prevent. Everything else in that row reads exactly like the others.

The table is the point. Hardening any boundary flips its cells, which fails this
module and forces the table to be brought up to date rather than letting the new
behavior go unrecorded. The same cells are asserted under the default
visibility, which differs only by the member lifecycle, so a boundary that
behaves differently there is a difference the default was not supposed to have.
A boundary that builds nothing under the default is still held to what the rest
of that stream did with the value, the encoder included, since the member's own
chunks go out there as RAW.

The whole module holds on a protocol release without the lineage events too. The
interface builds those behind a guarded import, so on such a release its source
constructs none of them; the coverage check leaves an event type the installed
protocol does not define out of the comparison on both sides rather than
reporting the rows naming it as claims about nothing.
"""

import json
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Set, Tuple

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import BaseEvent, EventType, RunAgentInput, UserMessage
from ag_ui.encoder import EventEncoder

from agno.models.response import ToolExecution
from agno.os.interfaces.agui.router import run_entity
from agno.reasoning.step import ReasoningStep
from agno.run.agent import (
    CustomEvent,
    ReasoningContentDeltaEvent,
    ReasoningStepEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunErrorEvent,
    RunStartedEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.requirement import RunRequirement
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.run.team import RunStartedEvent as TeamRunStartedEvent

from .agui_stream_invariants import (
    HOSTILE_VALUES,
    TOP_LEVEL_RUN,
    MalformedCollected,
    RaisesAnUnreadableError,
    SideEffect,
    agent_said,
    assert_stream_contains,
    attributed,
    captured_agno_logs,
    collect_async_recording_violations,
    collect_sync_recording_violations,
    encoding_failures,
    event_type_named,
    lane_of,
    member_chunk_kwargs,
    of_type,
    short_type_name,
    team_chunk_kwargs,
    team_said,
)
from .test_agui_documented_contract import event_constructions_by_function

THREAD_ID = "hostile-session"
# The same lineage fields the attribution suite builds its chunks from.
_TOP_LEVEL = team_chunk_kwargs("research-team", "Research Team", TOP_LEVEL_RUN)
_MEMBER = member_chunk_kwargs("scout", "run-scout")

TERMINATES = "terminates"
TERMINATES_UNSENDABLE = "terminates in memory and dies on the wire at this boundary's own event"
DROPPED_BEFORE_THE_BOUNDARY = "terminates, with the value dropped before the boundary"
ENDS_THE_RUN = "ends the run"
ENDS_THE_RUN_MALFORMED = "ends the run and leaves the stream malformed"

_DIES_ELSEWHERE = "terminates, with this boundary's own event sendable and the stream dying on "
_DROPPED_AND_DIES_ELSEWHERE = "terminates, with the value dropped before the boundary and the stream dying on "


def _naming(prefix: str, event_names: Tuple[str, ...]) -> str:
    assert event_names, "a verdict about a refused event has to name the event"
    return prefix + ", ".join(sorted(event_names))


def dies_on(*event_names: str) -> str:
    """The verdict for a stream the encoder refuses somewhere other than here.

    The event is named, so a cell cannot report a stream-wide refusal as though
    this boundary had built the event the encoder choked on.
    """
    return _naming(_DIES_ELSEWHERE, event_names)


def dropped_and_dies_on(*event_names: str) -> str:
    """The verdict for a value dropped before the boundary on a stream that still dies.

    "Dropped" alone is a claim that the run reached the client, which is false
    of a stream the encoder refuses partway through. The value never reached
    this boundary AND the client is left with a truncated stream, so the cell
    has to say both and name the event that truncated it.
    """
    return _naming(_DROPPED_AND_DIES_ELSEWHERE, event_names)


# What every surviving verdict has in common, for the one claim that holds
# across all of them.
REACHES_ITS_TERMINAL = "reaches its terminal"
_ENDED = (ENDS_THE_RUN, ENDS_THE_RUN_MALFORMED)


def _survives(verdict: str) -> bool:
    return verdict not in _ENDED


def _is_a_verdict(outcome: str) -> bool:
    """Whether an outcome is one this module can actually reach."""
    return outcome in (TERMINATES, TERMINATES_UNSENDABLE, DROPPED_BEFORE_THE_BOUNDARY, *_ENDED) or outcome.startswith(
        (_DIES_ELSEWHERE, _DROPPED_AND_DIES_ELSEWHERE)
    )


_HOSTILE = dict(HOSTILE_VALUES)
_RUN_TERMINALS = (EventType.RUN_FINISHED, EventType.RUN_ERROR)


class Fixture(NamedTuple):
    """One boundary's chunk list, and the session state the run carries with it."""

    chunks: List[Any]
    run_state: Optional[Dict[str, Any]] = None


# --- Chunk lists, one per event-building boundary ----------------------------


def _member_run(*inner: Any) -> List[Any]:
    return [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**_MEMBER),
        *inner,
        RunCompletedEvent(content="scout done", **_MEMBER),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]


def _member_terminal_result(value: Any) -> Fixture:
    """The member terminal's ``result``, built by the one hardened boundary."""
    return Fixture(
        [
            TeamRunStartedEvent(**_TOP_LEVEL),
            RunStartedEvent(**_MEMBER),
            RunCompletedEvent(content=value, **_MEMBER),
            TeamRunCompletedEvent(**_TOP_LEVEL),
        ]
    )


def _agent_text_delta(value: Any) -> Fixture:
    """TEXT_MESSAGE_CONTENT built from an Agent chunk's content."""
    return Fixture(_member_run(agent_said(value, **_MEMBER)))


def _team_text_delta(value: Any) -> Fixture:
    """TEXT_MESSAGE_CONTENT built from a Team chunk's own content."""
    leader = TeamRunContentEvent(**_TOP_LEVEL)
    leader.content = value
    return Fixture([TeamRunStartedEvent(**_TOP_LEVEL), leader, TeamRunCompletedEvent(**_TOP_LEVEL)])


def _team_member_response_delta(value: Any) -> Fixture:
    """TEXT_MESSAGE_CONTENT built by folding a Team chunk's nested member outputs.

    The leader says nothing of its own here. Its own text would put a delta on
    the wire whatever the fold did with the member's output, which is a green
    cell for a boundary the case never exercised.
    """
    leader = TeamRunContentEvent(**_TOP_LEVEL)
    leader.member_responses = [agent_said(value, **_MEMBER)]
    return Fixture([TeamRunStartedEvent(**_TOP_LEVEL), leader, TeamRunCompletedEvent(**_TOP_LEVEL)])


def _tool_call_args(value: Any) -> Fixture:
    """TOOL_CALL_ARGS built from a tool call's arguments."""
    tool = ToolExecution(tool_call_id="tc-hostile", tool_name="do_it", tool_args=value)
    return Fixture(
        _member_run(ToolCallStartedEvent(tool=tool, **_MEMBER), ToolCallCompletedEvent(tool=tool, **_MEMBER))
    )


def _tool_call_result(value: Any) -> Fixture:
    """TOOL_CALL_RESULT built from a tool call's result."""
    tool = ToolExecution(tool_call_id="tc-hostile", tool_name="do_it", tool_args={}, result=value)
    return Fixture(
        _member_run(ToolCallStartedEvent(tool=tool, **_MEMBER), ToolCallCompletedEvent(tool=tool, **_MEMBER))
    )


def _reasoning_content_delta(value: Any) -> Fixture:
    """REASONING_MESSAGE_CONTENT built from a streamed reasoning delta."""
    chunk = ReasoningContentDeltaEvent(**_MEMBER)
    chunk.reasoning_content = value
    return Fixture(_member_run(chunk))


def _reasoning_step_payload(value: Any) -> Fixture:
    """REASONING_MESSAGE_CONTENT built from a reasoning step that is not one."""
    chunk = ReasoningStepEvent(**_MEMBER)
    chunk.content = value
    return Fixture(_member_run(chunk))


def _reasoning_step_field(value: Any) -> Fixture:
    """REASONING_MESSAGE_CONTENT built from a reasoning step holding hostile text."""
    step = ReasoningStep(title="scout plan", reasoning="scout is thinking")
    step.reasoning = value
    chunk = ReasoningStepEvent(**_MEMBER)
    chunk.content = step
    return Fixture(_member_run(chunk))


def _custom_event_payload(value: Any) -> Fixture:
    """CUSTOM built from a custom chunk's own dump."""
    chunk = CustomEvent(**_MEMBER)
    chunk.to_dict = lambda: {"payload": value}  # type: ignore[method-assign]
    return Fixture(_member_run(chunk))


def _raw_event_payload(value: Any) -> Fixture:
    """RAW built from an unmapped chunk's own dump.

    The stream opens on the leader's own text rather than on a run-started
    chunk, which this interface passes through as RAW itself. With one of those
    ahead of it, a RAW is on the wire whatever this boundary does, so the
    boundary's own event can never be reported missing and a dump discarded
    before the boundary would read as one that reached it.
    """
    chunk = RunStartedEvent(**_MEMBER)
    chunk.to_dict = lambda: {"event": "RunStarted", "payload": value}  # type: ignore[method-assign]
    return Fixture(
        [
            team_said("leader speaking", **_TOP_LEVEL),
            chunk,
            RunCompletedEvent(content="scout done", **_MEMBER),
            TeamRunCompletedEvent(**_TOP_LEVEL),
        ]
    )


def _failing_run_with_a_member_mid_sentence(value: Any) -> Fixture:
    """A run that fails on hostile content while a member is still streaming.

    Two boundaries read that content: the run terminal the client is told about,
    and the terminal every member lane still open is closed with.
    """
    return Fixture(
        [
            TeamRunStartedEvent(**_TOP_LEVEL),
            RunStartedEvent(**_MEMBER),
            agent_said("half a sen", **_MEMBER),
            TeamRunErrorEvent(content=value, error_type="RuntimeError", **_TOP_LEVEL),
        ]
    )


def _state_delta(value: Any) -> Fixture:
    """STATE_DELTA built by diffing the session state a member's tool changed."""
    session_state: Dict[str, Any] = {"approved": False}
    tool = ToolExecution(tool_call_id="tc-approve", tool_name="approve", tool_args={}, result="ok")
    return Fixture(
        [
            TeamRunStartedEvent(**_TOP_LEVEL),
            RunStartedEvent(**_MEMBER),
            ToolCallStartedEvent(tool=tool, **_MEMBER),
            # Applied while the stream is being consumed, so the delta really is
            # computed from a change the client had not seen yet.
            SideEffect(lambda: session_state.__setitem__("value", value)),
            ToolCallCompletedEvent(tool=tool, **_MEMBER),
            RunCompletedEvent(content="scout done", **_MEMBER),
            TeamRunCompletedEvent(**_TOP_LEVEL),
        ],
        run_state=session_state,
    )


# What a caller that says nothing about the paused run's words passes. A missing
# argument cannot be spelled None here: None is one of the hostile values, and a
# cell keyed on it would pin what an unset content does rather than what an
# explicitly empty one does.
_SAYS_NOTHING = object()


def _paused_run(tool: ToolExecution, content: Any = _SAYS_NOTHING) -> Fixture:
    """A run that pauses on one pending call, and says what it says while pausing.

    One hostile value per fixture, never two. A pause reads its own words before
    it builds any of the prompt, so a fixture injecting the value into both the
    words and the call credited the call's boundary with whatever the words did
    first: the value that cannot be rendered ends the run from inside
    ``_pause_content``, several events before the arguments are serialized.
    """
    paused = TeamRunPausedEvent(tools=[tool], **_TOP_LEVEL)
    if content is not _SAYS_NOTHING:
        paused.content = content
    return Fixture([TeamRunStartedEvent(**_TOP_LEVEL), paused])


def _pause_prompt_args(value: Any) -> Fixture:
    """TOOL_CALL_ARGS built from the arguments of a call a paused run waits on."""
    return _paused_run(
        ToolExecution(
            tool_call_id="tc-hostile-confirm", tool_name="confirm", tool_args=value, requires_confirmation=True
        )
    )


def _benign_pending_call() -> ToolExecution:
    return ToolExecution(
        tool_call_id="tc-hostile-confirm", tool_name="confirm", tool_args={"to": "ops"}, requires_confirmation=True
    )


def _pause_prompt_content(value: Any) -> Fixture:
    """TEXT_MESSAGE_CONTENT built from what a paused run says while it waits."""
    return _paused_run(_benign_pending_call(), content=value)


def _pause_tool_name(value: Any) -> Fixture:
    """TOOL_CALL_START built from the name of a call a paused run waits on."""
    return _paused_run(
        ToolExecution(
            tool_call_id="tc-hostile-confirm", tool_name=value, tool_args={"to": "ops"}, requires_confirmation=True
        )
    )


def _pause_tool_id(value: Any) -> Fixture:
    """TOOL_CALL_START built from the id of a call a paused run waits on."""
    return _paused_run(
        ToolExecution(tool_call_id=value, tool_name="confirm", tool_args={"to": "ops"}, requires_confirmation=True)
    )


def _tool_call_name(value: Any) -> Fixture:
    """TOOL_CALL_START built from the name the model gave the tool it called.

    The call completes, as it does at the two boundaries above: a member's
    terminal ends no tool call, so a call left dangling here would make the
    benign row of this boundary a stream the run end closes after the member's
    terminal, which is a shape of its own rather than anything this boundary is
    about.
    """
    tool = ToolExecution(tool_call_id="tc-hostile", tool_name=value, tool_args={})
    return Fixture(
        _member_run(ToolCallStartedEvent(tool=tool, **_MEMBER), ToolCallCompletedEvent(tool=tool, **_MEMBER))
    )


def _tool_call_id(value: Any) -> Fixture:
    """TOOL_CALL_START built from the id the model gave the call, which may be missing."""
    tool = ToolExecution(tool_call_id=value, tool_name="do_it", tool_args={})
    return Fixture(
        _member_run(ToolCallStartedEvent(tool=tool, **_MEMBER), ToolCallCompletedEvent(tool=tool, **_MEMBER))
    )


def _subagent_error_message(value: Any) -> Fixture:
    """SUBAGENT_ERROR's message, built from what a member's failing run reported.

    The team finishes afterwards, so the member's failure is this boundary's
    subject rather than the run terminal: read as the run's own terminal, which
    is what the default does with it, the value would land at the RUN_ERROR
    boundary above instead.
    """
    failure = RunErrorEvent(error_type="RuntimeError", **_MEMBER)
    failure.content = value
    return Fixture(
        [
            TeamRunStartedEvent(**_TOP_LEVEL),
            RunStartedEvent(**_MEMBER),
            failure,
            TeamRunCompletedEvent(**_TOP_LEVEL),
        ]
    )


def _subagent_error_correlation(value: Any) -> Fixture:
    """The identifiers a member's failure is recorded with, alongside its SUBAGENT_ERROR."""
    failure = RunErrorEvent(content="member exploded", error_type="RuntimeError", error_id="err-42", **_MEMBER)
    failure.additional_data = {"attempt": value}
    return Fixture(
        [
            TeamRunStartedEvent(**_TOP_LEVEL),
            RunStartedEvent(**_MEMBER),
            failure,
            TeamRunCompletedEvent(**_TOP_LEVEL),
        ]
    )


def _subagent_cancellation_reason(value: Any) -> Fixture:
    """SUBAGENT_ERROR's message, built from the reason a member's run was cancelled."""
    cancelled = RunCancelledEvent(**_MEMBER)
    cancelled.reason = value
    return Fixture(
        [
            TeamRunStartedEvent(**_TOP_LEVEL),
            RunStartedEvent(**_MEMBER),
            cancelled,
            TeamRunCompletedEvent(**_TOP_LEVEL),
        ]
    )


def _paused_member_name(value: Any) -> Fixture:
    """SUBAGENT_STARTED's name, built from the identity a paused run names its member by.

    The member id stays readable, so a name that cannot be read has somewhere to
    fall back to and the announcement is still expected on the wire.
    """
    tool = ToolExecution(
        tool_call_id="tc-member-confirm", tool_name="send_email", tool_args={"to": "ops"}, requires_confirmation=True
    )
    requirement = RunRequirement(tool)
    requirement.member_agent_id = "scout"
    requirement.member_run_id = "run-scout"
    requirement.member_agent_name = value
    return Fixture(
        [
            TeamRunStartedEvent(**_TOP_LEVEL),
            TeamRunPausedEvent(tools=[], requirements=[requirement], **_TOP_LEVEL),
        ]
    )


def _member_identity(value: Any) -> Fixture:
    """SUBAGENT_STARTED built from the name and id a member's chunks carry."""
    member = {"agent_id": value, "agent_name": value, "run_id": "run-anonymous", "parent_run_id": TOP_LEVEL_RUN}
    return Fixture(
        [
            TeamRunStartedEvent(**_TOP_LEVEL),
            RunStartedEvent(**member),
            agent_said("member speaking", **member),
            RunCompletedEvent(content="done", **member),
            TeamRunCompletedEvent(**_TOP_LEVEL),
        ]
    )


_ALL_VALUES = tuple(name for name, _ in HOSTILE_VALUES)

# The values this table was written against, named rather than derived from the
# shared list the sweep reads. Derived, the completeness check compares the
# shared list with itself and holds however that list changes; named, a value
# added to it lands here first and every row has to state an outcome for it.
_HOSTILE_VALUE_NAMES = (
    "circular",
    "raises_on_serialization",
    "raises_an_unreadable_error",
    "set",
    "not_a_number",
    "none",
)


def _everywhere(outcome: str) -> Dict[str, str]:
    return {name: outcome for name in _ALL_VALUES}


def _terminates_except(**overrides: str) -> Dict[str, str]:
    expected = _everywhere(TERMINATES)
    expected.update(overrides)
    return expected


def _dropped_except(**overrides: str) -> Dict[str, str]:
    expected = _everywhere(DROPPED_BEFORE_THE_BOUNDARY)
    expected.update(overrides)
    return expected


_NO_DEFAULT_OVERRIDES: Mapping[str, str] = MappingProxyType({})


class Boundary(NamedTuple):
    """One place the interface builds an AG-UI event out of run content."""

    name: str
    builder: Callable[[Any], Fixture]
    # The event this boundary builds, by name, so a cell that emitted none of it
    # cannot pass as one that exercised the boundary.
    event: str
    # The interface function that constructs that event, named as the source
    # scan names it: module, then the scope inside it. Checked against a scan of
    # the package's own source, so a row cannot claim a function that builds
    # something else, and a function-and-event pair nothing here claims fails
    # the coverage check below.
    builds: str
    # A value the boundary handles, to prove the fixture reaches it at all.
    # Built per case, so no two cases share one object.
    benign: Callable[[], Any]
    # What every hostile value does here. Every boundary is driven with every
    # value, so this states one outcome per value and nothing narrows the sweep.
    outcomes: Dict[str, str]
    # Whether that event exists on the wire only under member attribution.
    lineage_only: bool = False
    # What the same fixture does under the default visibility, stated only where
    # that differs from the run merely reaching its terminal. Only a
    # lineage-only boundary can need one: it builds nothing there, so the cell
    # is about what the rest of the stream did with the value instead, and the
    # member's own unmapped chunks still carry it out as RAW.
    #
    # A NamedTuple default is one object shared by every row that leaves it
    # unset, so this one is immutable: a row reaching for it and writing into it
    # would otherwise state that cell for every other row too.
    under_the_default: Mapping[str, str] = _NO_DEFAULT_OVERRIDES


# Every boundary that builds an AG-UI event out of run content, the values it is
# driven with, and what happens today under member attribution. ``not_a_number``
# and ``none`` are the two values most serializers handle, which is why they are
# the quiet column. Each row names the interface function that builds its event,
# which the coverage test at the bottom of this module checks the whole table
# against.
_BOUNDARIES: Tuple[Boundary, ...] = (
    # The boundary hardened against a value that cannot be serialized: every
    # route falls back rather than raising. Each of those fallbacks records the
    # failure by rendering it, though, so the value whose failure cannot be
    # rendered either ends the run from inside the record of the first route
    # that refused it, before any of the later routes is tried.
    Boundary(
        "member_terminal_result",
        _member_terminal_result,
        "SUBAGENT_FINISHED",
        "handlers._lane_finished",
        lambda: "scout done",
        _terminates_except(raises_an_unreadable_error=ENDS_THE_RUN),
        lineage_only=True,
        # The default opens no member lane, so the serialization this boundary
        # is about is never run there at all and the value reaches nothing.
        under_the_default={"raises_an_unreadable_error": REACHES_ITS_TERMINAL},
    ),
    # json.dumps of the content is unguarded, so a cycle ends the run. Every
    # other value is swallowed by the text extractor before a delta is built,
    # so those cells reach the extractor and stop there.
    Boundary(
        "agent_text_delta",
        _agent_text_delta,
        "TEXT_MESSAGE_CONTENT",
        "handlers.on_run_content",
        lambda: "hello",
        _dropped_except(circular=ENDS_THE_RUN),
    ),
    Boundary(
        "team_text_delta",
        _team_text_delta,
        "TEXT_MESSAGE_CONTENT",
        "handlers.on_run_content",
        lambda: "hello",
        _dropped_except(circular=ENDS_THE_RUN),
    ),
    # The leader says nothing of its own here, so a nested member output that
    # folds into nothing leaves no delta on the wire at all: the leader's text
    # message opens and closes empty.
    Boundary(
        "team_member_response_delta",
        _team_member_response_delta,
        "TEXT_MESSAGE_CONTENT",
        "handlers.on_run_content",
        lambda: "hello",
        _dropped_except(circular=ENDS_THE_RUN),
    ),
    # json.dumps of the arguments is unguarded, so anything it refuses ends the
    # run. The tool call itself is never announced, so nothing dangles.
    Boundary(
        "tool_call_args",
        _tool_call_args,
        "TOOL_CALL_ARGS",
        "handlers.on_tool_call_started",
        lambda: {"query": "agno"},
        _terminates_except(
            circular=ENDS_THE_RUN,
            raises_on_serialization=ENDS_THE_RUN,
            raises_an_unreadable_error=ENDS_THE_RUN,
            set=ENDS_THE_RUN,
        ),
    ),
    # The call is marked ended in the mapper's state before its result is
    # serialized, so a result the serializer refuses discards the end event and
    # leaves the tool call open on the wire for good.
    Boundary(
        "tool_call_result",
        _tool_call_result,
        "TOOL_CALL_RESULT",
        "handlers.on_tool_call_completed",
        lambda: "three sources",
        _terminates_except(
            circular=ENDS_THE_RUN_MALFORMED,
            raises_on_serialization=ENDS_THE_RUN_MALFORMED,
            raises_an_unreadable_error=ENDS_THE_RUN_MALFORMED,
            set=ENDS_THE_RUN_MALFORMED,
            none=DROPPED_BEFORE_THE_BOUNDARY,
        ),
    ),
    # The reasoning span is opened in the mapper's state before the content
    # event is built, so a delta the protocol model refuses discards the start
    # while the state keeps the span, and the cleanup ends an id the client was
    # never given a start for.
    Boundary(
        "reasoning_content_delta",
        _reasoning_content_delta,
        "REASONING_MESSAGE_CONTENT",
        "handlers.on_reasoning_content_delta",
        lambda: "first I ",
        _terminates_except(
            circular=ENDS_THE_RUN_MALFORMED,
            raises_on_serialization=ENDS_THE_RUN_MALFORMED,
            raises_an_unreadable_error=ENDS_THE_RUN_MALFORMED,
            set=ENDS_THE_RUN_MALFORMED,
            not_a_number=ENDS_THE_RUN_MALFORMED,
            none=DROPPED_BEFORE_THE_BOUNDARY,
        ),
    ),
    Boundary(
        "reasoning_step_payload",
        _reasoning_step_payload,
        "REASONING_MESSAGE_CONTENT",
        "handlers.on_reasoning_step",
        lambda: ReasoningStep(title="scout plan", reasoning="scout is thinking"),
        _terminates_except(
            circular=ENDS_THE_RUN_MALFORMED,
            raises_on_serialization=ENDS_THE_RUN_MALFORMED,
            raises_an_unreadable_error=ENDS_THE_RUN_MALFORMED,
            set=ENDS_THE_RUN_MALFORMED,
            not_a_number=ENDS_THE_RUN_MALFORMED,
            none=DROPPED_BEFORE_THE_BOUNDARY,
        ),
    ),
    # The step's own title still renders, so a step whose reasoning text is
    # missing leaves a delta on the wire rather than nothing.
    Boundary(
        "reasoning_step_field",
        _reasoning_step_field,
        "REASONING_MESSAGE_CONTENT",
        "handlers.on_reasoning_step",
        lambda: "scout is thinking",
        _terminates_except(
            circular=ENDS_THE_RUN_MALFORMED,
            raises_on_serialization=ENDS_THE_RUN_MALFORMED,
            raises_an_unreadable_error=ENDS_THE_RUN_MALFORMED,
            set=ENDS_THE_RUN_MALFORMED,
            not_a_number=ENDS_THE_RUN_MALFORMED,
        ),
    ),
    # These two dump the chunk behind a guard, so a dump that RAISES is caught.
    # A dump that succeeds is not filtered at all: both events declare their
    # payload as an untyped field, so a value inside the dump rides out on the
    # event and the protocol's encoder is where the stream then dies.
    Boundary(
        "custom_event_payload",
        _custom_event_payload,
        "CUSTOM",
        "handlers.on_custom_event",
        lambda: {"payload": "fine"},
        _terminates_except(
            circular=TERMINATES_UNSENDABLE,
            raises_on_serialization=TERMINATES_UNSENDABLE,
            raises_an_unreadable_error=TERMINATES_UNSENDABLE,
        ),
    ),
    Boundary(
        "raw_event_payload",
        _raw_event_payload,
        "RAW",
        "handlers.on_unknown_event",
        lambda: {"payload": "fine"},
        _terminates_except(
            circular=TERMINATES_UNSENDABLE,
            raises_on_serialization=TERMINATES_UNSENDABLE,
            raises_an_unreadable_error=TERMINATES_UNSENDABLE,
        ),
    ),
    # The message is read through the interface's guarded reader, so one that
    # cannot be rendered falls back to a fixed line and the terminal is still
    # written, spans closed. The terminal embeds the failing chunk verbatim
    # though, and the value rides out inside that dump, so the encoder refuses
    # the very event this boundary builds.
    Boundary(
        "run_error_message",
        _failing_run_with_a_member_mid_sentence,
        "RUN_ERROR",
        "handlers.on_run_error",
        lambda: "the team blew up",
        _terminates_except(
            raises_on_serialization=TERMINATES_UNSENDABLE,
            raises_an_unreadable_error=TERMINATES_UNSENDABLE,
        ),
    ),
    # The same content, read at the other boundary it reaches: closing the run
    # writes it as the terminal of every member lane still open. It is the same
    # guarded reading as the run's own message, so the lane terminates under the
    # fallback line and this event is sendable; the stream still dies at the run
    # terminal, which embeds the failing chunk verbatim.
    Boundary(
        "run_error_lane_message",
        _failing_run_with_a_member_mid_sentence,
        "SUBAGENT_ERROR",
        "handlers._lane_errored",
        lambda: "the team blew up",
        _terminates_except(
            raises_on_serialization=dies_on("RUN_ERROR"),
            raises_an_unreadable_error=dies_on("RUN_ERROR"),
        ),
        lineage_only=True,
        # The default builds no lane terminal, and the run's own terminal
        # embeds the same dump there too, so the stream dies at the same event.
        under_the_default={
            "raises_on_serialization": dies_on("RUN_ERROR"),
            "raises_an_unreadable_error": dies_on("RUN_ERROR"),
        },
    ),
    # The delta is a diff of the session state, which holds anything, and the
    # ops it carries are untyped, so the value reaches the encoder unfiltered.
    Boundary(
        "state_delta",
        _state_delta,
        "STATE_DELTA",
        "handlers._emit_state_delta",
        lambda: "approved",
        _terminates_except(
            circular=TERMINATES_UNSENDABLE,
            raises_on_serialization=TERMINATES_UNSENDABLE,
            raises_an_unreadable_error=TERMINATES_UNSENDABLE,
        ),
    ),
    # The four things a paused run puts on the wire out of its own content, one
    # row each rather than one fixture carrying the value into several of them:
    # the prompt is built in this order, so a fixture that injected the value
    # twice reported whichever boundary came first under the name of the later
    # one.
    Boundary(
        "pause_prompt_content",
        _pause_prompt_content,
        "TEXT_MESSAGE_CONTENT",
        "handlers._prompt_block",
        lambda: "confirm this before I send it",
        # Read through the interface's guarded reader, so the value that raises
        # from its own repr is dropped and the prompt sends no delta, which is
        # where the empty value stops too. The reader's own record names the
        # failure's type rather than rendering it, so the value whose failure
        # cannot be rendered either is dropped here as well rather than ending
        # the run from inside the recovery, several events before this terminal
        # writes anything.
        _terminates_except(
            raises_on_serialization=DROPPED_BEFORE_THE_BOUNDARY,
            raises_an_unreadable_error=DROPPED_BEFORE_THE_BOUNDARY,
            none=DROPPED_BEFORE_THE_BOUNDARY,
        ),
    ),
    # The protocol model requires a string name and a string id here as much as
    # it does on a streamed call, and nothing coerces either. The one difference
    # from the streamed rows is the empty value: a pending call missing either
    # is dropped, with a warning, before the prompt is built, so the client is
    # told the run is waiting with nothing on the wire to act on.
    Boundary(
        "pause_tool_name",
        _pause_tool_name,
        "TOOL_CALL_START",
        "handlers._prompt_block",
        lambda: "confirm",
        _everywhere(ENDS_THE_RUN) | {"none": DROPPED_BEFORE_THE_BOUNDARY},
    ),
    Boundary(
        "pause_tool_id",
        _pause_tool_id,
        "TOOL_CALL_START",
        "handlers._prompt_block",
        lambda: "tc-benign",
        _everywhere(ENDS_THE_RUN) | {"none": DROPPED_BEFORE_THE_BOUNDARY},
    ),
    Boundary(
        "pause_prompt_args",
        _pause_prompt_args,
        "TOOL_CALL_ARGS",
        "handlers._prompt_block",
        lambda: {"to": "ops"},
        # Serialized behind a guard, unlike the arguments of a streamed call:
        # this is the run terminal, and a raise here would discard the closing
        # sweep built before it. Arguments the encoder refuses are dropped, and
        # the call is still prompted under the id a resume answers it by.
        _everywhere(TERMINATES),
    ),
    # The protocol model requires a string name, and nothing coerces the value
    # or drops the call before the event is built.
    Boundary(
        "tool_call_name",
        _tool_call_name,
        "TOOL_CALL_START",
        "handlers.on_tool_call_started",
        lambda: "do_it",
        _everywhere(ENDS_THE_RUN),
    ),
    # The id the model gave the call: the protocol model requires a string there
    # too, and nothing coerces the value or drops the call before it is built.
    Boundary(
        "tool_call_id",
        _tool_call_id,
        "TOOL_CALL_START",
        "handlers.on_tool_call_started",
        lambda: "tc-benign",
        _everywhere(ENDS_THE_RUN),
    ),
    # The member's own identity, which the announcement's name is read off.
    # Every value is read through the same guarded stringification, so a name
    # that cannot be rendered leaves the lane announced under its run id and the
    # run finishes, announcement included. The one exception is nothing this
    # boundary built: the member's unmapped chunks are passed through as RAW,
    # whose payload is the chunk's own dump, so an identity object the encoder
    # refuses rides out on that event and the stream dies there.
    Boundary(
        "member_identity",
        _member_identity,
        "SUBAGENT_STARTED",
        "handlers._announce_subagent",
        lambda: "Scout",
        _terminates_except(
            raises_on_serialization=dies_on("RAW"),
            raises_an_unreadable_error=dies_on("RAW"),
        ),
        lineage_only=True,
        # The default announces no member, so nothing here builds an event at
        # all; the member's unmapped chunks still go out as RAW, and the
        # identity the encoder refuses rides out on one of those.
        under_the_default={
            "raises_on_serialization": dies_on("RAW"),
            "raises_an_unreadable_error": dies_on("RAW"),
        },
    ),
    # The three ways a member's own terminal reports what happened to it, each
    # read through the same guarded stringification the names are: a failure
    # that cannot be described leaves the lane errored with the interface's own
    # wording rather than ending a run that is still going.
    Boundary(
        "subagent_error_message",
        _subagent_error_message,
        "SUBAGENT_ERROR",
        "handlers._lane_errored",
        lambda: "member exploded",
        _everywhere(TERMINATES),
        lineage_only=True,
    ),
    Boundary(
        "subagent_cancellation_reason",
        _subagent_cancellation_reason,
        "SUBAGENT_ERROR",
        "handlers._lane_errored",
        lambda: "user cancelled the run",
        _everywhere(TERMINATES),
        lineage_only=True,
        # The default builds no lane terminal, and reads the member's
        # cancellation as the run's own: the RUN_ERROR it writes embeds the
        # cancelled chunk verbatim, reason included, so the reason the encoder
        # refuses truncates the stream at the run's own terminal.
        under_the_default={
            "raises_on_serialization": dies_on("RAW"),
            "raises_an_unreadable_error": dies_on("RAW"),
        },
    ),
    # The identifiers that failure is recorded with never reach the wire, so the
    # value is driven through the log line the terminal is accompanied by: one
    # that cannot be rendered used to end the run from inside the record of why
    # a lane had already closed.
    Boundary(
        "subagent_error_correlation",
        _subagent_error_correlation,
        "SUBAGENT_ERROR",
        "handlers._lane_errored",
        lambda: "second try",
        _everywhere(TERMINATES),
        lineage_only=True,
    ),
    # The identity a paused run names its member by, which the announcement the
    # pause prompt needs is built from.
    Boundary(
        "paused_member_name",
        _paused_member_name,
        "SUBAGENT_STARTED",
        "handlers._announce_paused_lanes",
        lambda: "Scout",
        _everywhere(TERMINATES),
        lineage_only=True,
    ),
)

# Named rather than counted, so a boundary cannot be swapped for a different one
# while the total stays the same.
_BOUNDARY_NAMES = (
    "member_terminal_result",
    "agent_text_delta",
    "team_text_delta",
    "team_member_response_delta",
    "tool_call_args",
    "tool_call_result",
    "reasoning_content_delta",
    "reasoning_step_payload",
    "reasoning_step_field",
    "custom_event_payload",
    "raw_event_payload",
    "run_error_message",
    "run_error_lane_message",
    "state_delta",
    "pause_prompt_content",
    "pause_tool_name",
    "pause_tool_id",
    "pause_prompt_args",
    "tool_call_name",
    "tool_call_id",
    "member_identity",
    "subagent_error_message",
    "subagent_cancellation_reason",
    "subagent_error_correlation",
    "paused_member_name",
)


# --- Collectors -------------------------------------------------------------

# Both collectors are the shared ones, so this module's streams are checked
# against exactly the same definition of a well-formed stream as every other
# suite's. They report the invariant a stream broke rather than failing on it,
# because a malformed stream is this module's subject.

Collect = Callable[..., Any]

mappers = pytest.mark.parametrize(
    "collect",
    [collect_sync_recording_violations, collect_async_recording_violations],
    ids=["sync", "async"],
)


async def _collect(collect: Collect, fixture: Fixture, visibility: Optional[str]) -> MalformedCollected:
    return await collect(
        fixture.chunks,
        visibility,
        thread_id=THREAD_ID,
        run_id=TOP_LEVEL_RUN,
        run_state=fixture.run_state,
    )


# A cell the table does not state arrives as None and is reported by the test
# body. Read at collection instead, a missing cell raises a bare KeyError from
# import, which takes the whole module down and leaves the completeness check
# below unable to say what is missing.
_CASES = [
    pytest.param(boundary, value, boundary.outcomes.get(value), id=f"{boundary.name}-{value}")
    for boundary in _BOUNDARIES
    for value in _ALL_VALUES
]


def _stated(boundary: Boundary, value: str, expected: Optional[str]) -> str:
    assert expected is not None, (
        f"the table states no outcome for a {value} value at the {boundary.name} boundary. "
        "Drive it, and add the cell saying what it does."
    )
    return expected


def _survival(events: List[BaseEvent], error: Optional[Exception], violation: Optional[str]) -> str:
    """Whether the run reached a terminal at all, and what it left behind if not."""
    if error is None:
        assert violation is None, f"a run that terminated left the stream malformed: {violation}"
        assert events, "a run that terminated emitted nothing at all"
        assert events[-1].type in _RUN_TERMINALS, f"a run that terminated ended on {events[-1].type}"
        return REACHES_ITS_TERMINAL
    # Nothing may follow a run terminal, so a failure must not have written one.
    assert not [event for event in events if event.type in _RUN_TERMINALS], (
        "the failure path wrote a run terminal of its own"
    )
    return ENDS_THE_RUN if violation is None else ENDS_THE_RUN_MALFORMED


def _verdict(
    events: List[BaseEvent],
    error: Optional[Exception],
    violation: Optional[str],
    boundary_event: "EventType",
) -> str:
    """What became of the value, including whether the boundary ran at all.

    Whether the boundary's own event reached the wire is decided before a
    refusal is attributed. Attributed the other way round, a stream carrying any
    unsendable event at all reports as unsendable even where this boundary never
    built anything, which is the one thing the verdict has to distinguish.

    The encoder is consulted either way. A boundary whose event never appeared
    says so, but the stream can still be one the client never sees the end of,
    and a cell that stopped at "dropped" reported such a run as one that reached
    the client. So a drop names the event the encoder refused too, when there
    was one.

    A refusal is attributed by event type: this boundary's own event if the
    encoder refused one of those, and otherwise the event it did refuse, named.
    A cell that says only "unsendable" credits this boundary with a failure some
    unrelated event on the same stream caused.
    """
    survival = _survival(events, error, violation)
    if survival != REACHES_ITS_TERMINAL:
        return survival
    refused = {refused_type for refused_type, _ in encoding_failures(events)}
    if not of_type(events, boundary_event):
        return dropped_and_dies_on(*refused) if refused else DROPPED_BEFORE_THE_BOUNDARY
    if not refused:
        return TERMINATES
    if short_type_name(boundary_event) in refused:
        return TERMINATES_UNSENDABLE
    return dies_on(*refused)


async def _assert_the_fixture_reaches_its_boundary(
    collect: Collect, boundary: Boundary, visibility: Optional[str], boundary_event: Optional["EventType"]
) -> None:
    """The same boundary with content it handles, so a verdict above is the value's.

    Without this the verdict cannot tell a failure the injected value caused
    from any other failure the run happened to hit, and a cell whose event never
    appears cannot be told from a fixture that never reached the boundary.
    """
    events, error, violation = await _collect(collect, boundary.builder(boundary.benign()), visibility)

    assert error is None, f"the {boundary.name} fixture fails on content the boundary handles: {error!r}"
    assert violation is None, f"the {boundary.name} fixture is malformed on benign content: {violation}"
    refused = encoding_failures(events)
    assert not refused, f"the {boundary.name} fixture writes an unsendable event on benign content: {refused}"
    if boundary_event is not None:
        assert_stream_contains(events, boundary_event)


def _outcome_without_a_boundary(events: List[BaseEvent], error: Optional[Exception], violation: Optional[str]) -> str:
    """What became of a run whose stream this boundary builds no event on.

    The encoder is consulted here too. A lineage-only boundary builds nothing
    under the default, but the member's own chunks still reach the wire, mapped
    or passed through as RAW, so a value the encoder refuses can still truncate
    the stream. Stopping at whether the run reached its terminal reported such a
    stream as one the client saw the end of.
    """
    survival = _survival(events, error, violation)
    if survival != REACHES_ITS_TERMINAL:
        return survival
    refused = {refused_type for refused_type, _ in encoding_failures(events)}
    return dies_on(*refused) if refused else REACHES_ITS_TERMINAL


def _default_outcome(boundary: Boundary, value: str, stated: str) -> str:
    """What the table says the default does where this boundary builds nothing.

    Derived from the attributed cell, since the two streams differ only by the
    member lifecycle, unless the row states otherwise: the member's own chunks
    are passed through as RAW here, which carries out a value that member
    attribution kept off the wire.
    """
    return boundary.under_the_default.get(value, REACHES_ITS_TERMINAL if _survives(stated) else stated)


def _boundary_event(boundary: Boundary, visibility: Optional[str]) -> Optional["EventType"]:
    """The event type this boundary builds, or None when this stream cannot carry it."""
    if boundary.lineage_only and visibility is None:
        return None
    return event_type_named(boundary.event)


@pytest.mark.asyncio
@mappers
@pytest.mark.parametrize("boundary,value,expected", _CASES)
async def test_hostile_run_content_through_an_event_boundary(collect, boundary, value, expected):
    stated = _stated(boundary, value, expected)
    visibility = attributed()
    boundary_event = _boundary_event(boundary, visibility)

    await _assert_the_fixture_reaches_its_boundary(collect, boundary, visibility, boundary_event)
    events, error, violation = await _collect(collect, boundary.builder(_HOSTILE[value]()), visibility)

    assert _verdict(events, error, violation, boundary_event) == stated, (
        f"the {boundary.name} boundary now does something else with a {value} value. "
        "Update the table in this module to say what, and say whether the change "
        "was intended."
    )


@pytest.mark.asyncio
@mappers
@pytest.mark.parametrize("boundary,value,expected", _CASES)
async def test_hostile_run_content_under_the_default_visibility(collect, boundary, value, expected):
    """The default visibility reaches the same verdict, cell for cell.

    The default stream differs from the attributed one only by the member
    lifecycle, so every boundary whose event is not one of those has to do
    exactly what it does above, verdict and all, rather than merely surviving
    where it survived. A lineage-only boundary builds nothing here, which is
    what the two assertions about member events below say.
    """
    stated = _stated(boundary, value, expected)
    boundary_event = _boundary_event(boundary, None)

    await _assert_the_fixture_reaches_its_boundary(collect, boundary, None, boundary_event)
    events, error, violation = await _collect(collect, boundary.builder(_HOSTILE[value]()), None)

    if boundary_event is None:
        assert _outcome_without_a_boundary(events, error, violation) == _default_outcome(boundary, value, stated), (
            f"the {boundary.name} fixture does something else with a {value} value under the default "
            "visibility, where this boundary builds no event of its own"
        )
    else:
        assert _verdict(events, error, violation, boundary_event) == stated, (
            f"the {boundary.name} boundary does something else with a {value} value under the default "
            "visibility than it does under member attribution"
        )
    assert not [event for event in events if "SUBAGENT" in str(event.type)]
    assert not [event for event in events if lane_of(event) is not None]


@pytest.mark.asyncio
@mappers
@pytest.mark.parametrize("value", list(_HOSTILE), ids=list(_HOSTILE))
async def test_hostile_session_state_still_reaches_the_state_snapshot(collect, value):
    """STATE_SNAPSHOT is built by deep-copying the run's state, which holds anything."""
    injected = _HOSTILE[value]()
    fixture = Fixture(
        [
            TeamRunStartedEvent(**_TOP_LEVEL),
            RunStartedEvent(**_MEMBER),
            RunCompletedEvent(content="scout done", **_MEMBER),
            TeamRunCompletedEvent(**_TOP_LEVEL),
        ],
        run_state={"value": injected},
    )
    # Three of these snapshots are ones the protocol's encoder refuses, so the
    # run terminates in memory while the client's stream stops at the snapshot.
    unsendable = value in ("circular", "raises_on_serialization", "raises_an_unreadable_error")

    events, error, violation = await _collect(collect, fixture, attributed())

    assert _verdict(events, error, violation, EventType.STATE_SNAPSHOT) == (
        TERMINATES_UNSENDABLE if unsendable else TERMINATES
    )
    snapshots = of_type(events, EventType.STATE_SNAPSHOT)
    assert len(snapshots) == 1
    snapshot = snapshots[0].snapshot  # type: ignore[attr-defined]
    # Compared by type, never by value: one of these values raises from its own
    # repr, which an equality failure would try to render.
    assert "value" in snapshot, "the hostile value never reached the snapshot"
    assert type(snapshot["value"]) is type(injected), "the snapshot holds something other than the injected value"


# --- The recovery path a run terminal is built inside ------------------------

# The table above says what became of a value at each boundary. These two say
# what a client is actually handed when the value is one the interface's guarded
# reader cannot read, at the two run terminals that reader is called from: a
# record written by rendering the failure runs the same value the read did, so
# the guard raises out of its own recovery and takes the terminal being built
# around it with it. A cell of the table would report that as "ends the run",
# which is true of any raise; these name what a client loses instead.


def _as_a_client_receives(events: List[BaseEvent]) -> List[Dict[str, Any]]:
    """Every event read back off the bytes the protocol's encoder puts on a wire.

    Read off the encoding rather than off the mapped objects. The events built
    before a raise exist in memory whatever happens after it, so a list of
    mapped objects cannot say where a client's stream stopped, and the symptom
    here is a stream that stops before its terminal.
    """
    encoder = EventEncoder()
    received: List[Dict[str, Any]] = []
    for event in events:
        encoded = encoder.encode(event)
        prefix, _, payload = encoded.partition("data: ")
        assert not prefix and payload, f"the encoder no longer writes one data frame per event: {encoded!r}"
        received.append(json.loads(payload))
    return received


@pytest.mark.asyncio
@mappers
async def test_a_pause_whose_own_words_cannot_be_read_still_prompts_the_client(collect, caplog):
    """A pause that says something unreadable still asks its question and terminates.

    The words are read through the guarded reader, at the run terminal. A raise
    out of the reader's recovery discards the prompt, the call the client is
    meant to answer and the terminal itself, leaving a run that was merely
    waiting for an answer to end as a failure over its prose.
    """
    with captured_agno_logs(caplog, "WARNING"):
        events, error, violation = await _collect(
            collect, _pause_prompt_content(RaisesAnUnreadableError()), attributed()
        )

    assert error is None, f"reading the paused run's own words ended the run: {error!r}"
    assert violation is None, f"the pause left the stream malformed: {violation}"

    received = _as_a_client_receives(events)
    assert [event["type"] for event in received] == [
        "RAW",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_END",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "RUN_FINISHED",
    ], "the pause prompt a client receives is not the whole prompt"
    # The words are the one thing dropped: the call is still advertised under
    # the id a resume answers it by, which is what the pause is for.
    assert [event["toolCallId"] for event in received if event["type"] == "TOOL_CALL_START"] == ["tc-hostile-confirm"]
    assert "AG-UI could not read a paused run's own words: UnrenderableError" in [
        record.getMessage() for record in caplog.records
    ], "nothing records the words the client was not sent"


@pytest.mark.asyncio
@mappers
async def test_a_failure_whose_own_message_cannot_be_read_still_terminates_the_run(collect, caplog):
    """A run that fails unreadably still reports a failure and closes what it opened.

    The message is read through the same reader, before the terminal's cleanup
    runs, and is also what every member lane still open terminates under. A
    raise out of the reader's recovery here closes no span, terminates no lane
    and writes no terminal: the client is left mid-sentence, and the run's real
    failure is replaced by the one raised while naming it.
    """
    failure = TeamRunErrorEvent(error_type="RuntimeError", **_TOP_LEVEL)
    failure.content = RaisesAnUnreadableError()
    # Dumped as a payload that holds none of the value, so the terminal carrying
    # this dump is one the encoder accepts and the test is about the message
    # rather than about the verbatim chunk beside it.
    failure.to_dict = lambda: {"event": "TeamRunError"}  # type: ignore[method-assign]
    fixture = Fixture(
        [
            TeamRunStartedEvent(**_TOP_LEVEL),
            RunStartedEvent(**_MEMBER),
            agent_said("half a sen", **_MEMBER),
            failure,
        ]
    )

    with captured_agno_logs(caplog, "WARNING"):
        events, error, violation = await _collect(collect, fixture, attributed())

    assert error is None, f"reading the failed run's own message ended the run: {error!r}"
    assert violation is None, f"the failed terminal left the stream malformed: {violation}"

    received = _as_a_client_receives(events)
    assert [event["type"] for event in received] == [
        "RAW",
        "SUBAGENT_STARTED",
        "RAW",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "SUBAGENT_ERROR",
        "RUN_ERROR",
    ], "the failed run a client receives is not the whole terminal"
    assert received[-1]["message"] == "Run failed"
    assert received[-1]["code"] == "RuntimeError"
    assert "AG-UI could not read a failed run message: UnrenderableError" in [
        record.getMessage() for record in caplog.records
    ], "nothing records the failure text the client was not sent"


# --- The router's own terminal ----------------------------------------------


class _StubEntity:
    """An entity whose run is the chunk list, so the router's own mapping is driven.

    The router hands whatever the entity's ``arun`` returns to the async mapper.
    Nothing else about an Agent or a Team is read on this path, so a stub is what
    keeps the test about the terminal the router writes.
    """

    def __init__(self, chunks: List[Any]) -> None:
        self._chunks = chunks

    def arun(self, **_: Any) -> Any:
        chunks = self._chunks

        async def source() -> Any:
            for chunk in chunks:
                yield chunk

        return source()


def _run_input() -> "RunAgentInput":
    return RunAgentInput(
        thread_id=THREAD_ID,
        run_id=TOP_LEVEL_RUN,
        state={},
        messages=[UserMessage(id="message-1", role="user", content="go")],
        tools=[],
        context=[],
        forwarded_props={},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("value", list(_HOSTILE), ids=list(_HOSTILE))
async def test_the_router_terminal_reports_a_stream_the_hostile_value_ended(value):
    """The RUN_ERROR the router writes when the mapper raises on run content.

    This is the one event the interface builds that no boundary row can reach:
    the mapper raising is what produces it, so the row for the boundary that
    raised has already ended before the router writes anything. Driven with
    every hostile value through the boundary that ends the run on one of them,
    so the cells that do not end it pin that the router writes no terminal of
    its own instead.
    """
    injected = _HOSTILE[value]()
    chunks = [
        TeamRunStartedEvent(**_TOP_LEVEL),
        RunStartedEvent(**_MEMBER),
        agent_said(injected, **_MEMBER),
        RunCompletedEvent(content="scout done", **_MEMBER),
        TeamRunCompletedEvent(**_TOP_LEVEL),
    ]

    events: List[BaseEvent] = []
    async for event in run_entity(_StubEntity(chunks), _run_input()):  # type: ignore[arg-type]
        events.append(event)

    assert not encoding_failures(events), "the router wrote an event the protocol's own encoder refuses"
    errors = of_type(events, EventType.RUN_ERROR)
    if value != "circular":
        # Every other value is swallowed by the text extractor, so the mapper
        # never raises and the router's terminal is the run's own completion.
        assert not errors
        assert events[-1].type == EventType.RUN_FINISHED
        return
    # The mapper raises on a cycle, so the router turns the propagated failure
    # into the run's terminal. The message is the failure's own text, and the
    # run terminal is the last thing on the wire.
    assert [error.message for error in errors] == ["Circular reference detected"]  # type: ignore[attr-defined]
    assert events[-1].type == EventType.RUN_ERROR
    assert not of_type(events, EventType.RUN_FINISHED), "the router wrote two run terminals"


# --- What the whole table is checked against --------------------------------


def _because(reason: str, *pairs: Tuple[str, str]) -> Dict[Tuple[str, str], str]:
    """One justification, against each function-and-event pair it accounts for."""
    return {pair: reason for pair in pairs}


def _one_justification_each(*groups: Dict[Tuple[str, str], str]) -> Dict[Tuple[str, str], str]:
    """Merge the justifications, refusing to let one pair be justified twice.

    A pair justified in two groups would have one of them silently discarded,
    leaving a reason in this module that accounts for nothing.
    """
    merged: Dict[Tuple[str, str], str] = {}
    for group in groups:
        clashing = sorted(set(group) & set(merged))
        assert not clashing, f"these pairs are justified more than once: {clashing}"
        merged.update(group)
    return merged


# Every event the interface builds without reading anything a run produced,
# named as a function-and-event pair rather than as a bare function: a function
# that builds six events out of one of them is driven for that one and unchecked
# for the other five, which is how two events of the pause path went undriven
# while this module stayed green. Each pair is justified here and nowhere else.
_BUILDS_NOTHING_OUT_OF_RUN_CONTENT: Dict[Tuple[str, str], str] = _one_justification_each(
    _because(
        "closes a span by an id this interface minted when it opened it",
        ("handlers._end_lane_text_message", "TEXT_MESSAGE_END"),
        ("handlers._end_lane_reasoning", "REASONING_MESSAGE_END"),
        ("handlers._end_lane_reasoning", "REASONING_END"),
        ("handlers.on_reasoning_completed", "REASONING_MESSAGE_END"),
        ("handlers.on_reasoning_completed", "REASONING_END"),
        ("handlers.on_reasoning_started", "TEXT_MESSAGE_END"),
        ("handlers.on_reasoning_content_delta", "TEXT_MESSAGE_END"),
        ("handlers.on_reasoning_step", "TEXT_MESSAGE_END"),
        ("handlers.on_tool_call_started", "TEXT_MESSAGE_END"),
        ("handlers._prompt_block", "TEXT_MESSAGE_END"),
    ),
    _because(
        "opens a span, carrying an id this interface minted and a role, and none of what the run said",
        ("handlers.on_run_content", "TEXT_MESSAGE_START"),
        ("handlers.on_tool_call_started", "TEXT_MESSAGE_START"),
        ("handlers.on_reasoning_started", "REASONING_START"),
        ("handlers.on_reasoning_started", "REASONING_MESSAGE_START"),
        ("handlers.on_reasoning_content_delta", "REASONING_START"),
        ("handlers.on_reasoning_content_delta", "REASONING_MESSAGE_START"),
        ("handlers.on_reasoning_step", "REASONING_START"),
        ("handlers.on_reasoning_step", "REASONING_MESSAGE_START"),
        ("handlers._prompt_block", "TEXT_MESSAGE_START"),
    ),
    _because(
        "closes a tool call by an id the client already has a start for, which the tool_call_id and "
        "pause_tool_id boundaries are where the run's own value first reaches the wire",
        ("handlers._end_lane_tool_calls", "TOOL_CALL_END"),
        ("handlers.on_tool_call_completed", "TOOL_CALL_END"),
        ("handlers._prompt_block", "TOOL_CALL_END"),
    ),
    _because(
        "writes the run's own terminal, carrying the thread and run ids the request named and nothing "
        "the response stream produced",
        ("handlers._run_end_events", "RUN_FINISHED"),
    ),
    _because(
        "writes the run's opening and the request's own state, neither of which comes out of the "
        "response stream this module drives",
        ("router.run_entity", "RUN_STARTED"),
        ("router.run_entity", "STATE_SNAPSHOT"),
    ),
)

# Pairs no row drives because a test of this module's own drives them instead,
# each naming that test. A pair here is covered, not excused.
_COVERED_BY_ANOTHER_TEST: Dict[Tuple[str, str], str] = {
    # The snapshot is built out of the run's session state, which is content,
    # but by a route no chunk of the stream carries.
    ("handlers._run_end_events", "STATE_SNAPSHOT"): "test_hostile_session_state_still_reaches_the_state_snapshot",
    # The router's own terminal, built from the stringified failure the mapper
    # raised rather than from a chunk, so it is reached by driving a run that
    # ends the run rather than by a row of the table.
    ("router.run_entity", "RUN_ERROR"): "test_the_router_terminal_reports_a_stream_the_hostile_value_ended",
}


def _the_protocol_defines(event_name: str) -> bool:
    """Whether the installed ag_ui.core has an event type of this name.

    The lineage events arrived after this package's minimum protocol release. On
    a release without them the interface imports their constructions inside a
    guarded import that fails, so the source scan finds none of them and every
    pair naming one is a pair the scan cannot report. Read off the protocol
    rather than off a skip marker, so any future event the interface builds
    behind a version guard is accounted the same way, and so this module holds
    on both releases instead of failing on one where its siblings skip.
    """
    return getattr(EventType, event_name, None) is not None


def _servable(pairs: Dict[Tuple[str, str], Any]) -> Set[Tuple[str, str]]:
    return {pair for pair in pairs if _the_protocol_defines(pair[1])}


def _claimed_pairs() -> Set[Tuple[str, str]]:
    """The (function, event) pair every row of the table claims, on this install."""
    return _servable({(boundary.builds, boundary.event): None for boundary in _BOUNDARIES})


def _built_pairs() -> Set[Tuple[str, str]]:
    return {(function, event) for function, events in event_constructions_by_function().items() for event in events}


def test_every_hostile_value_is_driven_through_every_boundary():
    """The table is complete: every boundary, every value, one stated outcome.

    Checked against the value names this module was written against, which are
    independent of the shared list the sweep is built from: comparing that list
    with itself holds whatever it says. So a value added to it fails here until
    every row states an outcome for it, a row cannot quietly stop being driven
    with one, and an outcome cannot be stated for a value that no longer exists.
    """
    assert _ALL_VALUES == _HOSTILE_VALUE_NAMES, (
        f"the shared hostile values are now {list(_ALL_VALUES)}, and this table is written against "
        f"{list(_HOSTILE_VALUE_NAMES)}: state an outcome per boundary for whatever changed"
    )
    for boundary in _BOUNDARIES:
        assert set(boundary.outcomes) == set(_ALL_VALUES), (
            f"the {boundary.name} boundary states outcomes for {sorted(boundary.outcomes)}, not {sorted(_ALL_VALUES)}"
        )
        undefined = sorted(outcome for outcome in boundary.outcomes.values() if not _is_a_verdict(outcome))
        assert not undefined, f"the {boundary.name} boundary states an outcome this module does not define: {undefined}"
        assert boundary.lineage_only or not boundary.under_the_default, (
            f"the {boundary.name} boundary builds its own event under the default, so the cell above already "
            "states what happens there and a second statement can disagree with it"
        )
        unknown = sorted(set(boundary.under_the_default) - set(_ALL_VALUES))
        assert not unknown, f"the {boundary.name} boundary states a default outcome for {unknown}, which is no value"
        undefined = sorted(
            outcome
            for outcome in boundary.under_the_default.values()
            if outcome != REACHES_ITS_TERMINAL and not _is_a_verdict(outcome)
        )
        assert not undefined, (
            f"the {boundary.name} boundary states a default outcome this module does not define: {undefined}"
        )
    assert tuple(boundary.name for boundary in _BOUNDARIES) == _BOUNDARY_NAMES, (
        "the boundaries in the table are no longer the ones it is written against"
    )
    assert len(_CASES) == len(_BOUNDARY_NAMES) * len(_HOSTILE), (
        "some boundary is no longer driven with every hostile value"
    )


def test_the_table_names_every_event_the_interface_builds_one_of():
    """The boundary list, recomputed from the interface's own source.

    The table's claim is that it covers every place an AG-UI event is built out
    of run content. Nothing recomputed that, so a new event-building function
    could ship uncovered while every cell here stayed green.

    Accounted per function AND event, not per function: a function that builds
    six event types is driven for the one a row names and unchecked for the
    other five. So each event each scope of the package constructs has to be
    claimed by a row, covered by a named test, or justified above as built out
    of no run content.

    An event type the installed protocol does not define is left out of the
    comparison on both sides. The interface builds those behind a guarded
    import, so on such a release the source scan reports none of them and the
    rows naming them have nothing to be checked against, which used to fail this
    one test where every sibling skipped.
    """
    built = _built_pairs()
    claimed = _claimed_pairs()
    excused = _servable(_BUILDS_NOTHING_OUT_OF_RUN_CONTENT)
    covered = _servable(_COVERED_BY_ANOTHER_TEST)

    overlapping = sorted(claimed & (excused | covered))
    assert not overlapping, f"a boundary claims what this module also accounts for another way: {overlapping}"
    doubly_accounted = sorted(excused & covered)
    assert not doubly_accounted, f"these pairs are both excused and covered by a test: {doubly_accounted}"

    unclaimed = sorted(built - (claimed | excused | covered))
    assert not unclaimed, (
        f"the interface builds these events and no row of this table drives them: {unclaimed}. "
        "Drive each one with every hostile value and add its row, or justify it above."
    )
    imaginary = sorted((claimed | excused | covered) - built)
    assert not imaginary, f"the interface builds none of these any more: {imaginary}"

    # A pair is only covered if the test it names is really in this module: a
    # renamed or deleted test would otherwise leave the pair accounted for by a
    # string.
    absent = sorted(name for name in _COVERED_BY_ANOTHER_TEST.values() if name not in globals())
    assert not absent, f"these pairs name a test this module does not define: {absent}"
