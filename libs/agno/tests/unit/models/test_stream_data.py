from collections.abc import AsyncIterator, Iterator
from typing import Any

from agno.models.base import MessageData, Model
from agno.models.response import ModelResponse


class _StreamDataModel(Model):
    def __init__(self) -> None:
        super().__init__(id="stream-data-test", provider="test")

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise NotImplementedError
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise NotImplementedError
        yield  # pragma: no cover

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise NotImplementedError


def test_empty_tool_calls_do_not_yield_a_stream_delta() -> None:
    model = _StreamDataModel()
    stream_data = MessageData()

    deltas = list(model._populate_stream_data(stream_data, ModelResponse()))

    assert deltas == []
    assert stream_data.response_tool_calls == []


def test_non_empty_tool_calls_yield_and_accumulate() -> None:
    model = _StreamDataModel()
    stream_data = MessageData()
    response_delta = ModelResponse(tool_calls=[{"id": "call_1", "function": {"name": "search"}}])

    deltas = list(model._populate_stream_data(stream_data, response_delta))

    assert deltas == [response_delta]
    assert stream_data.response_tool_calls == response_delta.tool_calls
