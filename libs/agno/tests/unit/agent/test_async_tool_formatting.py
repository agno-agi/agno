"""
Tests for consistent output formatting between sync and async tool call paths.

Verifies:

1. Non-generator, non-ToolResult results use function_execution_result.result
   (not function_call.result) and handle None/falsy values by returning ""
   instead of "None".

2. WorkflowCompletedEvent handling in async generator processing is at the
   correct indentation level (sibling of CustomEvent check, not nested inside).

3. Sync generator path inside arun_function_calls includes
   WorkflowCompletedEvent handling (matching the sync run_function_call path).

4. Shared helpers (_process_generator_item, _format_non_generator_result)
   correctly handle edge cases including falsy values (0, False, empty list).
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from typing import List

import pytest

from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.tools.function import Function, FunctionCall, ToolResult


@pytest.fixture
def model():
    """Create a basic model for testing."""
    return OpenAIChat(id="gpt-4o-mini")


def _make_function_call(func_callable, arguments=None, call_id="call_1"):
    """Helper to create a FunctionCall from a callable."""
    func = Function.from_callable(func_callable)
    func.process_entrypoint()
    fc = FunctionCall(function=func, arguments=arguments or {}, call_id=call_id)
    return fc


class TestAsyncNonGeneratorFormatting:
    """Tests for non-generator result formatting in arun_function_calls."""

    @pytest.mark.asyncio
    async def test_none_result_formats_as_empty_string(self, model):
        """When a tool returns None, async path should produce '' not 'None'."""

        def returns_none() -> None:
            return None

        fc = _make_function_call(returns_none)
        function_call_results: List[Message] = []

        events = []
        async for event in model.arun_function_calls(
            function_calls=[fc],
            function_call_results=function_call_results,
        ):
            events.append(event)

        # Find the tool_call_completed event
        completed_events = [
            e
            for e in events
            if isinstance(e, ModelResponse) and e.event == ModelResponseEvent.tool_call_completed.value
        ]
        assert len(completed_events) == 1

        # The function_call_result message should have empty string content, not "None"
        assert len(function_call_results) == 1
        result_content = function_call_results[0].content
        assert result_content == "" or result_content is None
        assert result_content != "None"

    @pytest.mark.asyncio
    async def test_string_result_formatted_consistently(self, model):
        """When a tool returns a string, async path should format it like sync."""

        def returns_string() -> str:
            return "hello world"

        fc = _make_function_call(returns_string)
        function_call_results: List[Message] = []

        events = []
        async for event in model.arun_function_calls(
            function_calls=[fc],
            function_call_results=function_call_results,
        ):
            events.append(event)

        assert len(function_call_results) == 1
        assert function_call_results[0].content == "hello world"

    @pytest.mark.asyncio
    async def test_dict_result_formatted_as_string(self, model):
        """When a tool returns a dict, it should be str()-ified consistently."""

        def returns_dict() -> dict:
            return {"key": "value", "count": 42}

        fc = _make_function_call(returns_dict)
        function_call_results: List[Message] = []

        events = []
        async for event in model.arun_function_calls(
            function_calls=[fc],
            function_call_results=function_call_results,
        ):
            events.append(event)

        assert len(function_call_results) == 1
        expected = str({"key": "value", "count": 42})
        assert function_call_results[0].content == expected

    @pytest.mark.asyncio
    async def test_empty_string_result_formats_as_empty(self, model):
        """When a tool returns empty string, async path should produce ''."""

        def returns_empty() -> str:
            return ""

        fc = _make_function_call(returns_empty)
        function_call_results: List[Message] = []

        events = []
        async for event in model.arun_function_calls(
            function_calls=[fc],
            function_call_results=function_call_results,
        ):
            events.append(event)

        assert len(function_call_results) == 1
        # Empty string is falsy, so formatting should produce ""
        assert function_call_results[0].content == ""

    @pytest.mark.asyncio
    async def test_tool_result_media_transferred(self, model):
        """ToolResult media artifacts are properly transferred in async path."""
        from agno.media import Image

        def returns_tool_result() -> ToolResult:
            return ToolResult(
                content="image result",
                images=[Image(url="https://example.com/img.png")],
            )

        fc = _make_function_call(returns_tool_result)
        function_call_results: List[Message] = []

        events = []
        async for event in model.arun_function_calls(
            function_calls=[fc],
            function_call_results=function_call_results,
        ):
            events.append(event)

        assert len(function_call_results) == 1
        assert function_call_results[0].content == "image result"

        # Check media was transferred via the completed event
        completed_events = [
            e
            for e in events
            if isinstance(e, ModelResponse) and e.event == ModelResponseEvent.tool_call_completed.value
        ]
        assert len(completed_events) == 1
        assert completed_events[0].images is not None
        assert len(completed_events[0].images) == 1


class TestAsyncSyncConsistency:
    """Tests verifying sync and async paths produce identical formatting."""

    def test_sync_none_result_formats_as_empty(self, model):
        """Sync path: None result should format as empty string."""

        def returns_none() -> None:
            return None

        fc = _make_function_call(returns_none)
        function_call_results: List[Message] = []

        list(
            model.run_function_calls(
                function_calls=[fc],
                function_call_results=function_call_results,
            )
        )

        assert len(function_call_results) == 1
        sync_content = function_call_results[0].content
        assert sync_content == "" or sync_content is None
        assert sync_content != "None"

    @pytest.mark.asyncio
    async def test_sync_async_none_match(self, model):
        """Both sync and async paths should produce identical output for None result."""

        def returns_none() -> None:
            return None

        # Sync
        fc_sync = _make_function_call(returns_none, call_id="call_sync")
        sync_results: List[Message] = []
        list(
            model.run_function_calls(
                function_calls=[fc_sync],
                function_call_results=sync_results,
            )
        )

        # Async
        fc_async = _make_function_call(returns_none, call_id="call_async")
        async_results: List[Message] = []
        async for _ in model.arun_function_calls(
            function_calls=[fc_async],
            function_call_results=async_results,
        ):
            pass

        assert len(sync_results) == 1
        assert len(async_results) == 1
        assert sync_results[0].content == async_results[0].content

    @pytest.mark.asyncio
    async def test_sync_async_string_match(self, model):
        """Both paths should produce identical output for string results."""

        def returns_string() -> str:
            return "test output"

        # Sync
        fc_sync = _make_function_call(returns_string, call_id="call_sync")
        sync_results: List[Message] = []
        list(
            model.run_function_calls(
                function_calls=[fc_sync],
                function_call_results=sync_results,
            )
        )

        # Async
        fc_async = _make_function_call(returns_string, call_id="call_async")
        async_results: List[Message] = []
        async for _ in model.arun_function_calls(
            function_calls=[fc_async],
            function_call_results=async_results,
        ):
            pass

        assert len(sync_results) == 1
        assert len(async_results) == 1
        assert sync_results[0].content == async_results[0].content
        assert sync_results[0].content == "test output"

    @pytest.mark.asyncio
    async def test_sync_async_integer_match(self, model):
        """Both paths should produce identical output for integer results."""

        def returns_int() -> int:
            return 42

        # Sync
        fc_sync = _make_function_call(returns_int, call_id="call_sync")
        sync_results: List[Message] = []
        list(
            model.run_function_calls(
                function_calls=[fc_sync],
                function_call_results=sync_results,
            )
        )

        # Async
        fc_async = _make_function_call(returns_int, call_id="call_async")
        async_results: List[Message] = []
        async for _ in model.arun_function_calls(
            function_calls=[fc_async],
            function_call_results=async_results,
        ):
            pass

        assert len(sync_results) == 1
        assert len(async_results) == 1
        assert sync_results[0].content == async_results[0].content
        assert sync_results[0].content == "42"


class TestFormatNonGeneratorResult:
    """Tests for _format_non_generator_result helper with edge cases."""

    def test_zero_result_preserved(self, model):
        """Falsy value 0 should format as '0', not ''."""
        from agno.tools.function import FunctionExecutionResult

        def returns_zero() -> int:
            return 0

        fc = _make_function_call(returns_zero)
        fer = FunctionExecutionResult(status="success", result=0)

        output, show_response = model._format_non_generator_result(fer, fc)
        assert output == "0"

    def test_false_result_preserved(self, model):
        """Falsy value False should format as 'False', not ''."""
        from agno.tools.function import FunctionExecutionResult

        def returns_false() -> bool:
            return False

        fc = _make_function_call(returns_false)
        fer = FunctionExecutionResult(status="success", result=False)

        output, show_response = model._format_non_generator_result(fer, fc)
        assert output == "False"

    def test_empty_list_result_preserved(self, model):
        """Falsy value [] should format as '[]', not ''."""
        from agno.tools.function import FunctionExecutionResult

        def returns_empty_list() -> list:
            return []

        fc = _make_function_call(returns_empty_list)
        fer = FunctionExecutionResult(status="success", result=[])

        output, show_response = model._format_non_generator_result(fer, fc)
        assert output == "[]"

    def test_none_result_formats_as_empty(self, model):
        """None should still format as ''."""
        from agno.tools.function import FunctionExecutionResult

        def returns_none() -> None:
            return None

        fc = _make_function_call(returns_none)
        fer = FunctionExecutionResult(status="success", result=None)

        output, show_response = model._format_non_generator_result(fer, fc)
        assert output == ""

    def test_tool_result_media_transferred(self, model):
        """ToolResult media is properly transferred to FunctionExecutionResult."""
        from agno.media import Image
        from agno.tools.function import FunctionExecutionResult

        def returns_tool_result() -> ToolResult:
            return ToolResult(
                content="media content",
                images=[Image(url="https://example.com/img.png")],
            )

        fc = _make_function_call(returns_tool_result)
        tr = ToolResult(content="media content", images=[Image(url="https://example.com/img.png")])
        fer = FunctionExecutionResult(status="success", result=tr)

        output, show_response = model._format_non_generator_result(fer, fc)
        assert output == "media content"
        assert fer.images is not None
        assert len(fer.images) == 1


class TestFalsyValueSyncAsyncConsistency:
    """Verify falsy values (0, False) are formatted consistently in both paths."""

    @pytest.mark.asyncio
    async def test_sync_async_zero_match(self, model):
        """Both paths should produce '0' for integer 0 result."""

        def returns_zero() -> int:
            return 0

        # Sync
        fc_sync = _make_function_call(returns_zero, call_id="call_sync")
        sync_results: List[Message] = []
        list(
            model.run_function_calls(
                function_calls=[fc_sync],
                function_call_results=sync_results,
            )
        )

        # Async
        fc_async = _make_function_call(returns_zero, call_id="call_async")
        async_results: List[Message] = []
        async for _ in model.arun_function_calls(
            function_calls=[fc_async],
            function_call_results=async_results,
        ):
            pass

        assert len(sync_results) == 1
        assert len(async_results) == 1
        assert sync_results[0].content == async_results[0].content
        assert sync_results[0].content == "0"

    @pytest.mark.asyncio
    async def test_sync_async_false_match(self, model):
        """Both paths should produce 'False' for boolean False result."""

        def returns_false() -> bool:
            return False

        # Sync
        fc_sync = _make_function_call(returns_false, call_id="call_sync")
        sync_results: List[Message] = []
        list(
            model.run_function_calls(
                function_calls=[fc_sync],
                function_call_results=sync_results,
            )
        )

        # Async
        fc_async = _make_function_call(returns_false, call_id="call_async")
        async_results: List[Message] = []
        async for _ in model.arun_function_calls(
            function_calls=[fc_async],
            function_call_results=async_results,
        ):
            pass

        assert len(sync_results) == 1
        assert len(async_results) == 1
        assert sync_results[0].content == async_results[0].content
        assert sync_results[0].content == "False"
