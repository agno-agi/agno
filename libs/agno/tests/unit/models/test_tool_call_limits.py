from typing import Any, AsyncIterator, Iterator

import pytest

from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.tools.function import Function, FunctionCall


class MockModel(Model):
    """Minimal offline model for exercising base tool-call limit logic."""

    def __init__(self, responses: list[ModelResponse] | None = None):
        super().__init__(id="test-model", name="test-model", provider="test")
        self._mock_response = ModelResponse(
            content="ok",
            role="assistant",
            response_usage=MessageMetrics(),
        )
        self._responses = iter(responses or [])

    def _next_response(self) -> ModelResponse:
        return next(self._responses, self._mock_response)

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._next_response()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._next_response()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._next_response()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._next_response()
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


def _make_function_call(name: str, *, max_calls: int | None = None) -> FunctionCall:
    def tool_impl() -> str:
        return f"{name}-ok"

    func = Function.from_callable(tool_impl, name=name, max_calls=max_calls)
    return FunctionCall(function=func, arguments={}, call_id=f"call-{name}")


def _make_response_loop() -> tuple[MockModel, list[Function]]:
    def limited() -> str:
        return "limited-ok"

    def other() -> str:
        return "other-ok"

    responses = [
        ModelResponse(
            role="assistant",
            tool_calls=[
                {"id": "call-limited-1", "type": "function", "function": {"name": "limited", "arguments": "{}"}}
            ],
            response_usage=MessageMetrics(),
        ),
        ModelResponse(
            role="assistant",
            tool_calls=[
                {"id": "call-limited-2", "type": "function", "function": {"name": "limited", "arguments": "{}"}},
                {"id": "call-other-1", "type": "function", "function": {"name": "other", "arguments": "{}"}},
            ],
            response_usage=MessageMetrics(),
        ),
        ModelResponse(role="assistant", content="done", response_usage=MessageMetrics()),
    ]
    tools = [
        Function.from_callable(limited, max_calls=1),
        Function.from_callable(other),
    ]
    return MockModel(responses), tools


def _assert_response_loop_results(messages: list[Message]) -> None:
    tool_results = [message for message in messages if message.tool_name is not None]

    assert [(result.tool_name, result.tool_call_error) for result in tool_results] == [
        ("limited", False),
        ("limited", True),
        ("other", False),
    ]


@pytest.mark.parametrize("stream", [False, True])
def test_sync_response_flows_enforce_per_tool_limit(stream: bool):
    model, tools = _make_response_loop()
    messages = []

    if stream:
        list(model.response_stream(messages=messages, tools=tools))
    else:
        model.response(messages=messages, tools=tools)

    _assert_response_loop_results(messages)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.asyncio
async def test_async_response_flows_enforce_per_tool_limit(stream: bool):
    model, tools = _make_response_loop()
    messages = []

    if stream:
        async for _ in model.aresponse_stream(messages=messages, tools=tools):
            pass
    else:
        await model.aresponse(messages=messages, tools=tools)

    _assert_response_loop_results(messages)


def test_run_function_calls_enforces_per_tool_limit_across_batches():
    model = MockModel()
    per_tool_call_counts = {}

    limited_call_1 = _make_function_call("limited", max_calls=1)
    first_results = []
    list(model.run_function_calls([limited_call_1], first_results, per_tool_call_counts=per_tool_call_counts))

    assert len(first_results) == 1
    assert first_results[0].tool_name == "limited"
    assert first_results[0].tool_call_error is False

    limited_call_2 = _make_function_call("limited", max_calls=1)
    other_call = _make_function_call("other", max_calls=1)
    second_results = []
    list(
        model.run_function_calls(
            [limited_call_2, other_call],
            second_results,
            per_tool_call_counts=per_tool_call_counts,
        )
    )

    assert len(second_results) == 2
    assert second_results[0].tool_name == "limited"
    assert second_results[0].tool_call_error is True
    assert "Per-tool call limit reached" in str(second_results[0].content)
    assert second_results[1].tool_name == "other"
    assert second_results[1].tool_call_error is False
    assert per_tool_call_counts == {"limited": 1, "other": 1}


def test_run_function_calls_with_zero_limit_never_executes_tool():
    model = MockModel()
    per_tool_call_counts = {}
    function_call_results = []

    list(
        model.run_function_calls(
            [_make_function_call("disabled", max_calls=0)],
            function_call_results,
            per_tool_call_counts=per_tool_call_counts,
        )
    )

    assert len(function_call_results) == 1
    assert function_call_results[0].tool_name == "disabled"
    assert function_call_results[0].tool_call_error is True
    assert "max_calls=0" in str(function_call_results[0].content)
    assert per_tool_call_counts == {}


def test_run_function_calls_resets_per_tool_limit_when_counts_are_not_shared():
    model = MockModel()

    for _ in range(2):
        function_call_results = []
        list(model.run_function_calls([_make_function_call("limited", max_calls=1)], function_call_results))

        assert len(function_call_results) == 1
        assert function_call_results[0].tool_call_error is False


def test_run_function_calls_preserves_global_tool_call_limit_behavior():
    model = MockModel()

    first_call = _make_function_call("first", max_calls=5)
    second_call = _make_function_call("second", max_calls=5)
    function_call_results = []

    list(
        model.run_function_calls(
            [first_call, second_call],
            function_call_results,
            function_call_limit=1,
            per_tool_call_counts={},
        )
    )

    assert len(function_call_results) == 2
    assert function_call_results[0].tool_name == "first"
    assert function_call_results[0].tool_call_error is False
    assert function_call_results[1].tool_name == "second"
    assert function_call_results[1].tool_call_error is True
    assert str(function_call_results[1].content).startswith("Tool call limit reached")


@pytest.mark.asyncio
async def test_arun_function_calls_enforces_per_tool_limit_across_batches():
    model = MockModel()
    per_tool_call_counts = {}

    first_results = []
    async for _ in model.arun_function_calls(
        [_make_function_call("limited", max_calls=1)],
        first_results,
        per_tool_call_counts=per_tool_call_counts,
    ):
        pass

    assert len(first_results) == 1
    assert first_results[0].tool_call_error is False

    second_results = []
    async for _ in model.arun_function_calls(
        [_make_function_call("limited", max_calls=1), _make_function_call("other", max_calls=1)],
        second_results,
        per_tool_call_counts=per_tool_call_counts,
    ):
        pass

    assert len(second_results) == 2
    assert second_results[0].tool_name == "limited"
    assert second_results[0].tool_call_error is True
    assert "Per-tool call limit reached" in str(second_results[0].content)
    assert second_results[1].tool_name == "other"
    assert second_results[1].tool_call_error is False
