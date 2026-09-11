"""Negative controls for the shared definition of a well-formed AG-UI stream.

``agui_stream_invariants`` is what every AG-UI suite's collectors assert their
streams against, so an invariant that has stopped biting takes the whole set
down with it silently: every suite keeps passing, and nothing says the promise
went unchecked. A reviewer demonstrated exactly that by deleting six of the
individual checks with the suites still green.

Each invariant therefore gets a stream here that breaks it and nothing else,
built as a plain list of protocol events rather than by driving the interface,
so a control cannot drift into agreeing with whatever the interface does today.
The table below is keyed by the invariant each case is for, and one test asserts
that every invariant the checker names is in it.

An invariant reads its event types out of a table, so a case per invariant is
not enough on its own: a row deleted from ``_SPAN_FAMILIES``, ``_CONTENT_IN_SPAN``,
``_ANNOUNCEMENT_PARENT_LINKS``, the run terminal types, the run-level types, the
member terminal types or the state types leaves the invariant biting on every
other row and silently blind to that one. Every row therefore has a case whose
reported violation can only come from that row.
"""

import logging
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple, cast

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

import ag_ui.core
from ag_ui.core import (
    BaseEvent,
    EventType,
    ReasoningEndEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from .agui_stream_invariants import (
    A_CHILDS_TERMINAL_PRECEDES_ITS_PARENTS,
    A_SPAN_CLOSES_IN_THE_MEMBER_IT_OPENED_IN,
    A_TOOL_CALL_SITS_IN_ITS_PARENT_MESSAGES_MEMBER,
    A_TOOL_RESULT_CARRIES_ITS_CALLS_MEMBER,
    ABANDONED_MID_STREAM,
    ABANDONED_WITH_A_MEMBER_STILL_OPEN,
    AGNO_LOGGER_NAMES,
    AN_ANNOUNCED_PARENT_PRECEDES_ITS_CHILD,
    ATTRIBUTED_IS_SERVABLE,
    CONTENT_CARRIES_ITS_SPANS_MEMBER,
    CONTENT_LANDS_INSIDE_ITS_SPAN,
    EVERY_ANNOUNCED_MEMBER_TERMINATES,
    EVERY_ANNOUNCED_PARENT_IS_ANNOUNCED_TOO,
    EVERY_ANNOUNCED_PARENT_LINK_RESOLVES,
    EVERY_SPAN_CLOSES,
    EVERY_STAMP_NAMES_AN_ANNOUNCED_MEMBER,
    EVERY_TOOL_CALL_PARENT_MESSAGE_WAS_OPENED,
    EVERY_TOOL_RESULT_FOLLOWS_ITS_CALLS_END,
    EVERY_TOOL_RESULT_NAMES_A_STARTED_CALL,
    EXEMPTIONS,
    INVARIANTS,
    LINEAGE_ANNOUNCEMENT_FIELDS_READ_HERE,
    LINEAGE_EVENTS_PROTOCOL_FLOOR,
    NO_MEMBER_IS_ANNOUNCED_TWICE,
    NO_SPAN_CLOSES_BEFORE_IT_OPENS,
    NO_SPAN_CLOSES_TWICE,
    NO_SPAN_CLOSES_UNOPENED,
    NO_SPAN_OPENS_TWICE,
    NOTHING_CARRIES_A_MEMBER_AFTER_ITS_TERMINAL,
    ONE_RUN_TERMINAL_AND_NOTHING_AFTER_IT,
    RUN_EVENTS_ARE_NEVER_STAMPED,
    STATE_EVENTS_ARE_NEVER_STAMPED,
    TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL,
    announced_lane,
    announcement_fields_missing_from,
    assert_stream_carries_exactly,
    assert_stream_contains,
    assert_well_formed_stream,
    captured_agno_logs,
    circular,
    encoding_failures,
    event_type_named,
    exemption_waives,
    field_of,
    in_emitted_order,
    installed_protocol_release,
    lineage_announcement_fields_missing,
    require_lineage_events,
    stream_invariant_violation,
)

THREAD_ID = "invariant-session"
RUN_ID = "invariant-run"


# --- Building one event at a time -------------------------------------------


def _stamped(event: BaseEvent, lane: Optional[str]) -> BaseEvent:
    """One event carrying a member lane, set directly rather than by the interface.

    The protocol models accept extra attributes, so this reaches even an event
    type the interface refuses to attribute, which is what the state-event
    control needs.
    """
    if lane is not None:
        setattr(event, "subagent_run_id", lane)
    return event


def _text_start(message_id: str, lane: Optional[str] = None) -> BaseEvent:
    return _stamped(
        TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=message_id, role="assistant"), lane
    )


def _text_content(message_id: str, delta: str = "hello", lane: Optional[str] = None) -> BaseEvent:
    return _stamped(
        TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=message_id, delta=delta), lane
    )


def _text_end(message_id: str, lane: Optional[str] = None) -> BaseEvent:
    return _stamped(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id), lane)


def _tool_start(tool_call_id: str, lane: Optional[str] = None, parent_message_id: Optional[str] = None) -> BaseEvent:
    return _stamped(
        ToolCallStartEvent(
            type=EventType.TOOL_CALL_START,
            tool_call_id=tool_call_id,
            tool_call_name="do_it",
            parent_message_id=parent_message_id,
        ),
        lane,
    )


def _tool_args(tool_call_id: str, delta: str = "{}", lane: Optional[str] = None) -> BaseEvent:
    return _stamped(ToolCallArgsEvent(type=EventType.TOOL_CALL_ARGS, tool_call_id=tool_call_id, delta=delta), lane)


