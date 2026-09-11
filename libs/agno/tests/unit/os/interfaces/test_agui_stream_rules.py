"""The protocol checker's own coverage.

Every AG-UI suite that drives a mapper leans on this checker, so a rule it silently
fails to enforce is a rule none of those suites enforces either. Each rule the checker
states gets a stream that breaks it, and each family gets a stream that satisfies it.

Three families word their terminal-event rule alike, so each of those refusals matches
the whole sentence its own family emits. A bare "still open at the terminal event" would
pass on any of the three, and a stream that broke the wrong rule would look checked.
"""

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import (  # noqa: E402
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from ._agui_stream_rules import assert_valid_agui_stream  # noqa: E402

THREAD = {"thread_id": "thread-1", "run_id": "run-1"}


def started():
    return RunStartedEvent(**THREAD)


def finished():
    return RunFinishedEvent(**THREAD)


def message(message_id="msg-1", text="hi"):
    return [
        TextMessageStartEvent(message_id=message_id),
        TextMessageContentEvent(message_id=message_id, delta=text),
        TextMessageEndEvent(message_id=message_id),
    ]


def tool_call(call_id="call-1", name="lookup"):
    return [
        ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name),
        ToolCallArgsEvent(tool_call_id=call_id, delta="{}"),
        ToolCallEndEvent(tool_call_id=call_id),
    ]


def refuses(match, *events):
    with pytest.raises(AssertionError, match=match):
        assert_valid_agui_stream(list(events))


class TestRunFraming:
    def test_a_well_framed_run_passes(self):
        assert_valid_agui_stream([started(), *message(), finished()])

    def test_a_run_that_ends_in_an_error_passes(self):
        assert_valid_agui_stream([started(), *message(), RunErrorEvent(message="stopped")])

    def test_a_body_without_run_started_passes_because_the_route_prepends_it(self):
        assert_valid_agui_stream([*message(), finished()])

    def test_an_empty_stream_is_refused(self):
        refuses("carried no events at all")

    def test_run_started_twice_is_refused(self):
        refuses("appears more than once", started(), started(), finished())

    def test_run_started_after_another_event_is_refused(self):
        refuses("is not the first event", StepStartedEvent(step_name="Plan"), started(), finished())

    def test_a_stream_that_never_terminates_is_refused(self):
        refuses("never reached RUN_FINISHED or RUN_ERROR", started())

    def test_two_terminal_events_are_refused(self):
        refuses("more than one terminal event", started(), finished(), RunErrorEvent(message="stopped"))

    def test_a_terminal_event_that_is_not_last_is_refused(self):
        refuses("is not the last event", started(), finished(), StepStartedEvent(step_name="Plan"))


class TestStepSpans:
    def test_nested_spans_pass(self):
        assert_valid_agui_stream(
            [
                started(),
                StepStartedEvent(step_name="Outer"),
                StepStartedEvent(step_name="Inner"),
                StepFinishedEvent(step_name="Inner"),
                StepFinishedEvent(step_name="Outer"),
                finished(),
            ]
        )

    def test_a_step_started_while_already_active_is_refused(self):
        refuses(
            "is started while already active",
            started(),
            StepStartedEvent(step_name="Plan"),
            StepStartedEvent(step_name="Plan"),
            StepFinishedEvent(step_name="Plan"),
            StepFinishedEvent(step_name="Plan"),
            finished(),
        )

    def test_a_step_finished_while_not_active_is_refused(self):
        refuses("is finished while not active", started(), StepFinishedEvent(step_name="Plan"), finished())

    def test_a_step_left_open_at_the_terminal_event_is_refused(self):
        refuses(
            r"steps \['Plan'\] are still open at the terminal event",
            started(),
            StepStartedEvent(step_name="Plan"),
            finished(),
        )


