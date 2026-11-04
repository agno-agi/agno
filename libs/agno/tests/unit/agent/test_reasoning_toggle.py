"""Tests for per-run reasoning overrides."""

from typing import Any, AsyncIterator, Iterator, Optional

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent, _response
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS
from agno.run.agent import RunOutput
from agno.run.messages import RunMessages


class ScriptedModel(Model):
    """A model that answers without a provider call."""

    def __init__(self):
        super().__init__(id="scripted", name="scripted", provider="test")

    def _response(self) -> ModelResponse:
        return ModelResponse(content="answer", role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._response()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._response()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._response()

    def parse_args(self, *args: Any, **kwargs: Any) -> dict:
        return {}

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return self._response()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._response()


def _make_agent() -> Agent:
    model = ScriptedModel()
    return Agent(model=model, reasoning_model=model)


def test_reasoning_handlers_skip_reasoning_when_disabled(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def reason(**kwargs: Any):
        calls.append(kwargs)
        return iter(())

    monkeypatch.setattr(_response, "reason", reason)
    agent = _make_agent()
    run_response = RunOutput(run_id="run", session_id="session")
    run_messages = RunMessages()

    _response.handle_reasoning(agent, run_response, run_messages, reasoning=False)
    assert calls == []

    _response.handle_reasoning(agent, run_response, run_messages, reasoning=True)
    assert len(calls) == 1


def test_reasoning_stream_handler_skips_reasoning_when_disabled(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def reason(**kwargs: Any):
        calls.append(kwargs)
        return iter(())

    monkeypatch.setattr(_response, "reason", reason)
    agent = _make_agent()
    run_response = RunOutput(run_id="run", session_id="session")

    assert list(_response.handle_reasoning_stream(agent, run_response, RunMessages(), reasoning=False)) == []
    assert calls == []

    list(_response.handle_reasoning_stream(agent, run_response, RunMessages(), reasoning=True))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_async_reasoning_handlers_skip_reasoning_when_disabled(monkeypatch: pytest.MonkeyPatch):
    calls = []

    async def areason(**kwargs: Any):
        calls.append(kwargs)
        yield None

    monkeypatch.setattr(_response, "areason", areason)
    agent = _make_agent()
    run_response = RunOutput(run_id="run", session_id="session")
    run_messages = RunMessages()

    await _response.ahandle_reasoning(agent, run_response, run_messages, reasoning=False)
    assert calls == []

    await _response.ahandle_reasoning(agent, run_response, run_messages, reasoning=True)
    assert len(calls) == 1

    async for _ in _response.ahandle_reasoning_stream(agent, run_response, run_messages, reasoning=False):
        pytest.fail("Reasoning should not yield when disabled")
    assert len(calls) == 1

    async for _ in _response.ahandle_reasoning_stream(agent, run_response, run_messages, reasoning=True):
        pass
    assert len(calls) == 2


@pytest.mark.parametrize("reasoning", [False, True, None])
def test_run_uses_reasoning_override_without_mutating_agent(monkeypatch: pytest.MonkeyPatch, reasoning: Optional[bool]):
    calls = []

    def handle_reasoning(*args: Any, reasoning: Optional[bool] = None, **kwargs: Any) -> None:
        calls.append(reasoning)

    monkeypatch.setattr(_response, "handle_reasoning", handle_reasoning)
    agent = _make_agent()

    agent.run("hello", reasoning=reasoning)

    assert calls == [reasoning]
    assert agent.reasoning_model is agent.model


@pytest.mark.asyncio
@pytest.mark.parametrize("reasoning", [False, True, None])
async def test_arun_uses_reasoning_override_without_mutating_agent(
    monkeypatch: pytest.MonkeyPatch, reasoning: Optional[bool]
):
    calls = []

    async def handle_reasoning(*args: Any, reasoning: Optional[bool] = None, **kwargs: Any) -> None:
        calls.append(reasoning)

    monkeypatch.setattr(_response, "ahandle_reasoning", handle_reasoning)
    agent = _make_agent()

    await agent.arun("hello", reasoning=reasoning)

    assert calls == [reasoning]
    assert agent.reasoning_model is agent.model


def test_stream_run_uses_reasoning_override(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def handle_reasoning_stream(*args: Any, reasoning: Optional[bool] = None, **kwargs: Any):
        calls.append(reasoning)
        return iter(())

    monkeypatch.setattr(_response, "handle_reasoning_stream", handle_reasoning_stream)
    agent = _make_agent()

    list(agent.run("hello", stream=True, reasoning=False))

    assert calls == [False]


@pytest.mark.asyncio
async def test_async_stream_run_uses_reasoning_override(monkeypatch: pytest.MonkeyPatch):
    calls = []

    async def handle_reasoning_stream(*args: Any, reasoning: Optional[bool] = None, **kwargs: Any):
        calls.append(reasoning)
        if False:
            yield None

    monkeypatch.setattr(_response, "ahandle_reasoning_stream", handle_reasoning_stream)
    agent = _make_agent()

    async for _ in agent.arun("hello", stream=True, reasoning=False):
        pass

    assert calls == [False]


@pytest.mark.parametrize(("value", "expected"), [("true", True), ("false", False), (None, None)])
def test_agent_os_run_accepts_per_request_reasoning(value, expected, monkeypatch: pytest.MonkeyPatch):
    calls = []

    async def handle_reasoning(*args: Any, reasoning: Optional[bool] = None, **kwargs: Any) -> None:
        calls.append(reasoning)

    monkeypatch.setattr(_response, "ahandle_reasoning", handle_reasoning)
    agent = _make_agent()
    client = TestClient(AgentOS(agents=[agent], telemetry=False).get_app())
    data = {"message": "hello", "stream": "false"}
    if value is not None:
        data["reasoning"] = value

    response = client.post(f"/agents/{agent.id}/runs", data=data)

    assert response.status_code == 200, response.text
    assert calls == [expected]
    assert agent.reasoning_model is agent.model
