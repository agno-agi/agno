"""RunErrorEvent.error_type is populated on generic (non-guardrail) failures.

The guardrail handlers always passed error_type; the generic except-Exception
handlers emitted typeless events, which downstream same-error detection (the
rollout error-storm stop) could not use. error_type carries the AgnoError slug
when the exception has one, else the Python class name -- stability per failure
class, not a taxonomy.

When ``yield_run_output=True`` the streaming run also yields the canonical
failed ``RunOutput`` after the error event, so callers keep the durable tool
turns and the terminal state without a storage round-trip.
"""

from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent import Agent
from agno.exceptions import InputCheckError, ModelProviderError
from agno.guardrails.base import BaseGuardrail
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunErrorEvent, RunInput, RunOutput
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


class ToolThenErrorModel(ExplodingModel):
    """Run one real tool turn before the provider fails on its follow-up."""

    def __init__(self) -> None:
        super().__init__(RuntimeError("provider failed after durable tool"))
        self.calls = 0

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=[
                    {
                        "id": "durable-tool",
                        "type": "function",
                        "function": {"name": "record_effect", "arguments": "{}"},
                    }
                ]
            )
        raise self.exc

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()


class CompletedModel(Model):
    """Return ordinary content so a post-run guardrail owns the failure."""

    def __init__(self) -> None:
        super().__init__(id="completed", name="completed", provider="test")

    def __deepcopy__(self, memo: dict) -> "CompletedModel":
        return type(self)()

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse(content="ordinary model response")

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


class BlockingInputGuardrail(BaseGuardrail):
    def check(self, run_input: RunInput) -> None:
        raise InputCheckError("input guardrail rejected the run")

    async def async_check(self, run_input: RunInput) -> None:
        raise InputCheckError("input guardrail rejected the run")


def _assert_error_then_output(events: list[Any]) -> RunOutput:
    errors = [event for event in events if isinstance(event, RunErrorEvent)]
    outputs = [event for event in events if isinstance(event, RunOutput)]

    assert len(errors) == 1
    assert len(outputs) == 1
    assert events.index(errors[0]) < events.index(outputs[0])
    assert outputs[0].status == RunStatus.error
    return outputs[0]


def test_sync_stream_error_event_carries_class_name():
    agent = Agent(model=ExplodingModel(RuntimeError("boom")), telemetry=False)
    events = list(agent.run(input="hi", stream=True, stream_events=True))
    error_events = [event for event in events if isinstance(event, RunErrorEvent)]
    assert error_events
    assert all(event.error_type == "RuntimeError" for event in error_events)
    assert not any(isinstance(event, RunOutput) for event in events)


async def test_async_stream_error_event_carries_class_name():
    agent = Agent(model=ExplodingModel(RuntimeError("boom")), telemetry=False)
    events = [event async for event in agent.arun(input="hi", stream=True, stream_events=True)]
    error_events = [event for event in events if isinstance(event, RunErrorEvent)]
    assert error_events
    assert all(event.error_type == "RuntimeError" for event in error_events)
    assert not any(isinstance(event, RunOutput) for event in events)


def test_sync_stream_yield_run_output_returns_canonical_failed_tool_turn_without_storage():
    effects: list[str] = []

    def record_effect() -> str:
        effects.append("recorded")
        return "durable tool result"

    agent = Agent(model=ToolThenErrorModel(), tools=[record_effect], telemetry=False)
    assert agent.db is None
    assert agent.cache_session is False

    events = list(
        agent.run(
            input="record the effect, then continue",
            stream=True,
            stream_events=True,
            yield_run_output=True,
        )
    )

    output = _assert_error_then_output(events)
    assert effects == ["recorded"]
    assert [message.role for message in output.messages or []] == ["user", "assistant", "tool"]
    assert output.tools and output.tools[0].tool_call_id == "durable-tool"
    assert output.tools[0].result == "durable tool result"


async def test_async_stream_yield_run_output_returns_canonical_failed_tool_turn_without_storage():
    effects: list[str] = []

    def record_effect() -> str:
        effects.append("recorded")
        return "durable tool result"

    agent = Agent(model=ToolThenErrorModel(), tools=[record_effect], telemetry=False)
    assert agent.db is None
    assert agent.cache_session is False

    events = [
        event
        async for event in agent.arun(
            input="record the effect, then continue",
            stream=True,
            stream_events=True,
            yield_run_output=True,
        )
    ]

    output = _assert_error_then_output(events)
    assert effects == ["recorded"]
    assert [message.role for message in output.messages or []] == ["user", "assistant", "tool"]
    assert output.tools and output.tools[0].tool_call_id == "durable-tool"
    assert output.tools[0].result == "durable tool result"


def test_sync_initial_input_guardrail_yields_canonical_error_output_when_requested():
    agent = Agent(
        model=CompletedModel(),
        pre_hooks=[BlockingInputGuardrail()],
        telemetry=False,
    )

    events = list(
        agent.run(
            input="guard the initial request",
            stream=True,
            stream_events=True,
            yield_run_output=True,
        )
    )

    output = _assert_error_then_output(events)
    assert output.input and output.input.input_content == "guard the initial request"
    assert output.messages is None


async def test_async_initial_input_guardrail_yields_canonical_error_output_when_requested():
    agent = Agent(
        model=CompletedModel(),
        pre_hooks=[BlockingInputGuardrail()],
        telemetry=False,
    )

    events = [
        event
        async for event in agent.arun(
            input="guard the initial request",
            stream=True,
            stream_events=True,
            yield_run_output=True,
        )
    ]

    output = _assert_error_then_output(events)
    assert output.input and output.input.input_content == "guard the initial request"
    assert output.messages is None


def test_non_streaming_run_still_reports_error_status():
    # Non-streaming responses do not retain events; the sweep's observable contract
    # there is unchanged (status + content), pinned so the doors stay symmetric.
    agent = Agent(model=ExplodingModel(RuntimeError("boom")), telemetry=False)
    response = agent.run(input="hi")
    assert response.status == RunStatus.error
    assert "boom" in str(response.content)


def test_closing_at_canonical_error_output_preserves_terminal_state():
    from agno.db.in_memory import InMemoryDb

    agent = Agent(model=ExplodingModel(RuntimeError("boom")), db=InMemoryDb(), telemetry=False)
    events = agent.run("hi", stream=True, yield_run_output=True)
    output = next(event for event in events if isinstance(event, RunOutput))
    events.close()
    stored = agent.get_run_output(run_id=output.run_id, session_id=output.session_id)
    assert output.status == stored.status == RunStatus.error
    assert [message.to_dict() for message in stored.messages] == [message.to_dict() for message in output.messages]


@pytest.mark.asyncio
async def test_aclosing_at_canonical_error_output_preserves_terminal_state():
    from agno.db.in_memory import InMemoryDb

    agent = Agent(model=ExplodingModel(RuntimeError("boom")), db=InMemoryDb(), telemetry=False)
    events = agent.arun("hi", stream=True, yield_run_output=True)
    async for event in events:
        if isinstance(event, RunOutput):
            output = event
            break
    else:
        pytest.fail("missing canonical error output")
    await events.aclose()
    stored = await agent.aget_run_output(run_id=output.run_id, session_id=output.session_id)
    assert output.status == stored.status == RunStatus.error
    assert [message.to_dict() for message in stored.messages] == [message.to_dict() for message in output.messages]


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