def _tool_end(tool_call_id: str, lane: Optional[str] = None) -> BaseEvent:
    return _stamped(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id), lane)


def _tool_result(tool_call_id: str, lane: Optional[str] = None) -> BaseEvent:
    return _stamped(
        ToolCallResultEvent(
            type=EventType.TOOL_CALL_RESULT,
            tool_call_id=tool_call_id,
            message_id=tool_call_id,
            content="done",
            role="tool",
        ),
        lane,
    )


def _reasoning_start(message_id: str, lane: Optional[str] = None) -> BaseEvent:
    return _stamped(ReasoningStartEvent(type=EventType.REASONING_START, message_id=message_id), lane)


def _reasoning_end(message_id: str, lane: Optional[str] = None) -> BaseEvent:
    return _stamped(ReasoningEndEvent(type=EventType.REASONING_END, message_id=message_id), lane)


def _reasoning_message_start(message_id: str, lane: Optional[str] = None) -> BaseEvent:
    return _stamped(
        ReasoningMessageStartEvent(type=EventType.REASONING_MESSAGE_START, message_id=message_id, role="reasoning"),
        lane,
    )


def _reasoning_message_content(message_id: str, delta: str = "thinking", lane: Optional[str] = None) -> BaseEvent:
    return _stamped(
        ReasoningMessageContentEvent(type=EventType.REASONING_MESSAGE_CONTENT, message_id=message_id, delta=delta),
        lane,
    )


def _reasoning_message_end(message_id: str, lane: Optional[str] = None) -> BaseEvent:
    return _stamped(ReasoningMessageEndEvent(type=EventType.REASONING_MESSAGE_END, message_id=message_id), lane)


def _state_delta(lane: Optional[str] = None) -> BaseEvent:
    return _stamped(
        StateDeltaEvent(type=EventType.STATE_DELTA, delta=[{"op": "replace", "path": "/approved", "value": True}]),
        lane,
    )


def _state_snapshot(lane: Optional[str] = None) -> BaseEvent:
    return _stamped(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot={"approved": True}), lane)


def _run_started(lane: Optional[str] = None) -> BaseEvent:
    return _stamped(RunStartedEvent(type=EventType.RUN_STARTED, thread_id=THREAD_ID, run_id=RUN_ID), lane)


def _run_finished(lane: Optional[str] = None) -> BaseEvent:
    return _stamped(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=THREAD_ID, run_id=RUN_ID), lane)


def _run_error(lane: Optional[str] = None) -> BaseEvent:
    return _stamped(RunErrorEvent(type=EventType.RUN_ERROR, message="the run failed"), lane)


def _lineage_event(class_name: str, **fields: Any) -> BaseEvent:
    """One SUBAGENT_* event, skipping on a release that defines none.

    The class is reached by name off the installed module and its event type
    off the class itself. Naming ``EventType.SUBAGENT_*`` in a caller would not
    do: the argument is evaluated before this function is entered, so the skip
    below never runs and the case fails instead on a release the packaged extra
    still permits.
    """
    require_lineage_events()
    event_class = getattr(ag_ui.core, class_name)
    return event_class(**fields)


def _announced(
    lane: str,
    parent: Optional[str] = None,
    parent_tool_call_id: Optional[str] = None,
    parent_message_id: Optional[str] = None,
) -> BaseEvent:
    return _lineage_event(
        "SubagentStartedEvent",
        subagent_run_id=lane,
        name=lane.capitalize(),
        parent_subagent_run_id=parent,
        parent_tool_call_id=parent_tool_call_id,
        parent_message_id=parent_message_id,
    )


def _member_finished(lane: str) -> BaseEvent:
    return _lineage_event("SubagentFinishedEvent", subagent_run_id=lane)


def _member_errored(lane: str) -> BaseEvent:
    return _lineage_event("SubagentErrorEvent", subagent_run_id=lane, message="the member failed")


# --- One stream per invariant ------------------------------------------------


class Control(NamedTuple):
    """One stream that breaks exactly one invariant, and how it is reported."""

    invariant: str
    case: str
    # Built when the case runs, so a member case skips rather than failing on a
    # protocol release without the lineage events.
    build: Callable[[], List[BaseEvent]]
    # Part of what the checker says. Enough to tell this violation from every
    # other one the same stream could plausibly break.
    reported: str


