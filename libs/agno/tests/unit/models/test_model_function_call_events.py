from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator, List

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import CustomEvent
from agno.tools.decorator import tool
from agno.tools.function import FunctionCall


class DummyModel(Model):
    """Minimal concrete Model to exercise run_function_call in isolation."""

    def __init__(self):
        super().__init__(id="dummy-model")

    def invoke(self, *args, **kwargs) -> ModelResponse:  # pragma: no cover - not used in these tests
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:  # pragma: no cover - not used in these tests
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:  # pragma: no cover
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:  # pragma: no cover
        raise NotImplementedError

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:  # pragma: no cover
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:  # pragma: no cover
        raise NotImplementedError


def test_custom_events_do_not_pollute_function_outputs():
    @dataclass
    class ProcessingStatusEvent(CustomEvent):
        status: str = ""

    @tool()
    def get_document(doc_id: str):
        yield ProcessingStatusEvent(status="searching")
        yield "<doc>document content</doc>"

    model = DummyModel()
    function_call = FunctionCall(function=get_document, arguments={"doc_id": "123"}, call_id="call_1")
    function_call_results: List[Any] = []

    responses = list(
        model.run_function_call(function_call=function_call, function_call_results=function_call_results)
    )

    telemetry_events = [evt for evt in responses if isinstance(evt, ProcessingStatusEvent)]
    assert telemetry_events, "Telemetry CustomEvent should bubble through run_function_call"
    assert len(function_call_results) == 1

    tool_message = function_call_results[0]
    assert tool_message.tool_call_error is False
    assert tool_message.content == "<doc>document content</doc>"
    assert "ProcessingStatusEvent" not in tool_message.content

