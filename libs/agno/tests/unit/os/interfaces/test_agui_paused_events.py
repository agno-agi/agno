"""Tests for AGUI utils _create_completion_events with paused events."""

import uuid

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import ToolCallArgsEvent, ToolCallEndEvent, ToolCallStartEvent

from agno.models.response import ToolExecution
from agno.os.interfaces.agui.utils import EventBuffer, _create_completion_events
from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
from agno.run.team import RunPausedEvent as TeamRunPausedEvent


def _make_external_tool(name: str = "send_notification") -> ToolExecution:
    """Create a ToolExecution with external_execution_required=True."""
    tool = ToolExecution(
        tool_call_id="tool-call-1",
        tool_name=name,
        tool_args={"message": "hello"},
        external_execution_required=True,
    )
    return tool


def _make_paused_event_cls(event_cls, tools=None):
    """Create a paused event with the given tools."""
    kwargs = {
        "run_id": "run-1",
        "agent_id": "agent-1" if event_cls is AgentRunPausedEvent else None,
        "team_id": "team-1" if event_cls is TeamRunPausedEvent else None,
    }
    if tools:
        kwargs["tools"] = tools
    # Set team_id/agent_id based on the event type
    if event_cls is AgentRunPausedEvent:
        kwargs.pop("team_id", None)
        kwargs["agent_id"] = "agent-1"
        kwargs["agent_name"] = "test-agent"
    elif event_cls is TeamRunPausedEvent:
        kwargs.pop("agent_id", None)
        kwargs["team_id"] = "team-1"
        kwargs["team_name"] = "test-team"
    return event_cls(**kwargs)


class TestCreateCompletionEventsPaused:
    """Test that _create_completion_events handles both Agent and Team RunPausedEvent."""

    def test_agent_run_paused_event_emits_tool_events(self):
        """Agent RunPausedEvent with external_execution tools should emit tool call events."""
        tools = [_make_external_tool("notify")]
        chunk = _make_paused_event_cls(AgentRunPausedEvent, tools=tools)

        event_buffer = EventBuffer()
        thread_id = "thread-1"
        run_id = "run-1"

        events = _create_completion_events(
            chunk=chunk,
            event_buffer=event_buffer,
            message_started=False,
            message_id=str(uuid.uuid4()),
            thread_id=thread_id,
            run_id=run_id,
        )

        # Should emit tool call start, args, and end events
        tool_start_events = [e for e in events if isinstance(e, ToolCallStartEvent)]
        tool_args_events = [e for e in events if isinstance(e, ToolCallArgsEvent)]
        tool_end_events = [e for e in events if isinstance(e, ToolCallEndEvent)]

        assert len(tool_start_events) == 1
        assert len(tool_args_events) == 1
        assert len(tool_end_events) == 1
        assert tool_start_events[0].tool_call_name == "notify"

    def test_team_run_paused_event_emits_tool_events(self):
        """Team RunPausedEvent with external_execution tools should emit tool call events."""
        tools = [_make_external_tool("send_notification")]
        chunk = _make_paused_event_cls(TeamRunPausedEvent, tools=tools)

        event_buffer = EventBuffer()
        thread_id = "thread-1"
        run_id = "run-1"

        events = _create_completion_events(
            chunk=chunk,
            event_buffer=event_buffer,
            message_started=False,
            message_id=str(uuid.uuid4()),
            thread_id=thread_id,
            run_id=run_id,
        )

        # Should emit tool call start, args, and end events
        tool_start_events = [e for e in events if isinstance(e, ToolCallStartEvent)]
        tool_args_events = [e for e in events if isinstance(e, ToolCallArgsEvent)]
        tool_end_events = [e for e in events if isinstance(e, ToolCallEndEvent)]

        assert len(tool_start_events) == 1
        assert len(tool_args_events) == 1
        assert len(tool_end_events) == 1
        assert tool_start_events[0].tool_call_name == "send_notification"

    def test_run_paused_event_without_external_tools_emits_no_tool_events(self):
        """Paused event without external_execution tools should not emit tool events."""
        # Create a tool WITHOUT external_execution
        tool = ToolExecution(
            tool_call_id="tool-call-1",
            tool_name="normal_tool",
            tool_args={},
            external_execution_required=False,
        )
        chunk = _make_paused_event_cls(AgentRunPausedEvent, tools=[tool])

        event_buffer = EventBuffer()

        events = _create_completion_events(
            chunk=chunk,
            event_buffer=event_buffer,
            message_started=False,
            message_id=str(uuid.uuid4()),
            thread_id="thread-1",
            run_id="run-1",
        )

        tool_start_events = [e for e in events if isinstance(e, ToolCallStartEvent)]
        assert len(tool_start_events) == 0

    def test_team_run_paused_event_without_tools(self):
        """Team RunPausedEvent without tools should not error."""
        chunk = _make_paused_event_cls(TeamRunPausedEvent, tools=None)

        event_buffer = EventBuffer()

        events = _create_completion_events(
            chunk=chunk,
            event_buffer=event_buffer,
            message_started=False,
            message_id=str(uuid.uuid4()),
            thread_id="thread-1",
            run_id="run-1",
        )

        tool_start_events = [e for e in events if isinstance(e, ToolCallStartEvent)]
        assert len(tool_start_events) == 0

    def test_team_run_paused_event_tools_awaiting_external_execution(self):
        """Team RunPausedEvent tools_awaiting_external_execution filters correctly."""
        tools = [
            ToolExecution(
                tool_call_id="tc-1",
                tool_name="external",
                tool_args={},
                external_execution_required=True,
            ),
            ToolExecution(
                tool_call_id="tc-2",
                tool_name="normal",
                tool_args={},
                external_execution_required=False,
            ),
        ]
        chunk = _make_paused_event_cls(TeamRunPausedEvent, tools=tools)

        result = chunk.tools_awaiting_external_execution
        assert len(result) == 1
        assert result[0].tool_call_id == "tc-1"
        assert result[0].tool_name == "external"