_CONTROLS: Tuple[Control, ...] = (
    # Each of these opens twice and closes once, so the second open is the only
    # thing wrong with the stream: opening and closing twice would break the
    # duplicate-close promise below as well.
    Control(
        NO_SPAN_OPENS_TWICE,
        "one message id opened twice",
        lambda: [_text_start("m-1"), _text_start("m-1"), _text_end("m-1"), _run_finished()],
        "text message ids opened more than once: ['m-1']",
    ),
    Control(
        NO_SPAN_OPENS_TWICE,
        "one tool call id opened twice",
        lambda: [_tool_start("tc-1"), _tool_start("tc-1"), _tool_end("tc-1"), _run_finished()],
        "tool call ids opened more than once: ['tc-1']",
    ),
    Control(
        NO_SPAN_OPENS_TWICE,
        "one reasoning span opened twice",
        lambda: [
            _reasoning_start("r-1"),
            _reasoning_start("r-1"),
            _reasoning_end("r-1"),
            _run_finished(),
        ],
        "reasoning ids opened more than once: ['r-1']",
    ),
    Control(
        NO_SPAN_CLOSES_TWICE,
        "one message closed twice",
        # A second end for an id the stream did open. Counting the closes
        # against the opens nets this to zero and reports nothing, and reporting
        # the leftover close as a span that never opened names the wrong fault.
        lambda: [_text_start("m-1"), _text_end("m-1"), _text_end("m-1"), _run_finished()],
        "text message ids closed more than once: ['m-1']",
    ),
    Control(
        NO_SPAN_CLOSES_UNOPENED,
        "a message closed that never opened",
        lambda: [_text_end("m-ghost"), _run_finished()],
        "text message ids closed without ever being opened: ['m-ghost']",
    ),
    Control(
        EVERY_SPAN_CLOSES,
        "a tool call left open at the run terminal",
        lambda: [_text_start("m-1"), _text_content("m-1"), _text_end("m-1"), _tool_start("tc-1"), _run_finished()],
        "tool call ids opened and never closed: ['tc-1']",
    ),
    Control(
        NO_SPAN_CLOSES_BEFORE_IT_OPENS,
        "a reasoning message closed before it opened",
        lambda: [
            _reasoning_message_end("r-1"),
            _reasoning_message_start("r-1"),
            _run_finished(),
        ],
        "reasoning message r-1 was closed before it opened",
    ),
    Control(
        CONTENT_LANDS_INSIDE_ITS_SPAN,
        "a delta after its message ended",
        lambda: [_text_start("m-1"), _text_end("m-1"), _text_content("m-1"), _run_finished()],
        "text message content at index 2 names m-1, whose TEXT_MESSAGE_END already went out",
    ),
    Control(
        CONTENT_LANDS_INSIDE_ITS_SPAN,
        "tool arguments for a call that never started",
        lambda: [_tool_args("tc-ghost"), _run_finished()],
        "tool call arguments at index 0 names tc-ghost, which no earlier TOOL_CALL_START opened",
    ),
    Control(
        CONTENT_LANDS_INSIDE_ITS_SPAN,
        "a reasoning delta after its reasoning message ended",
        lambda: [
            _reasoning_message_start("r-1"),
            _reasoning_message_end("r-1"),
            _reasoning_message_content("r-1"),
            _run_finished(),
        ],
        "reasoning content at index 2 names r-1, whose REASONING_MESSAGE_END already went out",
    ),
    Control(
        CONTENT_CARRIES_ITS_SPANS_MEMBER,
        "one member's delta inside another member's message",
        lambda: [
            _announced("run-alpha"),
            _announced("run-beta"),
            _text_start("m-1", lane="run-alpha"),
            _text_content("m-1", lane="run-beta"),
            _text_end("m-1", lane="run-alpha"),
            _member_finished("run-alpha"),
            _member_finished("run-beta"),
            _run_finished(),
        ],
        "text message content for m-1 is stamped with member run-beta, while the "
        "TEXT_MESSAGE_START that opened it named run-alpha",
    ),
    Control(
        A_SPAN_CLOSES_IN_THE_MEMBER_IT_OPENED_IN,
        "one member's message closed in another member",
        lambda: [
            _announced("run-alpha"),
            _announced("run-beta"),
            _text_start("m-1", lane="run-alpha"),
            _text_end("m-1", lane="run-beta"),
            _member_finished("run-alpha"),
            _member_finished("run-beta"),
            _run_finished(),
        ],
        "the TEXT_MESSAGE_END for text message m-1 is stamped with member run-beta, while the "
        "TEXT_MESSAGE_START that opened it named run-alpha",
    ),
    Control(
        A_SPAN_CLOSES_IN_THE_MEMBER_IT_OPENED_IN,
        "a member's tool call closed with no member at all",
        lambda: [
            _announced("run-alpha"),
            _tool_start("tc-1", lane="run-alpha"),
            _tool_end("tc-1"),
            _member_finished("run-alpha"),
            _run_finished(),
        ],
        "the TOOL_CALL_END for tool call tc-1 is stamped with member None, while the "
        "TOOL_CALL_START that opened it named run-alpha",
    ),
    Control(
        EVERY_TOOL_CALL_PARENT_MESSAGE_WAS_OPENED,
        "a tool call hung off a message this stream never opened",
        lambda: [_tool_start("tc-1", parent_message_id="m-ghost"), _tool_end("tc-1"), _run_finished()],
        "tool call tc-1 names parent message m-ghost, which no TEXT_MESSAGE_START in this stream opened",
    ),
    Control(
        A_TOOL_CALL_SITS_IN_ITS_PARENT_MESSAGES_MEMBER,
        "a member's tool call hung off a message attributed to nobody",
        lambda: [
            _announced("run-alpha"),
            _text_start("m-1"),
            _text_end("m-1"),
            _tool_start("tc-1", lane="run-alpha", parent_message_id="m-1"),
            _tool_end("tc-1", lane="run-alpha"),
            _member_finished("run-alpha"),
            _run_finished(),
        ],
        "tool call tc-1 is stamped with member run-alpha, while the message m-1 it names as its "
        "parent was opened in member None",
    ),
    Control(
        A_TOOL_CALL_SITS_IN_ITS_PARENT_MESSAGES_MEMBER,
        "an unattributed tool call hung off a member's message",
        lambda: [
            _announced("run-alpha"),
            _text_start("m-1", lane="run-alpha"),
            _text_end("m-1", lane="run-alpha"),
            _tool_start("tc-1", parent_message_id="m-1"),
            _tool_end("tc-1"),
            _member_finished("run-alpha"),
            _run_finished(),
        ],
        "tool call tc-1 is stamped with member None, while the message m-1 it names as its "
        "parent was opened in member run-alpha",
    ),
    Control(
        A_TOOL_CALL_SITS_IN_ITS_PARENT_MESSAGES_MEMBER,
        "one member's tool call hung off another member's message",
        lambda: [
            _announced("run-alpha"),
            _announced("run-beta"),
            _text_start("m-1", lane="run-alpha"),
            _text_end("m-1", lane="run-alpha"),
            _tool_start("tc-1", lane="run-beta", parent_message_id="m-1"),
            _tool_end("tc-1", lane="run-beta"),
            _member_finished("run-alpha"),
            _member_finished("run-beta"),
            _run_finished(),
        ],
        "tool call tc-1 is stamped with member run-beta, while the message m-1 it names as its "
        "parent was opened in member run-alpha",
    ),
    Control(
        EVERY_TOOL_RESULT_NAMES_A_STARTED_CALL,
        "a result for a call the client never saw start",
        lambda: [_tool_result("tc-ghost"), _run_finished()],
        "tool call results name calls no TOOL_CALL_START opened: ['tc-ghost']",
    ),
    Control(
        EVERY_TOOL_RESULT_NAMES_A_STARTED_CALL,
        "a result ahead of its own call's start",
        lambda: [_tool_result("tc-1"), _tool_start("tc-1"), _tool_end("tc-1"), _run_finished()],
        "the result for tool call tc-1 went out at index 0, ahead of the TOOL_CALL_START that opened it at index 1",
    ),
    Control(
        EVERY_TOOL_RESULT_FOLLOWS_ITS_CALLS_END,
        "a result delivered while its own call was still open",
        lambda: [
            _tool_start("tc-1"),
            _tool_args("tc-1"),
            _tool_result("tc-1"),
            _tool_end("tc-1"),
            _run_finished(),
        ],
        "the result for tool call tc-1 went out at index 2, inside the call's own span: "
        "the TOOL_CALL_END that closed it is at index 3",
    ),
    Control(
        A_TOOL_RESULT_CARRIES_ITS_CALLS_MEMBER,
        "one member's tool result against another member's call",
        lambda: [
            _announced("run-alpha"),
            _announced("run-beta"),
            _tool_start("tc-1", lane="run-alpha"),
            _tool_end("tc-1", lane="run-alpha"),
            _tool_result("tc-1", lane="run-beta"),
            _member_finished("run-alpha"),
            _member_finished("run-beta"),
            _run_finished(),
        ],
        "the result for tool call tc-1 is stamped with member run-beta, while the "
        "TOOL_CALL_START that opened it named run-alpha",
    ),
    Control(
        ONE_RUN_TERMINAL_AND_NOTHING_AFTER_IT,
        "two run terminals",
        lambda: [_run_finished(), _run_finished()],
        "a run carries at most one terminal",
    ),
    Control(
        ONE_RUN_TERMINAL_AND_NOTHING_AFTER_IT,
        "an event after the run terminal",
        lambda: [_run_finished(), _text_start("m-1"), _text_end("m-1")],
        "events followed the run terminal:",
    ),
    Control(
        ONE_RUN_TERMINAL_AND_NOTHING_AFTER_IT,
        "an event after the run error",
        lambda: [_run_error(), _text_start("m-1"), _text_end("m-1")],
        "events followed the run terminal:",
    ),
    Control(
        ONE_RUN_TERMINAL_AND_NOTHING_AFTER_IT,
        "a run announced as started and never ended",
        lambda: [_run_started(), _text_start("m-1"), _text_end("m-1")],
        "this stream carries 1 RUN_STARTED and no terminal",
    ),
    Control(
        EVERY_STAMP_NAMES_AN_ANNOUNCED_MEMBER,
        "a stamp naming a member nothing announced",
        lambda: [
            _text_start("m-1", lane="run-ghost"),
            _text_end("m-1", lane="run-ghost"),
            _run_finished(),
        ],
        "is stamped with member run-ghost, which no earlier announcement named",
    ),
    Control(
        NO_MEMBER_IS_ANNOUNCED_TWICE,
        "one member announced twice",
        lambda: [
            _announced("run-alpha"),
            _announced("run-alpha"),
            _member_finished("run-alpha"),
            _run_finished(),
        ],
        "member run-alpha was announced more than once",
    ),
    Control(
        EVERY_ANNOUNCED_PARENT_IS_ANNOUNCED_TOO,
        "a parent link naming a member nothing announces",
        lambda: [
            _announced("run-child", parent="run-ghost"),
            _member_finished("run-child"),
            _run_finished(),
        ],
        "member run-child names parent run-ghost, which this stream never announces",
    ),
    Control(
        AN_ANNOUNCED_PARENT_PRECEDES_ITS_CHILD,
        "a parent link naming a member announced further down the stream",
        lambda: [
            _announced("run-child", parent="run-parent"),
            _announced("run-parent"),
            _member_finished("run-child"),
            _member_finished("run-parent"),
            _run_finished(),
        ],
        "member run-child announced at index 0 names parent run-parent, which this stream does not "
        "announce until index 1",
    ),
    Control(
        EVERY_ANNOUNCED_PARENT_LINK_RESOLVES,
        "a member announced under a delegating call this stream never carried",
        lambda: [
            _announced("run-alpha", parent_tool_call_id="tc-ghost"),
            _member_finished("run-alpha"),
            _run_finished(),
        ],
        "member run-alpha names parent_tool_call_id tc-ghost, which no TOOL_CALL_START in this stream carries",
    ),
    Control(
        EVERY_ANNOUNCED_PARENT_LINK_RESOLVES,
        "a member announced under a message this stream never opened",
        lambda: [
            _announced("run-alpha", parent_message_id="m-ghost"),
            _member_finished("run-alpha"),
            _run_finished(),
        ],
        "member run-alpha names parent_message_id m-ghost, which no TEXT_MESSAGE_START in this stream carries",
    ),
    Control(
        EVERY_ANNOUNCED_MEMBER_TERMINATES,
        "a member announced and never terminated",
        lambda: [_announced("run-alpha"), _run_finished()],
        "member run-alpha owns 0 terminals, expected exactly one",
    ),
    # A member owning two terminals is not in this table: a second terminal is
    # itself an event carrying that member after the first, so the stream breaks
    # what-follows-a-terminal as well and cannot be narrowed to one promise. It
    # is held to the count by the two exemption tests below, under each of the
    # waivers that could otherwise let a second terminal through.
    Control(
        NOTHING_CARRIES_A_MEMBER_AFTER_ITS_TERMINAL,
        "output stamped with a member the stream already closed",
        lambda: [
            _announced("run-alpha"),
            _member_finished("run-alpha"),
            _text_start("m-1", lane="run-alpha"),
            _text_end("m-1", lane="run-alpha"),
            _run_finished(),
        ],
        "events carrying member run-alpha followed its terminal",
    ),
    Control(
        NOTHING_CARRIES_A_MEMBER_AFTER_ITS_TERMINAL,
        "output stamped with a member the stream already errored",
        lambda: [
            _announced("run-alpha"),
            _member_errored("run-alpha"),
            _text_start("m-1", lane="run-alpha"),
            _text_end("m-1", lane="run-alpha"),
            _run_finished(),
        ],
        "events carrying member run-alpha followed its terminal",
    ),
    Control(
        A_CHILDS_TERMINAL_PRECEDES_ITS_PARENTS,
        "a parent terminating before its child",
        lambda: [
            _announced("run-parent"),
            _announced("run-child", parent="run-parent"),
            _member_finished("run-parent"),
            _member_finished("run-child"),
            _run_finished(),
        ],
        "member run-child terminated after its parent run-parent",
    ),
    Control(
        RUN_EVENTS_ARE_NEVER_STAMPED,
        "a run start stamped with the member the run happened to begin in",
        lambda: [
            _announced("run-alpha"),
            _run_started(lane="run-alpha"),
            _member_finished("run-alpha"),
            _run_finished(),
        ],
        "run lifecycle events carry a member lane: [('RUN_STARTED', 'run-alpha')]",
    ),
    Control(
        RUN_EVENTS_ARE_NEVER_STAMPED,
        "a run start stamped with an empty lane",
        # An empty lane is a stamp a client filters on like any other, so this
        # check reads presence rather than truth, as the state one does.
        lambda: [
            _announced(""),
            _run_started(lane=""),
            _member_finished(""),
            _run_finished(),
        ],
        "run lifecycle events carry a member lane: [('RUN_STARTED', '')]",
    ),
    Control(
        STATE_EVENTS_ARE_NEVER_STAMPED,
        "a state delta stamped with the member that caused it",
        lambda: [
            _announced("run-alpha"),
            _state_delta(lane="run-alpha"),
            _member_finished("run-alpha"),
            _run_finished(),
        ],
        "state events carry a member lane: [('STATE_DELTA', 'run-alpha')]",
    ),
    Control(
        STATE_EVENTS_ARE_NEVER_STAMPED,
        "a state snapshot stamped with the member that caused it",
        lambda: [
            _announced("run-alpha"),
            _state_snapshot(lane="run-alpha"),
            _member_finished("run-alpha"),
            _run_finished(),
        ],
        "state events carry a member lane: [('STATE_SNAPSHOT', 'run-alpha')]",
    ),
    Control(
        STATE_EVENTS_ARE_NEVER_STAMPED,
        "a state delta stamped with an empty lane",
        # An empty lane is a stamp a client filters on like any other, so the
        # check has to read presence rather than truth.
        lambda: [
            _announced(""),
            _state_delta(lane=""),
            _member_finished(""),
            _run_finished(),
        ],
        "state events carry a member lane: [('STATE_DELTA', '')]",
    ),
)

