"""Inspect Agent and Team model requests offline, without provider credentials."""

import asyncio
from typing import Any, AsyncIterator, Iterator, Union

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run import PreparedAgentModelRequest, PreparedTeamModelRequest
from agno.team import Team
from agno.tools.function import Function
from pydantic import BaseModel


# -----------------------------------------------------------------------------
# Offline model: an accidental generation call fails immediately.
# -----------------------------------------------------------------------------
class InspectionModel(Model):
    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise AssertionError("Inspection must not invoke the model")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise AssertionError("Inspection must not invoke the model")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise AssertionError("Inspection must not invoke the model")

    async def ainvoke_stream(
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[ModelResponse]:
        raise AssertionError("Inspection must not invoke the model")
        yield ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class Summary(BaseModel):
    summary: str


def echo(text: str) -> str:
    """Repeat text exactly."""
    return text


def show_request(
    prepared: Union[PreparedAgentModelRequest, PreparedTeamModelRequest],
) -> None:
    for message in prepared.messages:
        print(f"{message.role}: {message.content}")
    print(
        "Tool schemas:",
        [item.to_dict() for item in prepared.tools if isinstance(item, Function)],
    )
    print("Response format:", prepared.response_format)
    print("Session:", prepared.run_context.session_id)
    assert prepared.run_response.content is None
    assert prepared.response_format is Summary


# -----------------------------------------------------------------------------
# Reuse these instances for sync and async inspection.
# -----------------------------------------------------------------------------
agent = Agent(
    name="Inspector",
    model=InspectionModel(
        id="offline", provider="example", supports_native_structured_outputs=True
    ),
    instructions="Be concise.",
    tools=[echo],
    output_schema=Summary,
    telemetry=False,
)
team = Team(
    name="Inspection team",
    model=InspectionModel(
        id="offline", provider="example", supports_native_structured_outputs=True
    ),
    members=[agent],
    output_schema=Summary,
    telemetry=False,
)


async def main() -> None:
    show_request(agent.prepare_model_request("Hello", session_id="agent-sync"))
    show_request(await agent.aprepare_model_request("Hello", session_id="agent-async"))
    show_request(team.prepare_model_request("Hello", session_id="team-sync"))
    show_request(await team.aprepare_model_request("Hello", session_id="team-async"))


if __name__ == "__main__":
    asyncio.run(main())
