from agno.agent import Agent
from agno.agent._response import handle_model_response_chunk
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.agent import RunEvent, RunOutput
from agno.session import AgentSession


def _collect_events(content=None, reasoning_content=None):
    agent = Agent(id="agent-1", name="Agent")
    session = AgentSession(session_id="session-1")
    run_response = RunOutput(run_id="run-1", session_id="session-1", agent_id="agent-1", agent_name="Agent")
    model_response = ModelResponse(content="")
    model_response_event = ModelResponse(
        event=ModelResponseEvent.assistant_response.value,
        content=content,
        reasoning_content=reasoning_content,
    )

    return list(
        handle_model_response_chunk(
            agent,
            session,
            run_response,
            model_response,
            model_response_event,
            stream_events=True,
        )
    )


def test_native_reasoning_delta_is_emitted_as_reasoning_event():
    events = _collect_events(reasoning_content="thinking")

    assert [event.event for event in events] == [RunEvent.reasoning_content_delta.value]
    assert events[0].reasoning_content == "thinking"


def test_native_reasoning_delta_does_not_replace_text_content_event():
    events = _collect_events(content="answer", reasoning_content="thinking")

    assert [event.event for event in events] == [
        RunEvent.reasoning_content_delta.value,
        RunEvent.run_content.value,
    ]
    assert events[0].reasoning_content == "thinking"
    assert events[1].content == "answer"
    assert events[1].reasoning_content == ""
