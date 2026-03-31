"""Tests that member RunContentEvent objects are wrapped as IntermediateRunContentEvent
in _handle_model_response_chunk to prevent duplicate content in team streaming."""

from unittest.mock import MagicMock

from agno.run.agent import RunContentEvent, ToolCallCompletedEvent
from agno.run.team import IntermediateRunContentEvent, TeamRunOutput


def _make_team(stream_member_events: bool = True):
    team = MagicMock()
    team.stream_member_events = stream_member_events
    team.events_to_skip = None
    team.store_events = False
    team.id = "team-1"
    team.name = "Test Team"
    return team


def _make_session():
    session = MagicMock()
    session.session_id = "session-1"
    return session


def _make_run_response():
    run_response = MagicMock(spec=TeamRunOutput)
    run_response.run_id = "run-1"
    run_response.team_id = "team-1"
    run_response.team_name = "Test Team"
    run_response.session_id = "session-1"
    run_response.events = []
    return run_response


def test_member_run_content_wrapped_as_intermediate():
    """Member RunContentEvent must be wrapped as IntermediateRunContentEvent
    so the Slack interface (and other consumers) can suppress it in team mode."""
    from agno.team._response import _handle_model_response_chunk

    team = _make_team()
    session = _make_session()
    run_response = _make_run_response()

    member_content_event = RunContentEvent(
        content="Member says hello",
        content_type="str",
        agent_id="member-1",
        agent_name="Member Agent",
    )

    events = list(
        _handle_model_response_chunk(
            team,
            session=session,
            run_response=run_response,
            full_model_response=MagicMock(),
            model_response_event=member_content_event,
            stream_events=True,
        )
    )

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, IntermediateRunContentEvent)
    assert event.content == "Member says hello"
    assert event.content_type == "str"


def test_member_non_content_events_pass_through():
    """Non-content member events (like ToolCallCompleted) should NOT be wrapped."""
    from agno.team._response import _handle_model_response_chunk

    team = _make_team()
    session = _make_session()
    run_response = _make_run_response()

    tool_event = ToolCallCompletedEvent(
        agent_id="member-1",
        agent_name="Member Agent",
        tool=MagicMock(),
    )

    events = list(
        _handle_model_response_chunk(
            team,
            session=session,
            run_response=run_response,
            full_model_response=MagicMock(),
            model_response_event=tool_event,
            stream_events=True,
        )
    )

    assert len(events) == 1
    event = events[0]
    # Should remain as ToolCallCompletedEvent, not wrapped
    assert not isinstance(event, IntermediateRunContentEvent)


def test_member_events_suppressed_when_stream_member_events_false():
    """When stream_member_events=False, member events should be suppressed entirely."""
    from agno.team._response import _handle_model_response_chunk

    team = _make_team(stream_member_events=False)
    session = _make_session()
    run_response = _make_run_response()

    member_content_event = RunContentEvent(
        content="Should not appear",
        content_type="str",
        agent_id="member-1",
        agent_name="Member Agent",
    )

    events = list(
        _handle_model_response_chunk(
            team,
            session=session,
            run_response=run_response,
            full_model_response=MagicMock(),
            model_response_event=member_content_event,
            stream_events=True,
        )
    )

    assert len(events) == 0
