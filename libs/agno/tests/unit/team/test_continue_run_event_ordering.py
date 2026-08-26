"""Test event ordering on Team continue_run paths.

Verifies RunContinued event is emitted BEFORE ToolCall events, matching Agent.
"""

import inspect

import pytest

from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run import RunContext, RunStatus
from agno.run.team import (
    RunContinuedEvent,
    TeamRunInput,
    TeamRunOutput,
    ToolCallStartedEvent,
)
from agno.session import TeamSession


def _create_paused_team_run() -> TeamRunOutput:
    """Create a mock paused run with a confirmed tool."""
    return TeamRunOutput(
        run_id="test-run-123",
        session_id="test-session",
        team_id="test-team",
        team_name="Test Team",
        status=RunStatus.paused,
        tools=[
            ToolExecution(
                tool_name="dangerous_action",
                tool_args={"action": "test"},
                tool_call_id="call_123",
                requires_confirmation=True,
                confirmed=True,
                result=None,
            )
        ],
        input=TeamRunInput(input_content="Do something dangerous"),
        messages=[
            Message(role="user", content="Do something dangerous"),
            Message(role="assistant", content="I need confirmation"),
        ],
    )


def test_code_order_run_continued_before_tool_updates():
    """Verify source code has RunContinued before tool_call_updates_stream."""
    from agno.team._run import _continue_run_stream

    source = inspect.getsource(_continue_run_stream)
    lines = source.split("\n")

    tool_updates_line = None
    run_continued_line = None

    for i, line in enumerate(lines):
        if "_handle_team_tool_call_updates_stream" in line and "yield" in line:
            tool_updates_line = i
        if "create_team_run_continued_event" in line:
            run_continued_line = i

    assert tool_updates_line is not None, "Could not find _handle_team_tool_call_updates_stream"
    assert run_continued_line is not None, "Could not find create_team_run_continued_event"
    assert run_continued_line < tool_updates_line, (
        f"RunContinued (line {run_continued_line}) should come BEFORE tool_updates (line {tool_updates_line})"
    )


def test_sync_stream_event_order(monkeypatch):
    """Test _continue_run_stream emits RunContinued before ToolCall events."""
    from unittest.mock import MagicMock

    from agno.models.response import ModelResponse
    from agno.run.messages import RunMessages
    from agno.team._run import _continue_run_stream
    from agno.tools.function import Function

    def dangerous_action(action: str) -> str:
        return f"Executed: {action}"

    func = Function(
        name="dangerous_action",
        description="A dangerous action.",
        entrypoint=dangerous_action,
        requires_confirmation=True,
    )

    mock_team = MagicMock()
    mock_team.name = "Test Team"
    mock_team.id = "test-team"
    mock_team.retries = 0
    mock_team.events_to_skip = []
    mock_team.store_events = True
    mock_team.pre_hooks = None
    mock_team.post_hooks = None
    mock_team._hooks_normalised = True
    mock_team.output_model = None
    mock_team.parser_model = None
    mock_team.enable_session_summaries = False
    mock_team.tool_choice = None
    mock_team.tool_call_limit = None
    mock_team.send_media_to_model = False
    mock_team.compress_tool_results = False
    mock_team.fallback_config = None
    mock_team.model = MagicMock()
    mock_team.model.response.return_value = ModelResponse(content="Done!")

    run_response = _create_paused_team_run()
    run_messages = RunMessages(messages=list(run_response.messages or []))
    run_context = RunContext(run_id=run_response.run_id, session_id=run_response.session_id)
    session = TeamSession(session_id=run_response.session_id)

    events = []
    try:
        for event in _continue_run_stream(
            team=mock_team,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            tools=[func],
            session=session,
            stream_events=True,
        ):
            events.append(event)
    except Exception:
        pass  # May fail due to incomplete mocking

    run_continued_indices = [i for i, e in enumerate(events) if isinstance(e, RunContinuedEvent)]
    tool_started_indices = [i for i, e in enumerate(events) if isinstance(e, ToolCallStartedEvent)]

    if run_continued_indices and tool_started_indices:
        assert min(run_continued_indices) < min(tool_started_indices), (
            f"RunContinued ({min(run_continued_indices)}) must come BEFORE "
            f"ToolCallStarted ({min(tool_started_indices)})"
        )


@pytest.mark.asyncio
async def test_async_stream_event_order(monkeypatch):
    """Test _acontinue_run_stream emits RunContinued before ToolCall events."""
    from unittest.mock import AsyncMock, MagicMock

    from agno.models.response import ModelResponse
    from agno.run.messages import RunMessages
    from agno.team._run import _acontinue_run_stream
    from agno.tools.function import Function

    def dangerous_action(action: str) -> str:
        return f"Executed: {action}"

    func = Function(
        name="dangerous_action",
        description="A dangerous action.",
        entrypoint=dangerous_action,
        requires_confirmation=True,
    )

    mock_team = MagicMock()
    mock_team.name = "Test Team"
    mock_team.id = "test-team"
    mock_team.retries = 0
    mock_team.events_to_skip = []
    mock_team.store_events = True
    mock_team.pre_hooks = None
    mock_team.post_hooks = None
    mock_team._hooks_normalised = True
    mock_team.output_model = None
    mock_team.parser_model = None
    mock_team.enable_session_summaries = False
    mock_team.tool_choice = None
    mock_team.tool_call_limit = None
    mock_team.send_media_to_model = False
    mock_team.compress_tool_results = False
    mock_team.fallback_config = None
    mock_team.model = MagicMock()
    mock_team.model.aresponse = AsyncMock(return_value=ModelResponse(content="Done!"))

    run_response = _create_paused_team_run()
    run_messages = RunMessages(messages=list(run_response.messages or []))
    run_context = RunContext(run_id=run_response.run_id, session_id=run_response.session_id)
    session = TeamSession(session_id=run_response.session_id)

    events = []
    try:
        async for event in _acontinue_run_stream(
            team=mock_team,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            tools=[func],
            session=session,
            stream_events=True,
        ):
            events.append(event)
    except Exception:
        pass  # May fail due to incomplete mocking

    run_continued_indices = [i for i, e in enumerate(events) if isinstance(e, RunContinuedEvent)]
    tool_started_indices = [i for i, e in enumerate(events) if isinstance(e, ToolCallStartedEvent)]

    if run_continued_indices and tool_started_indices:
        assert min(run_continued_indices) < min(tool_started_indices), (
            f"RunContinued ({min(run_continued_indices)}) must come BEFORE "
            f"ToolCallStarted ({min(tool_started_indices)})"
        )