_CASES = [pytest.param(control, id=f"{control.invariant}-{control.case}") for control in _CONTROLS]


@pytest.mark.parametrize("control", _CASES)
def test_a_stream_breaking_one_invariant_is_reported_as_breaking_it(control):
    events = control.build()

    violation = stream_invariant_violation(events)

    assert violation is not None, (
        f"a stream that breaks {control.invariant} passed as well formed, so nothing checks that promise"
    )
    assert control.reported in violation, (
        f"a stream that breaks {control.invariant} was reported as something else: {violation}"
    )


def test_every_invariant_the_checker_names_has_a_stream_that_breaks_it():
    """An invariant with no control is one whose deletion nothing would notice."""
    covered = {control.invariant for control in _CONTROLS}
    assert covered == set(INVARIANTS), (
        f"invariants with no negative control: {sorted(set(INVARIANTS) - covered)}; "
        f"controls for invariants the checker does not name: {sorted(covered - set(INVARIANTS))}"
    )


# --- What the two pair rules have to let through ------------------------------

# The controls above are each rule's rejecting half. A rule that rejected every
# pair would satisfy them and fail every real stream, so the agreeing shapes are
# stated here as well.


def test_a_tool_call_and_its_parent_message_agreeing_on_a_member_is_well_formed():
    """One agreeing shape: a single member owning both the call and its parent message."""
    in_one_member = [
        _announced("run-alpha"),
        _text_start("m-1", lane="run-alpha"),
        _text_end("m-1", lane="run-alpha"),
        _tool_start("tc-1", lane="run-alpha", parent_message_id="m-1"),
        _tool_end("tc-1", lane="run-alpha"),
        _member_finished("run-alpha"),
        _run_finished(),
    ]

    assert_well_formed_stream(in_one_member)


