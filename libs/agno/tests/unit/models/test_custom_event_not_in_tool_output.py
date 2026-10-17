"""CustomEvent must not be stringified into tool call results (GitHub #9386)."""

from dataclasses import dataclass

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.agent import CustomEvent
from agno.tools.function import Function, FunctionCall


@dataclass
class ProgressEvent(CustomEvent):
    content: str = ""


class _DummyModel(Model):
    def __init__(self):
        super().__init__(id="dummy", name="dummy", provider="test")

    def invoke(self, *args, **kwargs) -> ModelResponse:
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs):
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs):
        raise NotImplementedError

    def _parse_provider_response(self, *args, **kwargs) -> ModelResponse:
        raise NotImplementedError

    def _parse_provider_response_delta(self, *args, **kwargs) -> ModelResponse:
        raise NotImplementedError


def test_custom_event_excluded_from_sync_generator_tool_output():
    def demo_tool():
        yield ProgressEvent(content="Starting analysis...")
        yield "Analysis complete"

    function = Function(name="demo", entrypoint=demo_tool)
    function_call = FunctionCall(function=function, arguments={}, call_id="call_1")
    results: list[Message] = []

    chunks = list(_DummyModel().run_function_call(function_call, results))

    custom = [c for c in chunks if isinstance(c, ProgressEvent)]
    assert len(custom) == 1
    assert custom[0].content == "Starting analysis..."
    assert custom[0].tool_call_id == "call_1"

    completed = [
        c
        for c in chunks
        if isinstance(c, ModelResponse) and c.event == "ToolCallCompleted" and c.tool_executions
    ]
    assert completed
    tool_result = completed[-1].tool_executions[0].result
    assert tool_result == "Analysis complete"
    assert "CustomEvent" not in str(tool_result)
    assert "ProgressEvent" not in str(tool_result)
    assert "Starting analysis" not in str(tool_result)
