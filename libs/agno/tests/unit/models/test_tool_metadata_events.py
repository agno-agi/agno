from dataclasses import dataclass
from typing import Any

import pytest

from agno.models.base import Model
from agno.models.response import ModelResponseEvent, ToolExecution
from agno.tools.decorator import tool
from agno.tools.function import Function, FunctionCall
from agno.tools.toolkit import Toolkit


@dataclass
class StubModel(Model):
    """Minimal concrete Model so the real run_function_call(s) path can be exercised.

    The abstract provider methods are never called: run_function_call(s) only executes the
    FunctionCall locally and constructs the ToolExecution surfaced on the completed event.
    """

    id: str = "stub"

    def invoke(self, *args, **kwargs):
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs):
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs):
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs):
        raise NotImplementedError

    def _parse_provider_response(self, response: Any, **kwargs):
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any):
        raise NotImplementedError


def _completed_tool_execution(model_responses) -> ToolExecution:
    completed = [r for r in model_responses if r.event == ModelResponseEvent.tool_call_completed.value]
    assert completed, "expected a tool_call_completed ModelResponse"
    tool_executions = completed[0].tool_executions
    assert tool_executions, "expected tool_executions on the completed response"
    return tool_executions[0]


def test_tool_decorator_sets_function_metadata():
    @tool(metadata={"data_mutation": True, "domain": "shifts"})
    def update_shift() -> str:
        return "updated"

    assert update_shift.metadata == {"data_mutation": True, "domain": "shifts"}


def test_run_function_call_completed_event_includes_tool_metadata():
    @tool(metadata={"data_mutation": True})
    def update_shift() -> str:
        return "updated"

    fc = FunctionCall(function=update_shift, arguments={}, call_id="call_1")

    responses = list(StubModel().run_function_call(function_call=fc, function_call_results=[]))

    tool_execution = _completed_tool_execution(responses)
    assert tool_execution.tool_metadata == {"data_mutation": True}


@pytest.mark.asyncio
async def test_arun_function_calls_completed_event_includes_tool_metadata():
    @tool(metadata={"data_mutation": True})
    def update_shift() -> str:
        return "updated"

    fc = FunctionCall(function=update_shift, arguments={}, call_id="call_1")

    responses = [r async for r in StubModel().arun_function_calls(function_calls=[fc], function_call_results=[])]

    tool_execution = _completed_tool_execution(responses)
    assert tool_execution.tool_metadata == {"data_mutation": True}


def test_completed_event_tool_metadata_none_when_not_set():
    @tool
    def read_shift() -> str:
        return "shift"

    fc = FunctionCall(function=read_shift, arguments={}, call_id="call_1")

    responses = list(StubModel().run_function_call(function_call=fc, function_call_results=[]))

    tool_execution = _completed_tool_execution(responses)
    assert tool_execution.tool_metadata is None


def test_tool_execution_metadata_roundtrips_through_dict():
    tool_execution = ToolExecution(
        tool_call_id="call_1",
        tool_name="update_shift",
        tool_metadata={"data_mutation": True},
    )

    restored = ToolExecution.from_dict(tool_execution.to_dict())

    assert restored.tool_metadata == {"data_mutation": True}


def test_function_metadata_roundtrips_through_dict():
    function = Function(name="update_shift", metadata={"data_mutation": True})

    assert function.to_dict()["metadata"] == {"data_mutation": True}
    assert Function.from_dict(function.to_dict()).metadata == {"data_mutation": True}


def test_toolkit_preserves_decorated_tool_metadata():
    class ShiftToolkit(Toolkit):
        def __init__(self):
            super().__init__(name="shift_toolkit", tools=[self.update_shift])

        @tool(metadata={"data_mutation": True})
        def update_shift(self) -> str:
            return "updated"

    toolkit = ShiftToolkit()

    assert toolkit.functions["update_shift"].metadata == {"data_mutation": True}
