"""Unit tests verifying that stop_after_tool_call prevents subsequent tool calls in the same batch from executing.

Agno Issue #9201: Later tool calls execute past a declared stop_after_tool_call batch boundary.
"""

from typing import Any, AsyncIterator, Iterator, List
from unittest.mock import MagicMock

import pytest

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.tools.function import Function, FunctionCall


class _StubModel(Model):
    def __init__(self):
        super().__init__(id="stub", name="stub", provider="stub")
        self.invoke_responses: List[ModelResponse] = []
        self.ainvoke_responses: List[ModelResponse] = []

    def invoke(self, *args, **kwargs) -> ModelResponse:
        if self.invoke_responses:
            return self.invoke_responses.pop(0)
        return ModelResponse(role="assistant", content="Done")

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        if self.ainvoke_responses:
            return self.ainvoke_responses.pop(0)
        return ModelResponse(role="assistant", content="Done")

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        raise NotImplementedError

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise NotImplementedError


def _make_function_call(name: str, stop_after_tool_call: bool, mock_fn: MagicMock) -> FunctionCall:
    def tool() -> str:
        return mock_fn()

    func = Function.from_callable(tool, name=name)
    func.stop_after_tool_call = stop_after_tool_call
    func.process_entrypoint()
    return FunctionCall(function=func, arguments={}, call_id=f"call_{name}")


# ---------------------------------------------------------------------------
# Tests for run_function_calls (sync)
# ---------------------------------------------------------------------------


def test_sync_batch_first_tool_stops_subsequent_tool_not_invoked():
    """When a model returns a batch of 2 tool calls and the first has stop_after_tool_call=True,
    the second tool call is never invoked."""
    tool1_mock = MagicMock(return_value="result_1")
    tool2_mock = MagicMock(return_value="result_2")

    fc1 = _make_function_call("tool1", stop_after_tool_call=True, mock_fn=tool1_mock)
    fc2 = _make_function_call("tool2", stop_after_tool_call=False, mock_fn=tool2_mock)

    model = _StubModel()
    results: List[Message] = []
    list(model.run_function_calls([fc1, fc2], function_call_results=results))

    assert tool1_mock.call_count == 1
    assert tool2_mock.call_count == 0

    assert len(results) == 2
    assert results[0].tool_name == "tool1"
    assert results[0].stop_after_tool_call is True
    assert results[1].tool_name == "tool2"
    assert results[1].tool_call_id == "call_tool2"
    assert "skipped" in str(results[1].content)


def test_sync_batch_neither_tool_stops_both_executed():
    """When neither tool call requests stop_after_tool_call, both tool calls execute normally."""
    tool1_mock = MagicMock(return_value="result_1")
    tool2_mock = MagicMock(return_value="result_2")

    fc1 = _make_function_call("tool1", stop_after_tool_call=False, mock_fn=tool1_mock)
    fc2 = _make_function_call("tool2", stop_after_tool_call=False, mock_fn=tool2_mock)

    model = _StubModel()
    results: List[Message] = []
    list(model.run_function_calls([fc1, fc2], function_call_results=results))

    assert tool1_mock.call_count == 1
    assert tool2_mock.call_count == 1

    assert len(results) == 2
    assert results[0].tool_name == "tool1"
    assert results[1].tool_name == "tool2"


# ---------------------------------------------------------------------------
# Tests for arun_function_calls (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_batch_first_tool_stops_subsequent_tool_not_invoked():
    """When a model returns a batch of 2 tool calls and the first has stop_after_tool_call=True,
    the second tool call is never invoked on the async execution path."""
    tool1_mock = MagicMock(return_value="result_1")
    tool2_mock = MagicMock(return_value="result_2")

    fc1 = _make_function_call("tool1", stop_after_tool_call=True, mock_fn=tool1_mock)
    fc2 = _make_function_call("tool2", stop_after_tool_call=False, mock_fn=tool2_mock)

    model = _StubModel()
    results: List[Message] = []
    async for _ in model.arun_function_calls([fc1, fc2], function_call_results=results):
        pass

    assert tool1_mock.call_count == 1
    assert tool2_mock.call_count == 0

    assert len(results) == 2
    assert results[0].tool_name == "tool1"
    assert results[0].stop_after_tool_call is True
    assert results[1].tool_name == "tool2"
    assert results[1].tool_call_id == "call_tool2"
    assert "skipped" in str(results[1].content)


@pytest.mark.asyncio
async def test_async_batch_neither_tool_stops_both_executed():
    """When neither tool call requests stop_after_tool_call, both tool calls execute normally on async path."""
    tool1_mock = MagicMock(return_value="result_1")
    tool2_mock = MagicMock(return_value="result_2")

    fc1 = _make_function_call("tool1", stop_after_tool_call=False, mock_fn=tool1_mock)
    fc2 = _make_function_call("tool2", stop_after_tool_call=False, mock_fn=tool2_mock)

    model = _StubModel()
    results: List[Message] = []
    async for _ in model.arun_function_calls([fc1, fc2], function_call_results=results):
        pass

    assert tool1_mock.call_count == 1
    assert tool2_mock.call_count == 1

    assert len(results) == 2
    assert results[0].tool_name == "tool1"
    assert results[1].tool_name == "tool2"


# ---------------------------------------------------------------------------
# End-to-end model response tests (sync and async)
# ---------------------------------------------------------------------------


