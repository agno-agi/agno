"""Regression tests for tool_call_limit infinite loop fix (agno issue #6984).

When every tool call in a batch is blocked by ``tool_call_limit``, the model's
``response()`` loop must terminate immediately instead of re-entering and
creating an infinite cycle.

See: https://github.com/agno-agi/agno/pull/6993
"""

from __future__ import annotations

from typing import Any, Iterator, List

import pytest

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse


# ---------------------------------------------------------------------------
# Factory: concrete Model subclass with all abstract methods implemented
# ---------------------------------------------------------------------------


def _make_model() -> Model:
    """Return a minimal, concrete Model instance suitable for unit tests."""

    class _ConcreteModel(Model):
        def invoke(self, *args, **kwargs) -> ModelResponse:
            raise NotImplementedError

        async def ainvoke(self, *args, **kwargs) -> ModelResponse:
            raise NotImplementedError

        def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
            raise NotImplementedError
            yield  # noqa: unreachable — makes it a generator

        async def ainvoke_stream(self, *args, **kwargs):
            raise NotImplementedError
            yield  # noqa: unreachable

        def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
            return response if isinstance(response, ModelResponse) else ModelResponse()

        def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
            return response if isinstance(response, ModelResponse) else ModelResponse()

        # ------------------------------------------------------------------
        # Overrides used during response() loop
        # ------------------------------------------------------------------

        def _populate_assistant_message(self, assistant_message: Message, provider_response: Any) -> None:
            """Copy tool_calls / content from the fake provider response."""
            if getattr(provider_response, "content", None):
                assistant_message.content = provider_response.content
            if getattr(provider_response, "tool_calls", None):
                assistant_message.tool_calls = provider_response.tool_calls

        def get_function_calls_to_run(self, assistant_message: Message, messages: List[Message], functions=None):
            from agno.tools.function import Function, FunctionCall

            result = []
            for tc in assistant_message.tool_calls or []:
                fn_name = tc.get("function", {}).get("name", "dummy_tool")
                fn = Function(name=fn_name, entrypoint=lambda **kw: "ok")
                fc = FunctionCall(function=fn, call_id=tc.get("id", "call_1"), arguments={})
                result.append(fc)
            return result

        def format_function_call_results(
            self,
            messages: List[Message],
            function_call_results: List[Message],
            compress_tool_results: bool = False,
            **kwargs,
        ) -> None:
            messages.extend(function_call_results)

    return _ConcreteModel(id="test-model", name="TestModel", provider="Test")


# ---------------------------------------------------------------------------
# Helpers that create fake provider responses
# ---------------------------------------------------------------------------


def _tool_call_response() -> ModelResponse:
    """Fake provider response that requests a single tool call."""
    resp = ModelResponse()
    resp.content = None
    resp.tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "dummy_tool", "arguments": "{}"}}]
    return resp


def _text_response(text: str = "All done.") -> ModelResponse:
    """Fake provider response that returns plain text (no tool calls)."""
    resp = ModelResponse()
    resp.content = text
    resp.tool_calls = None
    return resp


# ---------------------------------------------------------------------------
# Tests for the response() loop termination guard
# ---------------------------------------------------------------------------


class TestToolCallLimitLoopTermination:
    """Verify that the fix in base.py prevents an infinite loop when all tool
    calls are blocked by tool_call_limit."""

    # ------------------------------------------------------------------
    # test: tool_call_limit=0 → every call is blocked on the first batch
    # ------------------------------------------------------------------

    def test_response_terminates_when_all_calls_blocked_limit_zero(self):
        """With tool_call_limit=0 the first (and only) model invocation returns
        a tool call that is immediately blocked. The loop must break after that
        single iteration and NOT call the model a second time."""
        from agno.tools.function import Function

        model = _make_model()
        call_count = {"n": 0}

        def fake_invoke(**kwargs):
            call_count["n"] += 1
            if call_count["n"] > 1:
                raise AssertionError(
                    "Infinite loop detected — model was invoked more than once "
                    "after all tool calls were blocked by tool_call_limit."
                )
            return _tool_call_response()

        model._invoke_with_retry = fake_invoke  # type: ignore[method-assign]

        dummy_fn = Function(name="dummy_tool", entrypoint=lambda **kw: "ok")
        messages = [Message(role="user", content="please call the tool")]

        result = model.response(messages=messages, tools=[dummy_fn], tool_call_limit=0)

        assert call_count["n"] == 1, f"Expected exactly 1 model invocation, got {call_count['n']}"
        assert result is not None

    # ------------------------------------------------------------------
    # test: tool_call_limit=1 → first call ok, second batch fully blocked
    # ------------------------------------------------------------------

    def test_response_terminates_after_second_batch_all_blocked_limit_one(self):
        """With tool_call_limit=1 the first model call succeeds (1 tool call
        within limit).  The second model call also returns a tool call, but
        function_call_count is now 2 > 1, so the call is blocked.  The loop
        must terminate after the second model invocation."""
        from agno.tools.function import Function

        model = _make_model()
        call_count = {"n": 0}

        def fake_invoke(**kwargs):
            call_count["n"] += 1
            if call_count["n"] > 2:
                raise AssertionError(
                    "Infinite loop detected — model invoked more than twice when tool_call_limit=1."
                )
            return _tool_call_response()

        model._invoke_with_retry = fake_invoke  # type: ignore[method-assign]

        dummy_fn = Function(name="dummy_tool", entrypoint=lambda **kw: "ok")
        messages = [Message(role="user", content="keep calling")]

        result = model.response(messages=messages, tools=[dummy_fn], tool_call_limit=1)

        assert call_count["n"] == 2, f"Expected 2 model invocations, got {call_count['n']}"
        assert result is not None

    # ------------------------------------------------------------------
    # test: no limit → normal flow continues until text response
    # ------------------------------------------------------------------

    def test_response_continues_normally_without_limit(self):
        """Without tool_call_limit the loop must continue after a tool call
        and only terminate when the model returns a text (non-tool) response."""
        from agno.tools.function import Function

        model = _make_model()
        call_count = {"n": 0}

        def fake_invoke(**kwargs):
            call_count["n"] += 1
            # First call returns a tool call; second returns final text
            if call_count["n"] == 1:
                return _tool_call_response()
            return _text_response("Final answer")

        model._invoke_with_retry = fake_invoke  # type: ignore[method-assign]

        dummy_fn = Function(name="dummy_tool", entrypoint=lambda **kw: "ok")
        messages = [Message(role="user", content="do work then answer")]

        result = model.response(messages=messages, tools=[dummy_fn], tool_call_limit=None)

        assert call_count["n"] == 2, f"Expected 2 model invocations, got {call_count['n']}"
        assert result is not None


