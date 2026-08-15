import pytest

from agno.agent import Agent
from agno.models.message import Citations
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.team import TeamRunEvent, TeamRunOutput
from agno.session import TeamSession
from agno.team import Team


def _new_state():
    team = Team(members=[Agent(name="Agent1")])
    session = TeamSession(session_id="session_1")
    run_response = TeamRunOutput(run_id="run_1", team_id="team_1", team_name="Team")
    return team, session, run_response, ModelResponse()


def _feed(team, session, run_response, full_model_response, content, **kwargs):
    return list(
        team._handle_model_response_chunk(
            session=session,
            run_response=run_response,
            full_model_response=full_model_response,
            model_response_event=ModelResponse(
                event=ModelResponseEvent.assistant_response.value,
                content=content,
                **kwargs,
            ),
            stream_events=True,
        )
    )


def test_empty_string_content_yields_no_event_but_keeps_accumulated_text():
    team, session, run_response, fmr = _new_state()

    first = _feed(team, session, run_response, fmr, "Hello")
    empty = _feed(team, session, run_response, fmr, "")
    followup = _feed(team, session, run_response, fmr, " world")

    assert len(first) == 1
    assert first[0].event == TeamRunEvent.run_content.value
    assert first[0].content == "Hello"
    assert empty == []
    assert len(followup) == 1
    assert followup[0].content == " world"
    assert fmr.content == "Hello world"
    assert run_response.content == "Hello world"


def test_metadata_on_empty_content_chunk_is_preserved_without_emitting():
    team, session, run_response, fmr = _new_state()
    citations = Citations(raw={"source": "provider"})
    provider_data = {"response_id": "response-1"}

    events = _feed(
        team,
        session,
        run_response,
        fmr,
        "",
        citations=citations,
        provider_data=provider_data,
    )

    assert events == []
    assert run_response.citations == citations
    assert run_response.model_provider_data == provider_data


@pytest.mark.parametrize("falsy_content", [False, 0, [], {}])
def test_non_string_falsy_content_still_emits(falsy_content):
    team, session, run_response, fmr = _new_state()

    events = _feed(team, session, run_response, fmr, falsy_content)

    assert len(events) == 1
    assert events[0].event == TeamRunEvent.run_content.value
    assert events[0].content == falsy_content