def test_model_response_batch_with_stop_after_tool_call():
    """Test full Model.response flow with a batch of 2 tool calls where tool 1 has stop_after_tool_call=True."""
    tool1_mock = MagicMock(return_value="output_1")
    tool2_mock = MagicMock(return_value="output_2")

    def tool_1() -> str:
        return tool1_mock()

    def tool_2() -> str:
        return tool2_mock()

    func1 = Function.from_callable(tool_1, name="tool_1")
    func1.stop_after_tool_call = True
    func1.process_entrypoint()

    func2 = Function.from_callable(tool_2, name="tool_2")
    func2.stop_after_tool_call = False
    func2.process_entrypoint()

    model = _StubModel()
    batch_tool_calls = [
        {"id": "call_1", "type": "function", "function": {"name": "tool_1", "arguments": "{}"}},
        {"id": "call_2", "type": "function", "function": {"name": "tool_2", "arguments": "{}"}},
    ]
    model.invoke_responses = [
        ModelResponse(role="assistant", tool_calls=batch_tool_calls),
    ]

    messages = [Message(role="user", content="Hello")]
    resp = model.response(messages=messages, tools=[func1, func2])

    assert resp is not None
    assert tool1_mock.call_count == 1
    assert tool2_mock.call_count == 0
    # The second tool was never invoked, and no subsequent model turn occurred
    assert len(model.invoke_responses) == 0
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 2
    assert tool_results[0].tool_call_id == "call_1"
    assert tool_results[1].tool_call_id == "call_2"
    assert "skipped" in str(tool_results[1].content)


@pytest.mark.asyncio
async def test_model_aresponse_batch_with_stop_after_tool_call():
    """Test full Model.aresponse flow with a batch of 2 tool calls where tool 1 has stop_after_tool_call=True."""
    tool1_mock = MagicMock(return_value="output_1")
    tool2_mock = MagicMock(return_value="output_2")

    def tool_1() -> str:
        return tool1_mock()

    def tool_2() -> str:
        return tool2_mock()

    func1 = Function.from_callable(tool_1, name="tool_1")
    func1.stop_after_tool_call = True
    func1.process_entrypoint()

    func2 = Function.from_callable(tool_2, name="tool_2")
    func2.stop_after_tool_call = False
    func2.process_entrypoint()

    model = _StubModel()
    batch_tool_calls = [
        {"id": "call_1", "type": "function", "function": {"name": "tool_1", "arguments": "{}"}},
        {"id": "call_2", "type": "function", "function": {"name": "tool_2", "arguments": "{}"}},
    ]
    model.ainvoke_responses = [
        ModelResponse(role="assistant", tool_calls=batch_tool_calls),
    ]

    messages = [Message(role="user", content="Hello")]
    resp = await model.aresponse(messages=messages, tools=[func1, func2])

    assert resp is not None
    assert tool1_mock.call_count == 1
    assert tool2_mock.call_count == 0
    assert len(model.ainvoke_responses) == 0
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 2
    assert tool_results[0].tool_call_id == "call_1"
    assert tool_results[1].tool_call_id == "call_2"
    assert "skipped" in str(tool_results[1].content)


def test_sync_batch_middle_tool_stops_subsequent_tools_not_invoked():
    """When tool 2 of 3 has stop_after_tool_call=True, tool 1 and 2 run, tool 3 is skipped with stub."""
    t1 = MagicMock(return_value="r1")
    t2 = MagicMock(return_value="r2")
    t3 = MagicMock(return_value="r3")
    fc1 = _make_function_call("tool1", stop_after_tool_call=False, mock_fn=t1)
    fc2 = _make_function_call("tool2", stop_after_tool_call=True, mock_fn=t2)
    fc3 = _make_function_call("tool3", stop_after_tool_call=False, mock_fn=t3)
    model = _StubModel()
    results: List[Message] = []
    list(model.run_function_calls([fc1, fc2, fc3], function_call_results=results))
    assert t1.call_count == 1
    assert t2.call_count == 1
    assert t3.call_count == 0
    assert len(results) == 3
    assert results[0].tool_name == "tool1"
    assert results[1].tool_name == "tool2"
    assert results[2].tool_name == "tool3"
    assert "skipped" in str(results[2].content)


@pytest.mark.asyncio
async def test_async_batch_middle_tool_stops_subsequent_tools_not_invoked():
    """When tool 2 of 3 has stop_after_tool_call=True, tool 1 and 2 run, tool 3 is skipped with stub on async path."""
    t1 = MagicMock(return_value="r1")
    t2 = MagicMock(return_value="r2")
    t3 = MagicMock(return_value="r3")
    fc1 = _make_function_call("tool1", stop_after_tool_call=False, mock_fn=t1)
    fc2 = _make_function_call("tool2", stop_after_tool_call=True, mock_fn=t2)
    fc3 = _make_function_call("tool3", stop_after_tool_call=False, mock_fn=t3)
    model = _StubModel()
    results: List[Message] = []
    async for _ in model.arun_function_calls([fc1, fc2, fc3], function_call_results=results):
        pass
    assert t1.call_count == 1
    assert t2.call_count == 1
    assert t3.call_count == 0
    assert len(results) == 3
    assert results[0].tool_name == "tool1"
    assert results[1].tool_name == "tool2"
    assert results[2].tool_name == "tool3"
    assert "skipped" in str(results[2].content)