# ---------------------------------------------------------------------------
# Tests for run_function_calls() — the building block used by response()
# ---------------------------------------------------------------------------


class TestRunFunctionCallsLimit:
    """Unit tests for the run_function_calls() method that creates the error
    results consumed by the loop-break guard."""

    def test_calls_blocked_when_limit_exceeded(self):
        """run_function_calls() must create tool_call_error=True results for
        every FunctionCall that exceeds the limit, without executing them."""
        from agno.tools.function import Function, FunctionCall

        executed: list = []

        def counting_fn(**kwargs):
            executed.append(1)
            return "executed"

        model = _make_model()
        fn = Function(name="my_tool", entrypoint=counting_fn)
        fc1 = FunctionCall(function=fn, call_id="c1", arguments={})
        fc2 = FunctionCall(function=fn, call_id="c2", arguments={})

        results: List[Message] = []
        list(
            model.run_function_calls(
                function_calls=[fc1, fc2],
                function_call_results=results,
                current_function_call_count=0,
                function_call_limit=1,  # first allowed, second blocked
            )
        )

        ok_results = [m for m in results if not m.tool_call_error]
        error_results = [m for m in results if m.tool_call_error]

        assert len(ok_results) == 1, f"Expected 1 successful result, got {len(ok_results)}"
        assert len(error_results) == 1, f"Expected 1 blocked result, got {len(error_results)}"
        assert len(executed) == 1, f"Expected the tool executed once, got {len(executed)}"

    def test_all_calls_blocked_when_limit_zero(self):
        """With tool_call_limit=0, ALL calls must produce tool_call_error=True
        results — this is the condition that triggers the loop-break guard."""
        from agno.tools.function import Function, FunctionCall

        executed: list = []

        def counting_fn(**kwargs):
            executed.append(1)
            return "executed"

        model = _make_model()
        fn = Function(name="my_tool", entrypoint=counting_fn)
        fc1 = FunctionCall(function=fn, call_id="c1", arguments={})
        fc2 = FunctionCall(function=fn, call_id="c2", arguments={})

        results: List[Message] = []
        list(
            model.run_function_calls(
                function_calls=[fc1, fc2],
                function_call_results=results,
                current_function_call_count=0,
                function_call_limit=0,  # zero — everything blocked
            )
        )

        assert results, "Expected at least one result message"
        assert all(m.tool_call_error for m in results), "All results must have tool_call_error=True when limit=0"
        assert len(executed) == 0, f"No tool should have been executed, but got {len(executed)} executions"

    def test_guard_condition_all_errors(self):
        """Verify the exact boolean expression used in response():
        ``all(m.tool_call_error for m in function_call_results)`` must be True
        when every result is an error (i.e. all calls were blocked)."""
        from agno.tools.function import Function, FunctionCall

        model = _make_model()
        fn = Function(name="my_tool", entrypoint=lambda **kw: "ok")
        fc = FunctionCall(function=fn, call_id="c1", arguments={})

        results: List[Message] = []
        list(
            model.run_function_calls(
                function_calls=[fc],
                function_call_results=results,
                current_function_call_count=0,
                function_call_limit=0,
            )
        )

        # This is the exact condition checked in base.py response() to break the loop.
        # Note: tool_call_limit=0 is a valid (non-None) limit value.
        tool_call_limit = 0
        should_break = (
            tool_call_limit is not None  # 0 is a valid limit, not None
            and bool(results)  # function_call_results is non-empty
            and all(m.tool_call_error for m in results)  # every result is an error
        )
        assert should_break, "The loop-break guard must evaluate to True when all calls are blocked"
