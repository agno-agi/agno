"""strip_reasoning_from_history replays earlier runs without their reasoning, on Agent and Team.

Runs the full run()/arun() path against an offline model that returns reasoning with a provider
signature, then checks what the second run sends to the model.
"""

from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.team import Team


class ReasoningModel(Model):
    """Offline model: answers with reasoning and a provider signature, records every request."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.requests: List[List[Message]] = []

    def _answer(self, messages: List[Message]) -> ModelResponse:
        self.requests.append(list(messages))
        return ModelResponse(
            role="assistant",
            content="ok",
            reasoning_content="private reasoning",
            provider_data={"signature": "SIG", "response_id": "resp_1"},
            response_usage=MessageMetrics(),
        )

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, messages: List[Message], *args: Any, **kwargs: Any) -> ModelResponse:
        return self._answer(messages)

    async def ainvoke(self, messages: List[Message], *args: Any, **kwargs: Any) -> ModelResponse:
        return self._answer(messages)

    def invoke_stream(self, messages: List[Message], *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._answer(messages)

    async def ainvoke_stream(self, messages: List[Message], *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._answer(messages)

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _history_assistants(model: ReasoningModel) -> List[Message]:
    return [m for m in model.requests[-1] if m.role == "assistant" and m.from_history]


def _agent(model: ReasoningModel, strip: bool) -> Agent:
    return Agent(
        model=model,
        db=InMemoryDb(),
        add_history_to_context=True,
        strip_reasoning_from_history=strip,
        telemetry=False,
    )


def _team(model: ReasoningModel, strip: bool) -> Team:
    return Team(
        model=model,
        members=[],
        db=InMemoryDb(),
        add_history_to_context=True,
        strip_reasoning_from_history=strip,
        telemetry=False,
    )


@pytest.mark.parametrize("build", [_agent, _team], ids=["agent", "team"])
def test_history_keeps_reasoning_by_default(build):
    model = ReasoningModel()
    runner = build(model, strip=False)

    runner.run("first", session_id="s")
    runner.run("second", session_id="s")

    [assistant] = _history_assistants(model)
    assert assistant.reasoning_content == "private reasoning"
    assert assistant.provider_data["signature"] == "SIG"


@pytest.mark.parametrize("build", [_agent, _team], ids=["agent", "team"])
def test_history_is_stripped_when_enabled(build):
    model = ReasoningModel()
    runner = build(model, strip=True)

    runner.run("first", session_id="s")
    runner.run("second", session_id="s")

    [assistant] = _history_assistants(model)
    assert assistant.reasoning_content is None
    assert assistant.provider_data == {"response_id": "resp_1"}
    assert assistant.content == "ok"
    # The stored session keeps the reasoning; only the request is cleaned.
    stored = runner.get_session(session_id="s").runs[0].messages
    assert any(m.role == "assistant" and m.reasoning_content == "private reasoning" for m in stored)


@pytest.mark.asyncio
@pytest.mark.parametrize("build", [_agent, _team], ids=["agent", "team"])
async def test_history_is_stripped_when_enabled_async(build):
    model = ReasoningModel()
    runner = build(model, strip=True)

    await runner.arun("first", session_id="s")
    await runner.arun("second", session_id="s")

    [assistant] = _history_assistants(model)
    assert assistant.reasoning_content is None
    assert "signature" not in (assistant.provider_data or {})


@pytest.mark.parametrize("build", [_agent, _team], ids=["agent", "team"])
def test_setting_survives_config_round_trip(build):
    runner = build(ReasoningModel(), strip=True)
    config = runner.to_dict()
    assert config["strip_reasoning_from_history"] is True
