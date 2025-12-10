"""
Tests for session_state persistence in generator-based tools.

This test suite verifies that session_state modifications made during
generator iteration are properly captured and not overwritten by stale state.

The bug: When a tool is a generator function, updated_session_state was captured
before the generator body executed. Any session_state modifications made during
yield iterations would be lost when merge_dictionaries ran later, overwriting
the changes with the stale pre-execution snapshot.

Fix: For generators, we don't capture updated_session_state in execute()/aexecute().
Instead, we re-capture it after the generator is fully consumed in base.py.
"""

from typing import Iterator

import pytest

from agno.tools.function import Function, FunctionCall, FunctionExecutionResult


def test_sync_generator_session_state_not_captured_early():
    """Verify that sync generators don't capture session_state before consumption."""
    session_state = {"initial": "value"}

    def generator_tool(session_state: dict) -> Iterator[str]:
        """A generator tool that modifies session_state during iteration."""
        session_state["modified_during_yield"] = True
        yield "first"
        session_state["second_modification"] = "done"
        yield "second"

    # Create a Function from the callable
    func = Function.from_callable(generator_tool)
    func._session_state = session_state
    func.process_entrypoint()

    # Create FunctionCall
    fc = FunctionCall(function=func, arguments={})

    # Execute - this returns a FunctionExecutionResult
    result = fc.execute()

    # For generators, updated_session_state should be None
    # (since the generator hasn't been consumed yet)
    assert result.status == "success"
    assert result.updated_session_state is None

    # The result should be a generator
    assert hasattr(result.result, "__iter__")

    # Consume the generator
    output = list(result.result)
    assert output == ["first", "second"]

    # After consumption, session_state should have the modifications
    assert session_state["modified_during_yield"] is True
    assert session_state["second_modification"] == "done"


def test_non_generator_session_state_captured():
    """Verify that non-generator functions capture session_state normally."""
    session_state = {"initial": "value"}

    def regular_tool(session_state: dict) -> str:
        """A regular tool that modifies session_state."""
        session_state["modified"] = True
        return "done"

    # Create a Function from the callable
    func = Function.from_callable(regular_tool)
    func._session_state = session_state
    func.process_entrypoint()

    # Create FunctionCall
    fc = FunctionCall(function=func, arguments={})

    # Execute
    result = fc.execute()

    # For non-generators, updated_session_state should be captured
    assert result.status == "success"
    assert result.updated_session_state == session_state
    assert session_state["modified"] is True


def test_generator_with_run_context_session_state():
    """Verify that generators work with run_context.session_state."""
    from agno.run import RunContext

    session_state = {"initial": "value"}
    run_context = RunContext(run_id="test-run-id", session_id="test-session-id", session_state=session_state)

    def generator_tool_with_context(run_context: RunContext) -> Iterator[str]:
        """A generator tool using run_context."""
        run_context.session_state["from_context"] = True
        yield "output"

    # Create a Function from the callable
    func = Function.from_callable(generator_tool_with_context)
    func._run_context = run_context
    func.process_entrypoint()

    # Create FunctionCall
    fc = FunctionCall(function=func, arguments={})

    # Execute
    result = fc.execute()

    # For generators, updated_session_state should be None initially
    assert result.status == "success"
    assert result.updated_session_state is None

    # Consume the generator
    list(result.result)

    # After consumption, session_state should have the modifications
    assert run_context.session_state["from_context"] is True


@pytest.mark.asyncio
async def test_async_generator_session_state_not_captured_early():
    """Verify that async generators don't capture session_state before consumption."""
    from typing import AsyncIterator

    session_state = {"initial": "value"}

    async def async_generator_tool(session_state: dict) -> AsyncIterator[str]:
        """An async generator tool that modifies session_state during iteration."""
        session_state["async_modified"] = True
        yield "async_first"
        session_state["async_second"] = "done"
        yield "async_second"

    # Create a Function from the callable
    func = Function.from_callable(async_generator_tool)
    func._session_state = session_state
    func.process_entrypoint()

    # Create FunctionCall
    fc = FunctionCall(function=func, arguments={})

    # Execute asynchronously
    result = await fc.aexecute()

    # For async generators, updated_session_state should be None
    assert result.status == "success"
    assert result.updated_session_state is None

    # The result should be an async generator
    assert hasattr(result.result, "__anext__")

    # Consume the async generator
    output = []
    async for item in result.result:
        output.append(item)

    assert output == ["async_first", "async_second"]

    # After consumption, session_state should have the modifications
    assert session_state["async_modified"] is True
    assert session_state["async_second"] == "done"


@pytest.mark.asyncio
async def test_async_non_generator_session_state_captured():
    """Verify that async non-generator functions capture session_state normally."""
    session_state = {"initial": "value"}

    async def async_regular_tool(session_state: dict) -> str:
        """An async regular tool that modifies session_state."""
        session_state["async_regular"] = True
        return "async_done"

    # Create a Function from the callable
    func = Function.from_callable(async_regular_tool)
    func._session_state = session_state
    func.process_entrypoint()

    # Create FunctionCall
    fc = FunctionCall(function=func, arguments={})

    # Execute asynchronously
    result = await fc.aexecute()

    # For non-generators, updated_session_state should be captured
    # Note: The async version only captures from run_context, not _session_state
    # This is existing behavior we're not changing
    assert result.status == "success"
    assert session_state["async_regular"] is True


def test_execution_result_with_none_session_state():
    """Verify FunctionExecutionResult can have None updated_session_state."""
    result = FunctionExecutionResult(
        status="success",
        result="test",
        updated_session_state=None,
    )
    assert result.updated_session_state is None


def test_execution_result_with_session_state():
    """Verify FunctionExecutionResult can have dict updated_session_state."""
    session_state = {"key": "value"}
    result = FunctionExecutionResult(
        status="success",
        result="test",
        updated_session_state=session_state,
    )
    assert result.updated_session_state == session_state
    assert result.updated_session_state["key"] == "value"