def test_a_tool_call_and_its_parent_message_both_unattributed_is_well_formed():
    """The other agreeing shape: neither the call nor the message it hangs off attributed.

    Its own test rather than a second stream inside the member one above, which
    cannot be built at all on a protocol release without the lineage events: this
    shape would skip along with it while needing none of them.
    """
    at_the_top_level = [
        _text_start("m-1"),
        _text_end("m-1"),
        _tool_start("tc-1", parent_message_id="m-1"),
        _tool_end("tc-1"),
        _run_finished(),
    ]

    assert_well_formed_stream(at_the_top_level)


def test_an_announced_parent_ahead_of_its_child_is_well_formed():
    """The agreeing half of the parent-ordering rule: the parent announced first."""
    ordered = [
        _announced("run-parent"),
        _announced("run-child", parent="run-parent"),
        _member_finished("run-child"),
        _member_finished("run-parent"),
        _run_finished(),
    ]

    assert_well_formed_stream(ordered)


def test_a_tool_call_parented_to_a_message_the_stream_opened_is_well_formed():
    """The agreeing half of the parent-message rule, and the shape it must not refuse.

    A call parented to nothing is rendered on its own, which is the protocol's
    own shape and not a dangling reference, so the rule has to let it through.
    """
    attached = [
        _text_start("m-1"),
        _text_end("m-1"),
        _tool_start("tc-1", parent_message_id="m-1"),
        _tool_end("tc-1"),
        _run_finished(),
    ]
    parented_to_nothing = [_tool_start("tc-1"), _tool_end("tc-1"), _run_finished()]

    assert_well_formed_stream(attached)
    assert_well_formed_stream(parented_to_nothing)


