from typing import Any, AsyncIterator, Iterator

import pytest

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import PreparedTeamModelRequest
from agno.team import Team
from agno.tools import tool
from agno.tools.function import Function


class InspectOnlyModel(Model):
    def __init__(self):
        super().__init__(id="inspect-model", name="inspect-model", provider="test")
        self.invoke_calls = 0
        self.ainvoke_calls = 0

    def get_instructions_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_system_message_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def aget_instructions_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def aget_system_message_for_model(self, *args: Any, **kwargs: Any) -> None:
        return None

    def parse_args(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.invoke_calls += 1
        raise AssertionError("prepare_model_request must not invoke the model")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.ainvoke_calls += 1
        raise AssertionError("aprepare_model_request must not invoke the model")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        self.invoke_calls += 1
        raise AssertionError("prepare_model_request must not invoke the model")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        self.ainvoke_calls += 1
        raise AssertionError("aprepare_model_request must not invoke the model")
        yield ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse()


def test_prepare_model_request_returns_team_messages_tools_and_context():
    @tool(instructions="Use team echo for exact repeats.")
    def team_echo(text: str) -> str:
        return text

    model = InspectOnlyModel()
    team = Team(
        name="Inspection Team",
        model=model,
        members=[],
        instructions="Coordinate carefully.",
        tools=[team_echo],
    )

    prepared = team.prepare_model_request(
        "hello team",
        session_id="team-session-1",
        user_id="team-user-1",
        run_id="team-run-1",
        metadata={"source": "test"},
    )

    assert isinstance(prepared, PreparedTeamModelRequest)
    assert prepared.run_response.run_id == "team-run-1"
    assert prepared.run_response.session_id == "team-session-1"
    assert prepared.run_context.user_id == "team-user-1"
    assert prepared.run_context.metadata == {"source": "test"}
    assert prepared.session.session_id == "team-session-1"
    assert prepared.user_message is not None
    assert prepared.user_message.content == "hello team"
    assert prepared.system_message is not None
    assert "Coordinate carefully." in str(prepared.system_message.content)
    assert prepared.messages == prepared.run_messages.messages
    assert [tool.name for tool in prepared.tools if isinstance(tool, Function)] == ["team_echo"]
    assert prepared.tool_instructions == ["Use team echo for exact repeats."]
    assert model.invoke_calls == 0
    assert model.ainvoke_calls == 0


@pytest.mark.asyncio
async def test_aprepare_model_request_supports_async_team_tools_without_model_invocation():
    @tool(instructions="Use async team echo for exact repeats.")
    async def async_team_echo(text: str) -> str:
        return text

    model = InspectOnlyModel()
    team = Team(name="Async Inspection Team", model=model, members=[], tools=[async_team_echo])

    prepared = await team.aprepare_model_request(
        "hello async team",
        session_id="team-session-async",
        user_id="team-user-async",
        run_id="team-run-async",
    )

    assert prepared.run_response.run_id == "team-run-async"
    assert prepared.user_message is not None
    assert prepared.user_message.content == "hello async team"
    assert [tool.name for tool in prepared.tools if isinstance(tool, Function)] == ["async_team_echo"]
    assert prepared.tool_instructions == ["Use async team echo for exact repeats."]
    assert model.invoke_calls == 0
    assert model.ainvoke_calls == 0
