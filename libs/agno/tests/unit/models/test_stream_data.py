from collections.abc import AsyncIterator, Iterator
from typing import Any

from agno.models.base import MessageData, Model
from agno.models.response import ModelResponse


class _DummyModel(Model):
    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        return iter(())

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        if False:
            yield ModelResponse()

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return ModelResponse()


def test_empty_tool_call_delta_is_not_yielded() -> None:
    model = _DummyModel(id="test")
    stream_data = MessageData()
    delta = ModelResponse(tool_calls=[])

    yielded = list(model._populate_stream_data(stream_data, delta))

    assert yielded == []
    assert stream_data.response_tool_calls == []


def test_non_empty_tool_call_delta_is_yielded() -> None:
    model = _DummyModel(id="test")
    stream_data = MessageData()
    tool_call = {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{}"}}
    delta = ModelResponse(tool_calls=[tool_call])

    yielded = list(model._populate_stream_data(stream_data, delta))

    assert yielded == [delta]
    assert stream_data.response_tool_calls == [tool_call]