def test_an_announcement_whose_links_the_stream_carries_is_well_formed():
    """The agreeing half of the parent-link rule, in the shape the interface emits.

    The member is announced inside the still open delegation call, which is what
    ``parent_tool_call_id`` names, and under the assistant message that call
    hangs off. A member announced under neither is well formed too: that is a
    lane a client draws at the top rather than nested.
    """
    nested = [
        _text_start("m-1"),
        _text_end("m-1"),
        _tool_start("tc-1", parent_message_id="m-1"),
        _announced("run-alpha", parent_tool_call_id="tc-1", parent_message_id="m-1"),
        _member_finished("run-alpha"),
        _tool_end("tc-1"),
        _run_finished(),
    ]
    linked_to_nothing = [_announced("run-alpha"), _member_finished("run-alpha"), _run_finished()]

    assert_well_formed_stream(nested)
    assert_well_formed_stream(linked_to_nothing)


def test_an_unstamped_run_lifecycle_is_well_formed():
    """The agreeing half of the run-lifecycle rule: a run that begins and ends unattributed."""
    around_a_member = [
        _run_started(),
        _announced("run-alpha"),
        _text_start("m-1", lane="run-alpha"),
        _text_end("m-1", lane="run-alpha"),
        _member_finished("run-alpha"),
        _run_finished(),
    ]

    assert_well_formed_stream(around_a_member)


def test_the_run_lifecycle_rule_refuses_a_stamped_terminal_as_well_as_a_stamped_start():
    """The terminals, which no control can isolate, held under the waiver that isolates them.

    A run terminal is the last event in the stream and a member's own terminal
    comes before it, so a stamped run terminal always carries a member after
    that member's terminal too. Granting the waiver for that second promise
    leaves the run-lifecycle stamp as the only thing left wrong.
    """
    for terminal, reported in ((_run_finished, "RUN_FINISHED"), (_run_error, "RUN_ERROR")):
        stamped = [_announced("run-alpha"), _member_finished("run-alpha"), terminal(lane="run-alpha")]

        violation = stream_invariant_violation(stamped, exempt=[TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL])

        assert violation is not None and f"run lifecycle events carry a member lane: [('{reported}', 'run-alpha')]" in (
            violation
        ), f"a stamped {reported} passed as well formed: {violation}"


# --- The exemptions ---------------------------------------------------------


def test_an_exemption_nobody_justified_is_refused():
    with pytest.raises(AssertionError, match="not a justified stream invariant exemption"):
        assert_well_formed_stream([_run_finished()], exempt=["whatever_i_felt_like"])


def test_an_exemption_the_stream_does_not_need_is_refused():
    """A waiver granted where nothing breaks stops the invariant being checked at all."""
    well_formed = [_text_start("m-1"), _text_content("m-1"), _text_end("m-1"), _run_finished()]

    assert_well_formed_stream(well_formed)
    with pytest.raises(AssertionError, match="well formed without the abandoned_mid_stream exemption"):
        assert_well_formed_stream(well_formed, exempt=[ABANDONED_MID_STREAM])


@pytest.mark.parametrize("exemption", list(EXEMPTIONS))
def test_every_exemption_waives_an_invariant_the_checker_runs(exemption):
    waived = exemption_waives(exemption)
    assert waived in INVARIANTS, f"{exemption} waives {waived!r}, which is not an invariant this checker runs"


