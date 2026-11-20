import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.tools.function import Function


def lookup() -> str:
    return "result"


class LimitScriptedModel(Model):
    """Requests a second tool call after the configured limit is exhausted."""

    def __init__(self) -> None:
        super().__init__(id="limit-scripted", provider="test")
        self.calls = 0

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls <= 2:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": f"call-{self.calls}",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": json.dumps({})},
                    }
                ],
                response_usage=MessageMetrics(),
            )
        raise AssertionError("the model must not be invoked after a limit error")

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def test_response_stops_after_tool_call_limit_error() -> None:
    model = LimitScriptedModel()
    messages = [Message(role="user", content="use the tool")]

    model.response(
        messages=messages,
        tools=[Function.from_callable(lookup)],
        tool_call_limit=1,
    )

    assert model.calls == 2
    assert messages[-1].tool_call_error is True
    assert messages[-1].stop_after_tool_call is True


@pytest.mark.asyncio
async def test_async_response_stops_after_tool_call_limit_error() -> None:
    model = LimitScriptedModel()
    messages = [Message(role="user", content="use the tool")]

    await model.aresponse(
        messages=messages,
        tools=[Function.from_callable(lookup)],
        tool_call_limit=1,
    )

    assert model.calls == 2
    assert messages[-1].tool_call_error is True
    assert messages[-1].stop_after_tool_call is True
