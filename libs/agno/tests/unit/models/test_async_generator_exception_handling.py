"""
Tests for async generator exception handling in the Model class.

This test suite verifies that when an async generator tool raises an exception
during iteration, the exception is handled gracefully (like sync generators)
rather than crashing the agent.

The bug: When an async generator tool raised an exception during iteration,
the code would re-raise the exception with `raise error`, causing the agent
to crash instead of handling it gracefully.

Fix: Changed the exception handling to set `function_call.error = str(error)`
and `function_call_success = False`, matching the behavior of sync generators.
"""

import asyncio
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run import RunContext
from agno.tools.function import Function, FunctionCall


class TestAsyncGeneratorExceptionHandling:
    """Test suite for async generator exception handling."""

    @pytest.mark.asyncio
    async def test_async_generator_exception_sets_error_on_function_call(self):
        """Test that async generator exceptions are captured in function_call.error."""
        from agno.run import RunContext

        session_state = {"initial": "value"}

        async def failing_async_generator(run_context: RunContext) -> AsyncIterator[str]:
            """An async generator that raises an exception during iteration."""
            yield "first"
            raise ValueError("Test error during async generator iteration")

        # Create the function with run_context
        func = Function.from_callable(failing_async_generator)
        run_context = RunContext(run_id="test-run", session_id="test-session", session_state=session_state)
        func._run_context = run_context

        func.process_entrypoint()
        fc = FunctionCall(function=func, arguments={})

        # Execute - this returns a FunctionExecutionResult with an async generator
        result = fc.aexecute()
        result = await result

        # The result should be an async generator
        assert hasattr(result.result, "__anext__")

        # Consume the async generator and capture the error
        error = None
        output = []
        try:
            async for item in result.result:
                output.append(item)
        except ValueError as e:
            error = e

        # Verify the error was raised
        assert error is not None
        assert str(error) == "Test error during async generator iteration"
        assert output == ["first"]

    @pytest.mark.asyncio
    async def test_async_generator_exception_before_first_yield(self):
        """Test async generator that raises exception before yielding anything."""
        from agno.run import RunContext

        session_state = {}

        async def failing_immediately(run_context: RunContext) -> AsyncIterator[str]:
            """An async generator that fails immediately."""
            raise RuntimeError("Immediate failure")
            yield "never reached"  # noqa: F821

        func = Function.from_callable(failing_immediately)
        run_context = RunContext(run_id="test-run", session_id="test-session", session_state=session_state)
        func._run_context = run_context

        func.process_entrypoint()
        fc = FunctionCall(function=func, arguments={})

        result = await fc.aexecute()

        # The result should be an async generator
        assert hasattr(result.result, "__anext__")

        # Consuming should raise the error
        error = None
        output = []
        try:
            async for item in result.result:
                output.append(item)
        except RuntimeError as e:
            error = e

        assert error is not None
        assert str(error) == "Immediate failure"
        assert output == []

    @pytest.mark.asyncio
    async def test_async_generator_success_no_exception(self):
        """Test that successful async generators work correctly."""
        from agno.run import RunContext

        session_state = {"initial": "value"}

        async def successful_async_generator(run_context: RunContext) -> AsyncIterator[str]:
            """An async generator that completes successfully."""
            run_context.session_state["step1"] = True
            yield "first"
            run_context.session_state["step2"] = True
            yield "second"

        func = Function.from_callable(successful_async_generator)
        run_context = RunContext(run_id="test-run", session_id="test-session", session_state=session_state)
        func._run_context = run_context

        func.process_entrypoint()
        fc = FunctionCall(function=func, arguments={})

        result = await fc.aexecute()

        # Consume the generator
        output = []
        async for item in result.result:
            output.append(item)

        assert output == ["first", "second"]
        assert session_state["step1"] is True
        assert session_state["step2"] is True

    @pytest.mark.asyncio
    async def test_async_generator_exception_after_multiple_yields(self):
        """Test async generator that yields multiple times before failing."""
        from agno.run import RunContext

        session_state = {}

        async def multi_yield_then_fail(run_context: RunContext) -> AsyncIterator[str]:
            """An async generator that yields multiple times then fails."""
            yield "one"
            await asyncio.sleep(0.01)
            yield "two"
            await asyncio.sleep(0.01)
            yield "three"
            raise Exception("Failed after three yields")

        func = Function.from_callable(multi_yield_then_fail)
        run_context = RunContext(run_id="test-run", session_id="test-session", session_state=session_state)
        func._run_context = run_context

        func.process_entrypoint()
        fc = FunctionCall(function=func, arguments={})

        result = await fc.aexecute()

        # Consume and capture error
        error = None
        output = []
        try:
            async for item in result.result:
                output.append(item)
        except Exception as e:
            error = e

        assert output == ["one", "two", "three"]
        assert error is not None
        assert str(error) == "Failed after three yields"


class TestFunctionCallErrorAttribute:
    """Test that FunctionCall.error attribute is set correctly for errors."""

    def test_function_call_has_error_attribute(self):
        """Verify FunctionCall has an error attribute."""
        func = Function.from_callable(lambda: "test")
        fc = FunctionCall(function=func, arguments={})

        # FunctionCall should have error attribute (None by default)
        assert hasattr(fc, "error")
        assert fc.error is None

    def test_function_call_error_can_be_set(self):
        """Verify FunctionCall.error can be set."""
        func = Function.from_callable(lambda: "test")
        fc = FunctionCall(function=func, arguments={})

        fc.error = "Test error message"
        assert fc.error == "Test error message"

    def test_function_call_error_can_be_cleared(self):
        """Verify FunctionCall.error can be cleared."""
        func = Function.from_callable(lambda: "test")
        fc = FunctionCall(function=func, arguments={})

        fc.error = "Some error"
        fc.error = None
        assert fc.error is None


class TestSyncGeneratorExceptionHandling:
    """Test sync generator exception handling for comparison."""

    def test_sync_generator_exception_sets_error(self):
        """Test that sync generator exceptions are captured similarly."""
        from typing import Iterator

        from agno.run import RunContext

        session_state = {}

        def failing_sync_generator(run_context: RunContext) -> Iterator[str]:
            """A sync generator that raises an exception."""
            yield "first"
            raise ValueError("Sync generator error")

        func = Function.from_callable(failing_sync_generator)
        run_context = RunContext(run_id="test-run", session_id="test-session", session_state=session_state)
        func._run_context = run_context

        func.process_entrypoint()
        fc = FunctionCall(function=func, arguments={})

        result = fc.execute()

        # Consume the generator and capture error
        error = None
        output = []
        try:
            for item in result.result:
                output.append(item)
        except ValueError as e:
            error = e

        assert output == ["first"]
        assert error is not None
        assert str(error) == "Sync generator error"
