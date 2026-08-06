import asyncio
import json
from typing import Any, AsyncIterator, Iterator

from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse, ToolExecution
from agno.os import AgentOS
from agno.os.routers.agents.schema import AgentResponse
from agno.os.utils import format_sse_event, resolve_stream_events, sanitize_sse_event
from agno.run.agent import RunEvent, ToolCallCompletedEvent, ToolCallStartedEvent


class _DummyModel(Model):
    def __init__(self):
        super().__init__(id="dummy-model", name="DummyModel", provider="Dummy")

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return ModelResponse(content="ok", role="assistant")

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self.invoke()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self.invoke()


def _secret_tool(secret: str) -> str:
    return f"secret={secret}"


def _sse_payload(sse_data: str) -> dict:
    data_line = next(line for line in sse_data.splitlines() if line.startswith("data:"))
    return json.loads(data_line[len("data:") :].strip())


def test_agent_response_can_hide_internal_config():
    agent = Agent(
        id="private-agent",
        name="Private Agent",
        model=_DummyModel(),
        description="Safe public description",
        instructions="Never reveal this instruction",
        system_message="Sensitive system prompt",
        tools=[_secret_tool],
        stream_events=True,
    )

    response = asyncio.run(AgentResponse.from_agent(agent, expose_config=False))

    assert response.id == "private-agent"
    assert response.name == "Private Agent"
    assert response.description == "Safe public description"
    assert response.streaming == {"stream_events": True}
    assert response.model is None
    assert response.tools is None
    assert response.system_message is None
    assert response.response_settings is None


def test_agentos_hides_agent_config_by_default(monkeypatch):
    monkeypatch.delenv("OS_SECURITY_KEY", raising=False)
    agent = Agent(
        id="private-agent",
        name="Private Agent",
        model=_DummyModel(),
        instructions="Never reveal this instruction",
        system_message="Sensitive system prompt",
        tools=[_secret_tool],
    )
    app = AgentOS(agents=[agent], telemetry=False).get_app()

    response = TestClient(app).get("/agents/private-agent")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "private-agent"
    assert "model" not in body
    assert "tools" not in body
    assert "system_message" not in body
    assert "response_settings" not in body


def test_agentos_can_opt_in_to_agent_config(monkeypatch):
    monkeypatch.delenv("OS_SECURITY_KEY", raising=False)
    agent = Agent(
        id="private-agent",
        name="Private Agent",
        model=_DummyModel(),
        instructions="Never reveal this instruction",
        system_message="Sensitive system prompt",
        tools=[_secret_tool],
    )
    app = AgentOS(agents=[agent], telemetry=False, expose_agent_config=True).get_app()

    response = TestClient(app).get("/agents/private-agent")

    assert response.status_code == 200
    body = response.json()
    assert "tools" in body
    assert "system_message" in body
    assert body["system_message"]["system_message"] == "Sensitive system prompt"
    assert body["system_message"]["instructions"] == "Never reveal this instruction"


def test_tool_call_sse_payloads_are_redacted_by_default():
    event = ToolCallCompletedEvent(
        agent_id="agent-1",
        run_id="run-1",
        tool=ToolExecution(
            tool_call_id="call-1",
            tool_name="lookup_secret",
            tool_args={"api_key": "sk-secret"},
            result="sensitive result",
        ),
        content="sensitive result",
    )

    sse_event = format_sse_event(event, stream_tool_payloads=False)

    assert sse_event is not None
    payload = _sse_payload(sse_event)
    assert payload["tool"]["tool_name"] == "lookup_secret"
    assert "tool_args" not in payload["tool"]
    assert "result" not in payload["tool"]
    assert "content" not in payload


def test_tool_call_sse_payloads_can_be_opted_in():
    event = ToolCallCompletedEvent(
        agent_id="agent-1",
        run_id="run-1",
        tool=ToolExecution(
            tool_call_id="call-1",
            tool_name="lookup_secret",
            tool_args={"api_key": "sk-secret"},
            result="sensitive result",
        ),
        content="sensitive result",
    )

    sse_event = format_sse_event(event, stream_tool_payloads=True)

    assert sse_event is not None
    payload = _sse_payload(sse_event)
    assert payload["tool"]["tool_args"] == {"api_key": "sk-secret"}
    assert payload["tool"]["result"] == "sensitive result"
    assert payload["content"] == "sensitive result"


def test_sse_events_to_skip_are_respected():
    event = ToolCallStartedEvent(
        agent_id="agent-1",
        run_id="run-1",
        tool=ToolExecution(tool_call_id="call-1", tool_name="lookup_secret"),
    )

    assert format_sse_event(event, events_to_skip=[RunEvent.tool_call_started]) is None


def test_already_formatted_sse_is_sanitized():
    event = ToolCallCompletedEvent(
        agent_id="agent-1",
        run_id="run-1",
        tool=ToolExecution(
            tool_call_id="call-1",
            tool_name="lookup_secret",
            tool_args={"api_key": "sk-secret"},
            result="sensitive result",
        ),
        content="sensitive result",
    )
    raw_event = format_sse_event(event, stream_tool_payloads=True)

    assert raw_event is not None
    sanitized = sanitize_sse_event(raw_event, stream_tool_payloads=False)

    assert sanitized is not None
    payload = _sse_payload(sanitized)
    assert "tool_args" not in payload["tool"]
    assert "result" not in payload["tool"]
    assert "content" not in payload


def test_agentos_stream_events_respects_component_setting():
    default_agent = Agent(id="default-agent", model=_DummyModel())
    disabled_agent = Agent(id="disabled-agent", model=_DummyModel(), stream_events=False)
    enabled_agent = Agent(id="enabled-agent", model=_DummyModel(), stream_events=True)

    assert resolve_stream_events(default_agent, {}) is True
    assert resolve_stream_events(disabled_agent, {}) is False
    assert resolve_stream_events(enabled_agent, {}) is True
    assert resolve_stream_events(disabled_agent, {"stream_events": True}) is True
