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
    from agno.run import RunContext

    session_state = {"initial": "value"}

    def generator_tool_with_context(run_context: RunContext) -> Iterator[str]:
        """A generator tool that modifies run_context.session_state during iteration."""
        run_context.session_state["modified_during_yield"] = True
        yield "first"
        run_context.session_state["second_modification"] = "done"
        yield "second"

    # Create the function with run_context
    func = Function.from_callable(generator_tool_with_context)
    run_context = RunContext(run_id="test-run", session_id="test-session", session_state=session_state)
    func._run_context = run_context

    func.process_entrypoint()
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
    from agno.run import RunContext

    session_state = {"initial": "value"}

    def regular_tool_with_context(run_context: RunContext) -> str:
        """A regular tool that modifies run_context.session_state."""
        run_context.session_state["modified"] = True
        return "done"

    # Create the function with run_context
    func = Function.from_callable(regular_tool_with_context)
    run_context = RunContext(run_id="test-run", session_id="test-session", session_state=session_state)
    func._run_context = run_context

    func.process_entrypoint()
    fc = FunctionCall(function=func, arguments={})

    # Execute
    result = fc.execute()

    # For non-generators, updated_session_state should be captured
    assert result.status == "success"
    assert result.updated_session_state == session_state
    assert session_state["modified"] is True


@pytest.mark.asyncio
async def test_async_generator_session_state_not_captured_early():
    """Verify that async generators don't capture session_state before consumption."""
    from typing import AsyncIterator

    from agno.run import RunContext

    session_state = {"initial": "value"}

    async def async_generator_tool_with_context(run_context: RunContext) -> AsyncIterator[str]:
        """An async generator tool that modifies run_context.session_state during iteration."""
        run_context.session_state["async_modified"] = True
        yield "async_first"
        run_context.session_state["async_second"] = "done"
        yield "async_second"

    # Create the function with run_context
    func = Function.from_callable(async_generator_tool_with_context)
    run_context = RunContext(run_id="test-run", session_id="test-session", session_state=session_state)
    func._run_context = run_context

    func.process_entrypoint()
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
    from agno.run import RunContext

    session_state = {"initial": "value"}

    async def async_regular_tool_with_context(run_context: RunContext) -> str:
        """An async regular tool that modifies run_context.session_state."""
        run_context.session_state["async_regular"] = True
        return "async_done"

    # Create the function with run_context
    func = Function.from_callable(async_regular_tool_with_context)
    run_context = RunContext(run_id="test-run", session_id="test-session", session_state=session_state)
    func._run_context = run_context

    func.process_entrypoint()
    fc = FunctionCall(function=func, arguments={})

    # Execute asynchronously
    result = await fc.aexecute()

    # For non-generators, session_state modifications should be in place
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


def test_base_model_recaptures_session_state_after_sync_generator():
    """
    Test that base.py run_function_call re-captures session_state after generator consumption.

    This tests the full flow: function.py returns None for generators,
    then base.py re-captures after the generator is consumed.
    """
    from types import GeneratorType

    from agno.run import RunContext

    session_state = {"initial": "value"}

    def generator_tool_with_context(run_context: RunContext) -> Iterator[str]:
        """A generator tool that modifies run_context.session_state."""
        run_context.session_state["modified_in_generator"] = True
        yield "output"

    # Create the function and function call with run_context
    func = Function.from_callable(generator_tool_with_context)
    run_context = RunContext(run_id="test-run", session_id="test-session", session_state=session_state)
    func._run_context = run_context

    func.process_entrypoint()
    fc = FunctionCall(function=func, arguments={})

    # Execute - returns FunctionExecutionResult with updated_session_state=None for generators
    execution_result = fc.execute()
    assert execution_result.updated_session_state is None
    assert isinstance(execution_result.result, GeneratorType)

    # Simulate what base.py does: consume the generator
    output = list(execution_result.result)
    assert output == ["output"]

    # Verify session_state was modified during iteration
    assert session_state["modified_in_generator"] is True

    # Simulate the re-capture logic from base.py run_function_call
    # This is what happens after generator consumption in base.py
    if execution_result.updated_session_state is None:
        if fc.function._run_context is not None and fc.function._run_context.session_state is not None:
            execution_result.updated_session_state = fc.function._run_context.session_state

    # Now updated_session_state should be captured with the modifications
    assert execution_result.updated_session_state is not None
    assert execution_result.updated_session_state["modified_in_generator"] is True


@pytest.mark.asyncio
async def test_base_model_recaptures_session_state_after_async_generator():
    """
    Test that base.py arun_function_calls re-captures session_state after async generator consumption.

    This tests the full flow: function.py returns None for async generators,
    then base.py re-captures after the generator is consumed.
    """
    from typing import AsyncIterator

    from agno.run import RunContext

    session_state = {"initial": "value"}

    async def async_generator_tool_with_context(run_context: RunContext) -> AsyncIterator[str]:
        """An async generator tool that modifies run_context.session_state."""
        run_context.session_state["async_modified_in_generator"] = True
        yield "async_output"

    # Create the function and function call with run_context
    func = Function.from_callable(async_generator_tool_with_context)
    run_context = RunContext(run_id="test-run", session_id="test-session", session_state=session_state)
    func._run_context = run_context

    func.process_entrypoint()
    fc = FunctionCall(function=func, arguments={})

    # Execute - returns FunctionExecutionResult with updated_session_state=None for generators
    execution_result = await fc.aexecute()
    assert execution_result.updated_session_state is None

    # Consume the async generator
    output = []
    async for item in execution_result.result:
        output.append(item)
    assert output == ["async_output"]

    # Verify session_state was modified during iteration
    assert session_state["async_modified_in_generator"] is True

    # Simulate the re-capture logic from base.py arun_function_calls
    updated_session_state = execution_result.updated_session_state
    if updated_session_state is None:
        if fc.function._run_context is not None and fc.function._run_context.session_state is not None:
            updated_session_state = fc.function._run_context.session_state

    # Now updated_session_state should be captured with the modifications
    assert updated_session_state is not None
    assert updated_session_state["async_modified_in_generator"] is True
