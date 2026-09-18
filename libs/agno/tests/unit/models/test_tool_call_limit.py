from typing import Any, AsyncIterator, Iterator

from agno.models.base import Model
from agno.models.response import ModelResponse


class StubModel(Model):
    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise NotImplementedError

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise NotImplementedError

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise NotImplementedError


def test_tool_choice_is_disabled_after_tool_call_limit():
    model = StubModel(id="stub")
    forced_tool = {"type": "function", "function": {"name": "search"}}
    model._tool_choice = forced_tool

    assert model._get_tool_choice_for_call(forced_tool, function_call_count=0, tool_call_limit=3) == forced_tool
    assert model._get_tool_choice_for_call(forced_tool, function_call_count=2, tool_call_limit=3) == forced_tool
    assert model._get_tool_choice_for_call(forced_tool, function_call_count=3, tool_call_limit=3) == "none"
    assert model._get_tool_choice_for_call(forced_tool, function_call_count=4, tool_call_limit=None) == forced_tool
