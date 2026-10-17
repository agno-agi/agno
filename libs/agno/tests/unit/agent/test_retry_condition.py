from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunErrorEvent, RunOutput
from agno.run.base import RunStatus


class FailingModel(Model):
    def __init__(self) -> None:
        super().__init__(id="failing", name="failing", provider="test")
        self.calls = 0
        self.error: Exception | None = None
        self.mock_response = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.mock_response

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


async def run_agent(agent: Agent, *, async_mode: bool, stream: bool, run_response: RunOutput | None = None):
    if run_response is None:
        method = agent.arun if async_mode else agent.run
        result = method(input="hello", stream=stream, yield_run_output=stream, session_id="retry-condition")
    else:
        method = agent.acontinue_run if async_mode else agent.continue_run
        result = method(
            run_response=run_response,
            stream=stream,
            yield_run_output=stream,
            session_id="retry-condition",
        )

    if stream:
        outputs = [event async for event in result] if async_mode else list(result)
        return outputs[-1]
    return await result if async_mode else result


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("continuing", [False, True])
async def test_retry_condition_can_stop_all_agent_retry_paths(async_mode: bool, stream: bool, continuing: bool):
    model = FailingModel()
    inspected_errors = []
    agent = Agent(
        model=model,
        db=InMemoryDb(),
        retries=2,
        delay_between_retries=0,
        retry_condition=lambda error: inspected_errors.append(error) or False,
        telemetry=False,
    )

    previous_run = await run_agent(agent, async_mode=async_mode, stream=False) if continuing else None
    model.calls = 0
    model.error = RuntimeError("capacity exhausted")

    response = await run_agent(agent, async_mode=async_mode, stream=stream, run_response=previous_run)

    if stream:
        assert isinstance(response, RunErrorEvent)
    else:
        assert response.status == RunStatus.error
    assert model.calls == 1
    assert inspected_errors == [model.error]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_retry_condition_can_allow_retries(async_mode: bool, stream: bool):
    model = FailingModel()
    inspected_errors = []
    model.error = RuntimeError("transient failure")
    agent = Agent(
        model=model,
        retries=2,
        delay_between_retries=0,
        retry_condition=lambda error: inspected_errors.append(error) or True,
        telemetry=False,
    )

    response = await run_agent(agent, async_mode=async_mode, stream=stream)

    if stream:
        assert isinstance(response, RunErrorEvent)
    else:
        assert response.status == RunStatus.error
    assert model.calls == 3
    assert inspected_errors == [model.error, model.error]


def test_retry_condition_is_not_called_without_a_remaining_attempt():
    model = FailingModel()
    model.error = RuntimeError("failure")
    inspected_errors = []
    agent = Agent(
        model=model,
        retries=0,
        retry_condition=lambda error: inspected_errors.append(error) or True,
        telemetry=False,
    )

    response = agent.run("hello")

    assert response.status == RunStatus.error
    assert model.calls == 1
    assert inspected_errors == []
