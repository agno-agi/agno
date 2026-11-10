"""Tool-completed events contain their own call's media, including when stored or continued."""

import json
from unittest.mock import Mock

import pytest

from agno.agent import Agent
from agno.agent._response import handle_model_response_chunk
from agno.agent._tools import arun_tool, run_tool
from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.agent import RunEvent, RunOutput
from agno.run.messages import RunMessages
from agno.run.team import TeamRunEvent, TeamRunOutput
from agno.session import AgentSession, TeamSession
from agno.team import Team
from agno.team._response import _handle_model_response_chunk


@pytest.fixture(
    params=[
        pytest.param(("images", "images", Image, "image/png"), id="images"),
        pytest.param(("videos", "videos", Video, "video/mp4"), id="videos"),
        pytest.param(("audios", "audio", Audio, "audio/wav"), id="audio"),
        pytest.param(("files", "files", File, "application/pdf"), id="files"),
    ]
)
def media_case(request):
    model_field, run_field, media_type, mime_type = request.param

    def make_media(name):
        return media_type(id=name, content=f"{name}-payload".encode(), mime_type=mime_type)

    return model_field, run_field, make_media


def _tool(call_id):
    return ToolExecution(tool_call_id=call_id, tool_name="render_page", tool_args={}, result="rendered")


def _completed(call_id, model_field, media=None):
    return ModelResponse(
        event=ModelResponseEvent.tool_call_completed.value,
        tool_executions=[_tool(call_id)],
        **{model_field: media},
    )


def _completed_events(events, event_name):
    return [event for event in events if event.event == event_name]


@pytest.fixture(params=[False, True], ids=["agent", "team"])
def streaming_context(request):
    model = Mock(spec=Model)
    agent = Agent(model=model, store_events=True)
    if request.param:
        team = Team(members=[agent], model=model, store_events=True)
        session = TeamSession(session_id="session_1")
        run_response = TeamRunOutput(run_id="run_1", team_id="team_1", team_name="Team")

        def emit(chunk):
            return list(
                _handle_model_response_chunk(
                    team,
                    session=session,
                    run_response=run_response,
                    full_model_response=ModelResponse(),
                    model_response_event=chunk,
                    stream_events=True,
                )
            )

        event_name = TeamRunEvent.tool_call_completed.value
    else:
        session = AgentSession(session_id="session_1")
        run_response = RunOutput(run_id="run_1", agent_id="agent_1", agent_name="Agent")

        def emit(chunk):
            return list(
                handle_model_response_chunk(
                    agent,
                    session=session,
                    run_response=run_response,
                    model_response=ModelResponse(),
                    model_response_event=chunk,
                    stream_events=True,
                )
            )

        event_name = RunEvent.tool_call_completed.value
    return run_response, emit, event_name


def test_streaming_event_carries_only_its_tool_calls_media(streaming_context, media_case):
    run_response, emit, event_name = streaming_context
    model_field, run_field, make_media = media_case
    earlier, own, later = [make_media(name) for name in ("earlier", "own", "later")]
    setattr(run_response, run_field, [earlier])

    (completed,) = _completed_events(emit(_completed("call_2", model_field, [own])), event_name)

    assert getattr(completed, run_field) == [own]
    assert getattr(run_response, run_field) == [earlier, own]
    # Growing the run's aggregate must not change an already emitted event.
    getattr(run_response, run_field).append(later)
    assert getattr(completed, run_field) == [own]


def test_media_less_event_carries_no_earlier_run_media(streaming_context, media_case):
    run_response, emit, event_name = streaming_context
    model_field, run_field, make_media = media_case
    earlier = make_media("earlier")
    setattr(run_response, run_field, [earlier])

    (completed,) = _completed_events(emit(_completed("call_2", model_field)), event_name)

    assert getattr(completed, run_field) is None
    assert getattr(run_response, run_field) == [earlier]


def test_stored_events_serialize_each_tool_media_once(streaming_context, media_case):
    run_response, emit, event_name = streaming_context
    model_field, run_field, make_media = media_case
    calls = 6

    for index in range(calls):
        emit(_completed(f"call_{index}", model_field, [make_media(f"page_{index}")]))

    stored = _completed_events(run_response.events or [], event_name)
    assert len(stored) == calls
    # Check the actual saved JSON, including the encoded media payloads.
    serialized_run = json.loads(run_response.to_json())
    serialized_events = [event for event in serialized_run["events"] if event["event"] == event_name]
    assert [[media["id"] for media in event[run_field]] for event in serialized_events] == [
        [f"page_{index}"] for index in range(calls)
    ]
    assert sum(len(event[run_field]) for event in serialized_events) == calls
    assert len(serialized_run[run_field]) == calls


def _continuation_context(team_mode, call_results, run_field, earlier):
    model = Mock(spec=Model)
    function_call = Mock()
    function_call.function.name = "render_page"
    function_call.arguments = {}
    model.get_function_call_to_run_from_tool_execution.return_value = function_call
    model.run_function_call.return_value = call_results

    async def arun_function_calls(**_kwargs):
        for call_result in call_results:
            yield call_result

    model.arun_function_calls = arun_function_calls
    agent = Agent(model=model, store_events=True)
    if team_mode:
        run_response = TeamRunOutput(run_id="run_1", team_id="team_1", team_name="Team")
        event_name = TeamRunEvent.tool_call_completed.value
    else:
        run_response = RunOutput(run_id="run_1", agent_id="agent_1", agent_name="Agent")
        event_name = RunEvent.tool_call_completed.value
    setattr(run_response, run_field, [earlier])
    return agent, run_response, event_name


@pytest.mark.parametrize("team_mode", [False, True], ids=["agent", "team"])
def test_continued_tool_event_carries_only_its_tool_calls_media(media_case, team_mode):
    model_field, run_field, make_media = media_case
    own = make_media("own")
    agent, run_response, event_name = _continuation_context(
        team_mode, [_completed("call_2", model_field, [own])], run_field, make_media("earlier")
    )

    events = list(
        run_tool(
            agent,
            run_response=run_response,
            run_messages=RunMessages(),
            tool=_tool("call_2"),
            stream_events=True,
            team_mode=team_mode,
        )
    )

    (completed,) = _completed_events(events, event_name)
    assert getattr(completed, run_field) == [own]
    getattr(run_response, run_field).append(make_media("later"))
    assert completed.to_dict()[run_field] == [own.to_dict()]


@pytest.mark.asyncio
@pytest.mark.parametrize("team_mode", [False, True], ids=["agent", "team"])
async def test_async_continued_tool_event_carries_only_its_tool_calls_media(media_case, team_mode):
    model_field, run_field, make_media = media_case
    own = make_media("own")
    agent, run_response, event_name = _continuation_context(
        team_mode, [_completed("call_2", model_field, [own])], run_field, make_media("earlier")
    )

    events = [
        event
        async for event in arun_tool(
            agent,
            run_response=run_response,
            run_messages=RunMessages(),
            tool=_tool("call_2"),
            stream_events=True,
            team_mode=team_mode,
        )
    ]

    (completed,) = _completed_events(events, event_name)
    assert getattr(completed, run_field) == [own]
    getattr(run_response, run_field).append(make_media("later"))
    assert completed.to_dict()[run_field] == [own.to_dict()]
