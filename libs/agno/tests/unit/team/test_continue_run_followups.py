"""Regression tests for followup generation after continuing a team run."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.models.response import ModelResponse
from agno.run import RunStatus
from agno.run.team import TeamRunOutput


def _team() -> MagicMock:
    team = MagicMock()
    team.retries = 0
    team.events_to_skip = []
    team.store_events = False
    team.post_hooks = None
    team.session_summary_manager = None
    team.output_model = None
    team.add_history_to_context = False
    team.fallback_config = None
    team.tool_choice = None
    team.tool_call_limit = None
    team.send_media_to_model = True
    team.compress_tool_results = False
    team.compression_manager = None
    team.db = None
    return team


def test_continue_run_generates_followups_before_persisting():
    from agno.team._run import _continue_run

    team = _team()
    run_response = TeamRunOutput(run_id="run-1", session_id="session-1")
    run_messages = MagicMock(messages=[])
    run_context = MagicMock()
    session = MagicMock(session_id="session-1")
    order = []

    def update_response(*args, **kwargs):
        run_response.content = "completed response"

    def generate_followups(team_arg, run_response):
        assert team_arg is team
        run_response.followups = ["What should happen next?"]
        order.append("followups")

    def cleanup(*args, **kwargs):
        assert run_response.followups == ["What should happen next?"]
        order.append("cleanup")

    with (
        patch("agno.team._run.register_run"),
        patch("agno.team._run.cleanup_run"),
        patch("agno.team._run.handle_event"),
        patch("agno.team._run.call_model_with_fallback", return_value=ModelResponse(content="completed response")),
        patch("agno.team._run.build_team_after_tool_results_callback"),
        patch("agno.team._run.store_media_util"),
        patch("agno.team._run._cleanup_and_store", side_effect=cleanup),
        patch("agno.team._init._disconnect_connectable_tools"),
        patch("agno.team._telemetry.log_team_telemetry"),
        patch("agno.team._response.parse_response_with_output_model"),
        patch("agno.team._response.parse_response_with_parser_model"),
        patch("agno.team._response._convert_response_to_structured_format"),
        patch("agno.team._response._update_run_response", side_effect=update_response),
        patch("agno.team._response.generate_team_followups", side_effect=generate_followups) as followups,
    ):
        result = _continue_run(
            team,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            tools=[],
            session=session,
        )

    assert result is run_response
    assert run_response.status == RunStatus.completed
    assert order == ["followups", "cleanup"]
    followups.assert_called_once_with(team, run_response=run_response)


def test_continue_run_stream_forwards_followup_events_before_completion():
    from agno.team._run import _continue_run_stream

    team = _team()
    run_response = TeamRunOutput(run_id="run-1", session_id="session-1", content="completed response")
    run_context = MagicMock()
    session = MagicMock(session_id="session-1")

    def generate_followups(team_arg, run_response, stream_events):
        assert team_arg is team
        assert stream_events is True
        run_response.followups = ["What should happen next?"]
        yield "followups-started"
        yield "followups-completed"

    with (
        patch("agno.team._run.register_run"),
        patch("agno.team._run.cleanup_run"),
        patch("agno.team._run.raise_if_cancelled"),
        patch("agno.team._run.handle_event", side_effect=lambda event, *args, **kwargs: event),
        patch("agno.team._run._handle_team_tool_call_updates_stream", return_value=iter(())),
        patch("agno.team._run._cleanup_and_store") as cleanup,
        patch("agno.team._init._disconnect_connectable_tools"),
        patch("agno.team._telemetry.log_team_telemetry"),
        patch("agno.team._response._handle_model_response_stream", return_value=iter(())),
        patch("agno.team._response.parse_response_with_parser_model_stream", return_value=iter(())),
        patch("agno.team._response.generate_team_followups_stream", side_effect=generate_followups),
    ):
        events = list(
            _continue_run_stream(
                team,
                run_response=run_response,
                run_messages=MagicMock(messages=[]),
                run_context=run_context,
                tools=[],
                session=session,
                stream_events=True,
            )
        )

    event_names = [event if isinstance(event, str) else event.event for event in events]
    assert event_names[-3:] == ["followups-started", "followups-completed", "TeamRunCompleted"]
    assert run_response.followups == ["What should happen next?"]
    cleanup.assert_called_once_with(team, run_response=run_response, session=session)


@pytest.mark.asyncio
async def test_acontinue_run_generates_followups_before_persisting():
    from agno.team._run import _acontinue_run

    team = _team()
    run_response = TeamRunOutput(run_id="run-1", session_id="session-1", status=RunStatus.running)
    run_context = MagicMock()
    session = MagicMock(session_id="session-1", runs=[run_response])
    order = []

    async def complete_model_response(*args, **kwargs):
        run_response.content = "completed response"
        return None

    async def generate_followups(team_arg, run_response):
        assert team_arg is team
        run_response.followups = ["What should happen next?"]
        order.append("followups")

    async def cleanup(*args, **kwargs):
        assert run_response.followups == ["What should happen next?"]
        order.append("cleanup")

    with (
        patch("agno.team._run._asetup_session", new=AsyncMock(return_value=session)),
        patch("agno.team._run.aregister_run", new=AsyncMock()),
        patch("agno.team._run.acleanup_run", new=AsyncMock()),
        patch("agno.team._run.handle_event"),
        patch("agno.team._run._get_continue_run_messages", return_value=MagicMock(messages=[])),
        patch("agno.team._run._ahandle_model_response_for_continue", side_effect=complete_model_response),
        patch("agno.team._run._acleanup_and_store", side_effect=cleanup),
        patch("agno.team._init._disconnect_connectable_tools"),
        patch("agno.team._init._disconnect_mcp_tools", new=AsyncMock()),
        patch("agno.team._tools._check_and_refresh_mcp_tools", new=AsyncMock()),
        patch("agno.team._tools._aget_learning_tools", new=AsyncMock(return_value=[])),
        patch("agno.team._tools._determine_tools_for_model", return_value=[]),
        patch("agno.team._telemetry.alog_team_telemetry", new=AsyncMock()),
        patch("agno.team._response.agenerate_team_followups", side_effect=generate_followups) as followups,
    ):
        result = await _acontinue_run(
            team,
            session_id="session-1",
            run_context=run_context,
            run_response=run_response,
        )

    assert result is run_response
    assert run_response.status == RunStatus.completed
    assert order == ["followups", "cleanup"]
    followups.assert_awaited_once_with(team, run_response=run_response)


@pytest.mark.asyncio
async def test_acontinue_run_stream_forwards_followup_events_before_completion():
    from agno.team._run import _acontinue_run_stream

    team = _team()
    run_response = TeamRunOutput(run_id="run-1", session_id="session-1", status=RunStatus.running)
    run_context = MagicMock()
    session = MagicMock(session_id="session-1", runs=[run_response])

    async def empty_stream(*args, **kwargs):
        if False:
            yield None

    async def complete_model_response(*args, **kwargs):
        run_response.content = "completed response"
        if False:
            yield None

    async def generate_followups(team_arg, run_response, stream_events):
        assert team_arg is team
        assert stream_events is True
        run_response.followups = ["What should happen next?"]
        yield "followups-started"
        yield "followups-completed"

    with (
        patch("agno.team._run._asetup_session", new=AsyncMock(return_value=session)),
        patch("agno.team._run.aregister_run", new=AsyncMock()),
        patch("agno.team._run.acleanup_run", new=AsyncMock()),
        patch("agno.team._run.araise_if_cancelled", new=AsyncMock()),
        patch("agno.team._run.handle_event", side_effect=lambda event, *args, **kwargs: event),
        patch("agno.team._run._get_continue_run_messages", return_value=MagicMock(messages=[])),
        patch("agno.team._run._ahandle_team_tool_call_updates_stream", side_effect=empty_stream),
        patch("agno.team._run._acleanup_and_store", new=AsyncMock()) as cleanup,
        patch("agno.team._init._disconnect_connectable_tools"),
        patch("agno.team._init._disconnect_mcp_tools", new=AsyncMock()),
        patch("agno.team._tools._check_and_refresh_mcp_tools", new=AsyncMock()),
        patch("agno.team._tools._aget_learning_tools", new=AsyncMock(return_value=[])),
        patch("agno.team._tools._determine_tools_for_model", return_value=[]),
        patch("agno.team._telemetry.alog_team_telemetry", new=AsyncMock()),
        patch("agno.team._response._ahandle_model_response_stream", side_effect=complete_model_response),
        patch("agno.team._response.aparse_response_with_parser_model_stream", side_effect=empty_stream),
        patch("agno.team._response.agenerate_team_followups_stream", side_effect=generate_followups),
    ):
        events = [
            event
            async for event in _acontinue_run_stream(
                team,
                session_id="session-1",
                run_context=run_context,
                run_response=run_response,
                stream_events=True,
            )
        ]

    event_names = [event if isinstance(event, str) else event.event for event in events]
    assert event_names[-3:] == ["followups-started", "followups-completed", "TeamRunCompleted"]
    assert run_response.followups == ["What should happen next?"]
    cleanup.assert_awaited_once_with(team, run_response=run_response, session=session)
