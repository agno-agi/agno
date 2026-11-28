"""A tasks-mode run that creates no tasks must end by answering, not by burning
max_iterations: an empty list never satisfies all_terminal, so before the idle-turn
check a greeting looped ten times."""

from typing import Iterator

import pytest

from agno.agent import Agent
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.team.team import Team


class CountingMockModel(Model):
    """Offline model that answers with plain text, never calls a tool, and counts invocations."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self.invocations = 0

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response) -> ModelResponse:
        return response

    def _response(self) -> ModelResponse:
        self.invocations += 1
        return ModelResponse(content="Hello there.", role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._response()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._response()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._response()

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._response()


def _tasks_team(model: Model) -> Team:
    member = Agent(name="Helper", id="helper", model=model)
    return Team(model=model, members=[member], mode="tasks", telemetry=False)


def test_no_task_run_ends_after_the_reminder_turn():
    model = CountingMockModel()
    team = _tasks_team(model)
    output = team.run("Hi! Say hello.")
    assert output.content
    # First answer, one reminder turn, done — never the full max_iterations (10).
    assert model.invocations <= 3, model.invocations


@pytest.mark.asyncio
async def test_no_task_run_ends_after_the_reminder_turn_async():
    model = CountingMockModel()
    team = _tasks_team(model)
    output = await team.arun("Hi! Say hello.")
    assert output.content
    assert model.invocations <= 3, model.invocations
