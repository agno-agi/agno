"""How the AG-UI mapper frames tool calls.

A tool call reaches the client as three events that have to agree with each other and
with the message they hang under. The engine offers no guarantee that a tool execution
carries an id, and it repeats a completed call whenever a run is replayed from history,
so both of those have to leave the stream valid and still reach its terminal event.
"""

import json
import logging
from datetime import datetime

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import EventType

from agno.models.response import ToolExecution
from agno.os.interfaces.agui.handlers import _tool_args_json, on_tool_call_completed
from agno.os.interfaces.agui.state import StreamState
from agno.run.agent import RunContentEvent, ToolCallCompletedEvent, ToolCallStartedEvent
from agno.run.workflow import StepCompletedEvent, StepStartedEvent, WorkflowCompletedEvent

from ._agui_mappers import MAPPER_DRIVERS, MAPPER_IDS, validated


@pytest.fixture(params=MAPPER_DRIVERS, ids=MAPPER_IDS)
def run_stream(request):
    """Drive one chunk sequence through a mapper, once per mapper."""
    return validated(request.param)


def event_types(events):
    return [event.type for event in events]


def tool_calls_of(events, event_type):
    return [event for event in events if event.type == event_type]


def test_a_completed_tool_call_with_no_id_does_not_take_the_stream_down(run_stream):
    """The paused path already refuses a tool with no id; this path let it raise instead.

    An exception here is caught by the route, which ends the run with an error in place
    of everything it had still to send rather than the one thing it could not render.
    """
    events = run_stream(
        [
            ToolCallCompletedEvent(tool=ToolExecution(tool_name="search", result="ok")),
            WorkflowCompletedEvent(),
        ]
    )

    assert events[-1].type == EventType.RUN_FINISHED
    assert EventType.TOOL_CALL_END not in event_types(events)


def test_a_started_tool_call_with_no_id_does_not_take_the_stream_down(run_stream):
    """The same guard on the other half of the pair, which the client renders together."""
    events = run_stream(
        [
            ToolCallStartedEvent(tool=ToolExecution(tool_name="search")),
            WorkflowCompletedEvent(),
        ]
    )

    assert events[-1].type == EventType.RUN_FINISHED
    assert EventType.TOOL_CALL_START not in event_types(events)


def test_a_started_tool_call_with_no_arguments_announces_an_empty_object(run_stream):
    """The paused path already renders an absent argument list as one; this path sent a null.

    What a client renders a call with reads its arguments as an object, and a null has
    no keys to read off it, so a tool taking no arguments rendered nothing at all.
    """
    events = run_stream(
        [
            ToolCallStartedEvent(tool=ToolExecution(tool_call_id="call-1", tool_name="now")),
            WorkflowCompletedEvent(),
        ]
    )

    args = next(event for event in events if event.type == EventType.TOOL_CALL_ARGS)

    assert json.loads(args.delta) == {}


def test_a_started_tool_call_keeps_arguments_the_standard_serializer_cannot_read(run_stream):
    """A datetime argument raised, which the route turned into the run's error."""
    events = run_stream(
        [
            ToolCallStartedEvent(
                tool=ToolExecution(
                    tool_call_id="call-1",
                    tool_name="schedule",
                    tool_args={"starts_at": datetime(2026, 1, 2, 3, 4, 5), "title": "review"},
                )
            ),
            WorkflowCompletedEvent(),
        ]
    )

    args = next(event for event in events if event.type == EventType.TOOL_CALL_ARGS)

    assert json.loads(args.delta) == {"starts_at": "2026-01-02 03:04:05", "title": "review"}


def _self_referring_args():
    args = {"title": "review"}
    args["itself"] = args
    return args


@pytest.mark.parametrize(
    "tool_args",
    [
        pytest.param({("starts", "at"): "noon", "title": "review"}, id="a key the serializer refuses"),
        pytest.param(_self_referring_args(), id="a record that refers to itself"),
    ],
)
def test_arguments_no_serializer_can_walk_still_reach_the_client_as_an_object(tool_args):
    """No model writes either record, so this holds the promise rather than a live case.

    The promise is worth holding because the cost of breaking it is the whole run: the
    route turns anything raised here into the run's error, in place of everything it
    still had to send.
    """
    delta = _tool_args_json(tool_args)

    arguments = json.loads(delta)
    assert isinstance(arguments, dict)
    assert arguments["title"] == "'review'"


def test_a_tool_call_with_no_id_is_logged(caplog):
    with caplog.at_level(logging.WARNING):
        validated(MAPPER_DRIVERS[0])(
            [
                ToolCallCompletedEvent(tool=ToolExecution(tool_name="search", result="ok")),
                WorkflowCompletedEvent(),
            ]
        )

    assert "search" in caplog.text


def test_a_repeated_tool_completion_still_sends_the_state_it_carries():
    """The run's state moves on between two reports of one tool call, and the client is owed it.

    The second report ends no tool call, because the client was already told this one
    ended, but the state delta rides on the same event and is not a duplicate.
    """
    state = StreamState(run_state={"count": 0})
    state.set_state_snapshot({"count": 0})
    tool = ToolExecution(tool_call_id="call-1", tool_name="increment", result="ok")
    state.start_tool_call("call-1")

    first = on_tool_call_completed(ToolCallCompletedEvent(tool=tool), state)
    assert [event.type for event in first] == [EventType.TOOL_CALL_END, EventType.TOOL_CALL_RESULT]

    state.run_state["count"] = 1
    second = on_tool_call_completed(ToolCallCompletedEvent(tool=tool), state)

    assert [event.type for event in second] == [EventType.STATE_DELTA]


def test_a_tool_call_after_a_step_output_hangs_under_the_message_the_client_holds(run_stream):
    """A step's own output opens a message of its own, and the one before it is gone.

    Parenting a later tool call to the message that was current before the step output
    points the client at a message it has already finished reading.
    """
    events = run_stream(
        [
            StepStartedEvent(step_name="One", step_id="one"),
            RunContentEvent(content="thinking", step_id="one"),
            ToolCallStartedEvent(tool=ToolExecution(tool_call_id="call-1", tool_name="search")),
            ToolCallCompletedEvent(tool=ToolExecution(tool_call_id="call-1", tool_name="search", result="ok")),
            StepCompletedEvent(step_name="One", step_id="one", content="thinking"),
            StepStartedEvent(step_name="Two", step_id="two"),
            StepCompletedEvent(step_name="Two", step_id="two", content="what the function returned"),
            StepStartedEvent(step_name="Three", step_id="three"),
            ToolCallStartedEvent(tool=ToolExecution(tool_call_id="call-2", tool_name="fetch")),
            ToolCallCompletedEvent(tool=ToolExecution(tool_call_id="call-2", tool_name="fetch", result="ok")),
            StepCompletedEvent(step_name="Three", step_id="three", content="done"),
            WorkflowCompletedEvent(),
        ]
    )

    step_output_message = next(
        event.message_id
        for event in events
        if event.type == EventType.TEXT_MESSAGE_CONTENT and event.delta == "what the function returned"
    )
    second_call = next(
        event for event in tool_calls_of(events, EventType.TOOL_CALL_START) if event.tool_call_id == "call-2"
    )

    assert second_call.parent_message_id == step_output_message