class TestTextMessages:
    def test_a_well_framed_message_passes(self):
        assert_valid_agui_stream([started(), *message(), finished()])

    def test_an_empty_message_closed_immediately_passes(self):
        """The mapper opens and closes one on purpose, as a tool call's parent message
        and as the assistant turn a pause with no text still has to open."""
        assert_valid_agui_stream(
            [
                started(),
                TextMessageStartEvent(message_id="msg-1"),
                TextMessageEndEvent(message_id="msg-1"),
                *tool_call(),
                finished(),
            ]
        )

    def test_an_empty_message_closed_after_other_events_is_refused(self):
        refuses(
            "carries no content and is closed only after other events went out",
            started(),
            TextMessageStartEvent(message_id="msg-1"),
            StepStartedEvent(step_name="Plan"),
            StepFinishedEvent(step_name="Plan"),
            TextMessageEndEvent(message_id="msg-1"),
            finished(),
        )

    def test_a_message_started_inside_another_is_refused(self):
        refuses(
            "starts while message msg-1 is still open",
            started(),
            TextMessageStartEvent(message_id="msg-1"),
            TextMessageStartEvent(message_id="msg-2"),
            TextMessageEndEvent(message_id="msg-2"),
            TextMessageEndEvent(message_id="msg-1"),
            finished(),
        )

    def test_content_outside_a_message_is_refused(self):
        refuses(
            "arrives outside a message",
            started(),
            TextMessageContentEvent(message_id="msg-1", delta="hi"),
            finished(),
        )

    def test_content_naming_another_message_is_refused(self):
        refuses(
            "content for message msg-2 arrives inside message msg-1",
            started(),
            TextMessageStartEvent(message_id="msg-1"),
            TextMessageContentEvent(message_id="msg-2", delta="hi"),
            TextMessageEndEvent(message_id="msg-1"),
            finished(),
        )

    def test_an_end_without_a_start_is_refused(self):
        refuses(
            "ends without having started",
            started(),
            TextMessageEndEvent(message_id="msg-1"),
            finished(),
        )

    def test_an_end_naming_another_message_is_refused(self):
        refuses(
            "message msg-2 ends while message msg-1 is open",
            started(),
            TextMessageStartEvent(message_id="msg-1"),
            TextMessageContentEvent(message_id="msg-1", delta="hi"),
            TextMessageEndEvent(message_id="msg-2"),
            finished(),
        )

    def test_a_message_left_open_at_the_terminal_event_is_refused(self):
        refuses(
            "message msg-1 is still open at the terminal event",
            started(),
            TextMessageStartEvent(message_id="msg-1"),
            TextMessageContentEvent(message_id="msg-1", delta="hi"),
            finished(),
        )


class TestToolCalls:
    def test_a_well_formed_tool_call_passes(self):
        assert_valid_agui_stream(
            [
                started(),
                *tool_call(),
                ToolCallResultEvent(message_id="msg-1", tool_call_id="call-1", content="done"),
                finished(),
            ]
        )

    def test_a_tool_call_left_open_is_refused(self):
        refuses(
            "tool call call-1 is still open at the terminal event",
            started(),
            ToolCallStartEvent(tool_call_id="call-1", tool_call_name="lookup"),
            ToolCallArgsEvent(tool_call_id="call-1", delta="{}"),
            finished(),
        )

    def test_a_tool_call_id_started_twice_is_refused(self):
        refuses("started twice", started(), *tool_call(), *tool_call(), finished())

    def test_a_second_tool_call_opened_inside_the_first_is_refused(self):
        refuses(
            "starts while tool call call-1 is still open",
            started(),
            ToolCallStartEvent(tool_call_id="call-1", tool_call_name="lookup"),
            ToolCallStartEvent(tool_call_id="call-2", tool_call_name="lookup"),
            ToolCallEndEvent(tool_call_id="call-2"),
            ToolCallEndEvent(tool_call_id="call-1"),
            finished(),
        )

    def test_arguments_outside_a_tool_call_are_refused(self):
        refuses(
            "arrive outside a tool call",
            started(),
            ToolCallArgsEvent(tool_call_id="call-1", delta="{}"),
            finished(),
        )

    def test_arguments_naming_another_tool_call_are_refused(self):
        refuses(
            "arguments for tool call call-2 arrive inside tool call call-1",
            started(),
            ToolCallStartEvent(tool_call_id="call-1", tool_call_name="lookup"),
            ToolCallArgsEvent(tool_call_id="call-2", delta="{}"),
            ToolCallEndEvent(tool_call_id="call-1"),
            finished(),
        )

    def test_an_end_without_a_start_is_refused(self):
        refuses("ends without having started", started(), ToolCallEndEvent(tool_call_id="call-1"), finished())

    def test_an_end_naming_another_tool_call_is_refused(self):
        refuses(
            "call-2 ends while tool call call-1 is open",
            started(),
            ToolCallStartEvent(tool_call_id="call-1", tool_call_name="lookup"),
            ToolCallEndEvent(tool_call_id="call-2"),
            finished(),
        )

    def test_a_result_for_a_tool_call_that_never_ended_is_refused(self):
        refuses(
            "never ended",
            started(),
            ToolCallResultEvent(message_id="msg-1", tool_call_id="call-1", content="done"),
            finished(),
        )

    def test_a_second_result_for_the_same_tool_call_is_refused(self):
        refuses(
            "a second result arrives for tool call call-1",
            started(),
            *tool_call(),
            ToolCallResultEvent(message_id="msg-1", tool_call_id="call-1", content="done"),
            ToolCallResultEvent(message_id="msg-2", tool_call_id="call-1", content="done again"),
            finished(),
        )
