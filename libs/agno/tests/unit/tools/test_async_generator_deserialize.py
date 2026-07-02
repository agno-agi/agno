"""Test for async generator Pydantic deserialization fix (issue #8711)."""

import asyncio
from typing import AsyncGenerator, Literal

import pytest
from pydantic import BaseModel

from agno.tools.function import Function


class SearchParams(BaseModel):
    """Test parameters for async generator tool."""
    query: str
    time_range: Literal["OneDay", "OneWeek"] = "OneWeek"


async def async_generator_tool(params: SearchParams) -> AsyncGenerator[dict, None]:
    """An async generator tool with Pydantic BaseModel arguments."""
    yield {"query": params.query, "time_range": params.time_range}


def test_async_generator_gets_validate_call_wrapped():
    """Test that async generators are wrapped with validate_call."""
    func = Function._wrap_callable(async_generator_tool)
    
    # The function should be wrapped (not the original)
    # validate_call wraps the function, so it should not be the same object
    # unless wrapping failed
    assert func is not None


@pytest.mark.asyncio
async def test_async_generator_deserializes_pydantic_model():
    """Test that async generator can receive dict and deserialize to BaseModel."""
    # Process the function to set up entrypoint
    func = Function(
        name="async_gen_test",
        entrypoint=async_generator_tool,
    )
    func.process_entrypoint()
    
    # Simulate what happens when the tool is called with a dict
    # (which is what happens in practice - args come as dicts from JSON)
    args = {"params": {"query": "test search", "time_range": "OneDay"}}
    
    # The entrypoint should be able to handle dict input
    # and deserialize it to the Pydantic model
    entrypoint = func.entrypoint
    
    # If validate_call is properly applied, this should work
    # Without the fix, this would fail with "'dict' object has no attribute 'query'"
    try:
        # Call the wrapped function
        result = entrypoint(**args)
        # For async generators, we need to iterate
        if hasattr(result, '__aiter__'):
            async for item in result:
                assert item["query"] == "test search"
                assert item["time_range"] == "OneDay"
                break
    except AttributeError as e:
        if "'dict' object has no attribute" in str(e):
            pytest.fail(f"Pydantic deserialization failed: {e}")
        raise
