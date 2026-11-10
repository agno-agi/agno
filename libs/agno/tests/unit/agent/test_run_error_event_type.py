"""RunErrorEvent.error_type is populated on generic (non-guardrail) failures.

The guardrail handlers always passed error_type; the generic except-Exception
handlers emitted typeless events, which downstream same-error detection (the
rollout error-storm stop) could not use. error_type carries the AgnoError slug
when the exception has one, else the Python class name -- stability per failure
class, not a taxonomy.
"""

from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent import Agent
from agno.exceptions import InputCheckError, ModelProviderError, OutputCheckError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.agent import RunErrorEvent, RunOutput
from agno.run.base import RunStatus


class ExplodingModel(Model):
    def __init__(self, exc: BaseException) -> None:
        super().__init__(id="exploding", name="exploding", provider="test")
        self.exc = exc

    def __deepcopy__(self, memo: dict) -> "ExplodingModel":
        return type(self)(exc=self.exc)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise self.exc

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise self.exc

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise self.exc
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise self.exc
        yield  # pragma: no cover

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def test_sync_stream_error_event_carries_class_name():
    agent = Agent(model=ExplodingModel(RuntimeError("boom")), telemetry=False)
    events = list(agent.run(input="hi", stream=True, stream_events=True))
    error_events = [event for event in events if isinstance(event, RunErrorEvent)]
    assert error_events
    assert all(event.error_type == "RuntimeError" for event in error_events)


async def test_async_stream_error_event_carries_class_name():
    agent = Agent(model=ExplodingModel(RuntimeError("boom")), telemetry=False)
    events = [event async for event in agent.arun(input="hi", stream=True, stream_events=True)]
    error_events = [event for event in events if isinstance(event, RunErrorEvent)]
    assert error_events
    assert all(event.error_type == "RuntimeError" for event in error_events)


def test_non_streaming_run_still_reports_error_status():
    # Non-streaming responses do not retain events; the sweep's observable contract
    # there is unchanged (status + content), pinned so the doors stay symmetric.
    agent = Agent(model=ExplodingModel(RuntimeError("boom")), telemetry=False)
    response = agent.run(input="hi")
    assert response.status == RunStatus.error
    assert "boom" in str(response.content)


def test_error_type_of_prefers_agno_slug():
    from agno.utils.events import error_type_of

    assert error_type_of(RuntimeError("x")) == "RuntimeError"
    assert error_type_of(ModelProviderError(message="x")) == "model_provider_error"


async def test_agno_error_keeps_its_slug():
    # Typed agno exceptions keep the same snake_case slug the guardrail handlers
    # emit, so the field's vocabulary stays consistent across handler kinds.
    agent = Agent(model=ExplodingModel(ModelProviderError(message="provider down")), telemetry=False)
    events = [event async for event in agent.arun(input="hi", stream=True, stream_events=True)]
    error_events = [event for event in events if isinstance(event, RunErrorEvent)]
    assert error_events
    assert all(event.error_type == "model_provider_error" for event in error_events)


@pytest.mark.parametrize("error_type", [ModelProviderError, InputCheckError, OutputCheckError])
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("yield_run_output", [False, True])
async def test_continuation_error_yields_final_output_when_requested(error_type, async_mode, yield_run_output):
    agent = Agent(model=ExplodingModel(error_type("boom")), telemetry=False)
    previous = RunOutput(
        run_id="run",
        session_id="session",
        status=RunStatus.paused,
        messages=[Message(role="user", content="hi")],
        content="Earlier answer",
    )
    if async_mode:
        events = [
            event
            async for event in agent.acontinue_run(
                previous, stream=True, stream_events=True, yield_run_output=yield_run_output
            )
        ]
    else:
        events = list(agent.continue_run(previous, stream=True, stream_events=True, yield_run_output=yield_run_output))

    errors = [event for event in events if isinstance(event, RunErrorEvent)]
    assert len(errors) == 1
    assert errors[0].content == "boom"
    outputs = [event for event in events if isinstance(event, RunOutput)]
    if yield_run_output:
        assert len(outputs) == 1
        assert events[-1] is outputs[0]
        assert outputs[0].status == RunStatus.error
        assert outputs[0].run_id == errors[0].run_id == "run"
        assert outputs[0].session_id == errors[0].session_id == "session"
        assert outputs[0].content == "Earlier answer"
    else:
        assert outputs == []