# A case per exemption and control rather than one case per exemption looping
# over the controls: a control that needs the lineage events cannot be built on
# a protocol release without them, and inside a loop that skip takes every
# remaining control with it. Built from the invariant names alone, so assembling
# the list needs no lineage event either.
_EXEMPTION_CASES = [
    pytest.param(exemption, control, id=f"{exemption}-{control.invariant}-{control.case}")
    for exemption in EXEMPTIONS
    for control in _CONTROLS
    if control.invariant != exemption_waives(exemption)
]


@pytest.mark.parametrize(("exemption", "control"), _EXEMPTION_CASES)
def test_each_exemption_waives_its_invariant_and_only_that_one(exemption, control):
    """The stream an exemption is for still gets every other invariant checked."""
    violation = stream_invariant_violation(control.build(), exempt=[exemption])

    assert violation is not None and control.reported in violation, (
        f"granting {exemption} stopped {control.invariant} being reported on a stream that breaks it, "
        f"so it waives more than {exemption_waives(exemption)}: {violation}"
    )


def test_the_abandonment_exemptions_permit_the_stream_they_were_written_for():
    """A prefix of a stream: spans left open and a member left unterminated."""
    prefix = [_announced("run-alpha"), _text_start("m-1", lane="run-alpha"), _text_content("m-1", lane="run-alpha")]

    assert_well_formed_stream(prefix, exempt=[ABANDONED_MID_STREAM, ABANDONED_WITH_A_MEMBER_STILL_OPEN])
    assert stream_invariant_violation(prefix) is not None


def test_the_trailing_output_exemption_permits_the_stream_it_was_written_for():
    """A member's own run emitted after its terminal, still attributed to it."""
    trailing = [
        _announced("run-alpha"),
        _member_finished("run-alpha"),
        _text_start("m-1", lane="run-alpha"),
        _text_end("m-1", lane="run-alpha"),
        _run_finished(),
    ]

    assert_well_formed_stream(trailing, exempt=[TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL])
    assert stream_invariant_violation(trailing) is not None


def test_the_trailing_output_exemption_still_holds_a_member_to_one_terminal():
    """The exemption's own promise: whatever follows a terminal, the terminal is unique."""
    twice = [
        _announced("run-alpha"),
        _member_finished("run-alpha"),
        _member_finished("run-alpha"),
        _run_finished(),
    ]

    violation = stream_invariant_violation(twice, exempt=[TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL])
    assert violation is not None and "member run-alpha owns 2 terminals" in violation, (
        f"a member owning two terminals passed under {TRAILING_OUTPUT_AFTER_A_MEMBER_TERMINAL}: {violation}"
    )


def test_the_abandonment_waiver_still_holds_a_member_to_one_terminal():
    """Owning none is what the waiver permits; owning two is malformed either way."""
    twice = [
        _announced("run-alpha"),
        _member_finished("run-alpha"),
        _member_finished("run-alpha"),
        _run_finished(),
    ]

    violation = stream_invariant_violation(twice, exempt=[ABANDONED_WITH_A_MEMBER_STILL_OPEN])
    assert violation is not None and "member run-alpha owns 2 terminals, expected at most one" in violation, (
        f"a member owning two terminals passed under {ABANDONED_WITH_A_MEMBER_STILL_OPEN}: {violation}"
    )


# --- The census -------------------------------------------------------------


def test_the_census_refuses_a_bound_that_holds_for_any_stream():
    events = [_text_start("m-1"), _text_end("m-1"), _run_finished()]

    assert_stream_contains(events, EventType.TEXT_MESSAGE_START)
    with pytest.raises(AssertionError, match="holds for any stream at all"):
        assert_stream_contains(events, EventType.REASONING_START, 0)
    assert_stream_carries_exactly(events, EventType.REASONING_START, 0)
    with pytest.raises(AssertionError, match="carries 1 TEXT_MESSAGE_START events, not 2"):
        assert_stream_carries_exactly(events, EventType.TEXT_MESSAGE_START, 2)


def test_the_census_refuses_a_stream_that_carries_less_than_the_test_reasons_about():
    """The anti-vacuity guard itself: a fixture short of its subject is not a pass."""
    events = [_text_start("m-1"), _text_end("m-1"), _run_finished()]

    with pytest.raises(AssertionError, match="carries 0 REASONING_START events, but the test reasons about at least 1"):
        assert_stream_contains(events, EventType.REASONING_START)
    with pytest.raises(AssertionError, match="cannot exercise what they claim to"):
        assert_stream_contains(events, EventType.TEXT_MESSAGE_START, 2)


def test_reading_a_field_an_event_does_not_carry_is_refused():
    """A renamed field read with a default compares equal to itself on both sides."""
    assert field_of(_text_start("m-1"), "message_id") == "m-1"
    with pytest.raises(AssertionError, match="declares no invented_field"):
        field_of(_text_start("m-1"), "invented_field")


def test_reading_a_field_the_event_carries_only_as_an_extra_is_refused():
    """Declared, not merely present: the models accept attributes they never declare.

    A run terminal cannot carry a member on the wire, and setting one on the
    object anyway is what a test comparing its own writes looks like. Reading it
    back through a permissive attribute lookup is what makes that comparison
    pass.
    """
    stamped_where_the_wire_carries_nothing = _stamped(_run_started(), "run-alpha")

    assert getattr(stamped_where_the_wire_carries_nothing, "subagent_run_id") == "run-alpha"
    with pytest.raises(AssertionError, match="declares no subagent_run_id"):
        field_of(stamped_where_the_wire_carries_nothing, "subagent_run_id")


