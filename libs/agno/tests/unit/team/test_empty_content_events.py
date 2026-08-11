import pytest

from agno.agent import Agent
from agno.models.message import Citations
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.team import TeamRunEvent, TeamRunOutput
from agno.session import TeamSession
from agno.team import Team


def test_team_stream_skips_empty_model_content_and_preserves_accumulated_content():
    team = Team(members=[Agent(name="Agent1")])
    session = TeamSession(session_id="session_1")
    run_response = TeamRunOutput(run_id="run_1", team_id="team_1", team_name="Team")
    full_model_response = ModelResponse()

    first_events = list(
        team._handle_model_response_chunk(
            session=session,
            run_response=run_response,
            full_model_response=full_model_response,
            model_response_event=ModelResponse(
                event=ModelResponseEvent.assistant_response.value,
                content="Hello",
            ),
            stream_events=True,
        )
    )

    empty_events = list(
        team._handle_model_response_chunk(
            session=session,
            run_response=run_response,
            full_model_response=full_model_response,
            model_response_event=ModelResponse(
                event=ModelResponseEvent.assistant_response.value,
                content="",
            ),
            stream_events=True,
        )
    )

    assert len(first_events) == 1
    assert first_events[0].event == TeamRunEvent.run_content.value
    assert first_events[0].content == "Hello"
    assert empty_events == []
    assert full_model_response.content == "Hello"
    assert run_response.content == "Hello"

    followup_events = list(
        team._handle_model_response_chunk(
            session=session,
            run_response=run_response,
            full_model_response=full_model_response,
            model_response_event=ModelResponse(
                event=ModelResponseEvent.assistant_response.value,
                content=" world",
            ),
            stream_events=True,
        )
    )

    assert len(followup_events) == 1
    assert followup_events[0].event == TeamRunEvent.run_content.value
    assert followup_events[0].content == " world"
    assert full_model_response.content == "Hello world"
    assert run_response.content == "Hello world"


def test_team_stream_preserves_metadata_on_empty_model_content():
    team = Team(members=[Agent(name="Agent1")])
    session = TeamSession(session_id="session_1")
    run_response = TeamRunOutput(run_id="run_1", team_id="team_1", team_name="Team")
    full_model_response = ModelResponse()
    citations = Citations(raw={"source": "provider"})
    provider_data = {"response_id": "response-1"}

    events = list(
        team._handle_model_response_chunk(
            session=session,
            run_response=run_response,
            full_model_response=full_model_response,
            model_response_event=ModelResponse(
                event=ModelResponseEvent.assistant_response.value,
                content="",
                citations=citations,
                provider_data=provider_data,
            ),
            stream_events=True,
        )
    )

    assert events == []
    assert run_response.citations == citations
    assert run_response.model_provider_data == provider_data


@pytest.mark.parametrize("falsy_content", [False, 0, [], {}])
def test_team_stream_preserves_other_falsy_model_content(falsy_content):
    team = Team(members=[Agent(name="Agent1")])
    session = TeamSession(session_id="session_1")
    run_response = TeamRunOutput(run_id="run_1", team_id="team_1", team_name="Team")
    full_model_response = ModelResponse()

    events = list(
        team._handle_model_response_chunk(
            session=session,
            run_response=run_response,
            full_model_response=full_model_response,
            model_response_event=ModelResponse(
                event=ModelResponseEvent.assistant_response.value,
                content=falsy_content,
            ),
            stream_events=True,
        )
    )

    assert len(events) == 1
    assert events[0].event == TeamRunEvent.run_content.value
    assert events[0].content == falsy_content
    assert full_model_response.content is None
    assert run_response.content is None
