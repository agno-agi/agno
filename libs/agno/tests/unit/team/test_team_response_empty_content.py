"""Regression test for agno-agi/agno#9491.

Empty-string content on a model response event (e.g. Anthropic MessageStopEvent)
must not yield a content event.
"""

from types import SimpleNamespace

from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team._response import _handle_model_response_chunk


def _make_team():
    return SimpleNamespace(
        id="team-1",
        name="Test Team",
        stream_member_events=True,
        _member_response_model=None,
        events_to_skip=[],
        store_events=True,
    )


def test_empty_string_content_does_not_yield_event():
    """A MessageStop-style event with content='' should not surface as content."""
    team = _make_team()
    session = TeamSession(session_id="session-1", team_id=team.id)
    run_response = TeamRunOutput(run_id="run-1")
    full_model_response = ModelResponse()
    event = ModelResponse(
        event=ModelResponseEvent.assistant_response.value,
        content="",
    )

    events = list(
        _handle_model_response_chunk(
            team,
            session,
            run_response,
            full_model_response,
            event,
        )
    )

    assert events == []


def test_non_empty_string_content_yields_event():
    """A normal text delta must still yield a content event."""
    team = _make_team()
    session = TeamSession(session_id="session-1", team_id=team.id)
    run_response = TeamRunOutput(run_id="run-1")
    full_model_response = ModelResponse()
    event = ModelResponse(
        event=ModelResponseEvent.assistant_response.value,
        content="hello",
    )

    events = list(
        _handle_model_response_chunk(
            team,
            session,
            run_response,
            full_model_response,
            event,
        )
    )

    assert len(events) == 1
    assert run_response.content == "hello"