class _AnnouncementWithoutItsLane:
    """An announcement with the lane field gone, as a protocol rename would leave it.

    Built by hand because the installed models all declare the field: a rename
    is the case the strict read exists for, and no real event can stand in for
    it.
    """

    def __init__(self, event_type: EventType) -> None:
        self.type = event_type


def test_reading_an_announcement_that_names_no_member_is_refused():
    """The announced id is what every stamp, parent link and terminal resolves against.

    Read with a default, a renamed field would leave every announcement naming
    the top-level entity, and those three checks would resolve to each other and
    pass without comparing any member attribution at all.
    """
    require_lineage_events()
    renamed = cast(BaseEvent, _AnnouncementWithoutItsLane(event_type_named("SUBAGENT_STARTED")))

    assert announced_lane(_announced("run-alpha")) == "run-alpha"
    with pytest.raises(AssertionError, match="declares no subagent_run_id"):
        announced_lane(renamed)


def test_the_projection_helper_refuses_a_comparison_of_nothing():
    with pytest.raises(AssertionError, match="at least one projection"):
        in_emitted_order([_text_start("m-1")], EventType.TEXT_MESSAGE_START)


# --- Log capture at the agno loggers -----------------------------------------


def test_capturing_agno_logs_refuses_a_name_that_is_not_a_level(caplog):
    with pytest.raises(AssertionError, match="not a logging level name"):
        with captured_agno_logs(caplog, "SHOUTING"):
            pass

    with pytest.raises(AssertionError, match="not a logging level name"):
        with captured_agno_logs(caplog, "getLogger"):
            pass

    # A bool passes an int check and reads as level 1, the widest capture there
    # is, so a test asking for a name that happens to be a bool setting would
    # capture everything and never say it had asked for nothing.
    assert logging.raiseExceptions is True
    with pytest.raises(AssertionError, match="not a logging level name"):
        with captured_agno_logs(caplog, "raiseExceptions"):
            pass


def test_capturing_agno_logs_widens_a_narrow_logger_rather_than_narrowing_a_wide_one(caplog):
    """The level entered is the most permissive of the one asked for and the ones in place.

    Asking for ERROR on a logger already sitting lower has to keep the lower
    one: raising it instead drops the warnings the test is about to assert on,
    and a test that then finds nothing reads as the code not having warned.
    """
    logger = logging.getLogger(AGNO_LOGGER_NAMES[0])
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        with captured_agno_logs(caplog, "ERROR"):
            logger.warning("a warning below the level that was asked for")
    finally:
        logger.setLevel(previous)

    assert "a warning below the level that was asked for" in caplog.text, (
        "asking for ERROR raised a logger that was sitting at DEBUG, so records under ERROR were dropped"
    )


# --- The protocol release member attribution needs ----------------------------


class _AnnouncementDeclaringNoLineage:
    """An announcement class from before the lineage fields, declaring none of them.

    Built by hand: the installed class declares every one, so the release this
    checker's floor is about cannot be stood in for by a real event.
    """

    model_fields = {"type": object()}


def test_every_lineage_field_this_checker_reads_is_reported_when_it_is_missing():
    """The floor recomputed against the fields, rather than asserted as a number.

    Each of these is read off an announcement by an invariant, so a release that
    declares none of them cannot serve member attribution, whatever the version
    string says. Listed here rather than derived from the checker's own tuple,
    which would agree with itself however that tuple shrank.
    """
    assert announcement_fields_missing_from(_AnnouncementDeclaringNoLineage) == [
        "parent_message_id",
        "parent_subagent_run_id",
        "parent_tool_call_id",
        "subagent_run_id",
    ]
    assert sorted(LINEAGE_ANNOUNCEMENT_FIELDS_READ_HERE) == [
        "parent_message_id",
        "parent_subagent_run_id",
        "parent_tool_call_id",
        "subagent_run_id",
    ]


def test_the_lineage_protocol_floor_agrees_with_what_this_install_can_serve():
    """The version claim and the feature detection have to say the same thing.

    Everything member attribution needs is feature-detected, so the floor is a
    claim about which release carries those features and nothing enforces it.
    An install at or above it whose announcement omits a field this checker
    reads, or one below it that serves attribution anyway, means the floor names
    the wrong release.
    """
    installed = installed_protocol_release()
    assert installed, "the installed ag-ui-protocol version parsed to no numeric components"
    at_or_above_the_floor = installed >= LINEAGE_EVENTS_PROTOCOL_FLOOR

    assert at_or_above_the_floor == ATTRIBUTED_IS_SERVABLE, (
        f"ag-ui-protocol {installed} sits {'at or above' if at_or_above_the_floor else 'below'} the "
        f"{LINEAGE_EVENTS_PROTOCOL_FLOOR} floor this module names, while member attribution is "
        f"{'servable' if ATTRIBUTED_IS_SERVABLE else 'not servable'} on it"
    )
    assert (lineage_announcement_fields_missing() == []) == at_or_above_the_floor, (
        f"ag-ui-protocol {installed} against the {LINEAGE_EVENTS_PROTOCOL_FLOOR} floor, with these "
        f"announcement fields missing: {lineage_announcement_fields_missing()}"
    )


# --- What the encoder can put on a wire --------------------------------------


def test_the_encoder_check_reports_the_event_a_wire_would_die_on():
    assert encoding_failures([_text_start("m-1"), _run_finished()]) == []
    refused: Dict[str, Any] = {"op": "replace", "path": "/value", "value": circular()}
    assert [name for name, _ in encoding_failures([StateDeltaEvent(type=EventType.STATE_DELTA, delta=[refused])])] == [
        "STATE_DELTA"
    ]
