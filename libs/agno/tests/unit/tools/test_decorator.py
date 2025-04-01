import asyncio
from typing import AsyncIterator, Generator

import pytest

from agno.tools.decorator import tool
from agno.tools.function import Function


def test_sync_function_decorator():
    @tool
    def sync_function(x: int) -> int:
        """Test sync function"""
        return x * 2

    assert isinstance(sync_function, Function)
    assert sync_function.name == "sync_function"
    assert sync_function.description == "Test sync function"
    result = sync_function.entrypoint(5)
    assert result == 10


@pytest.mark.asyncio
async def test_async_function_decorator():
    @tool
    async def async_function(x: int) -> int:
        """Test async function"""
        await asyncio.sleep(0.1)
        return x * 2

    assert isinstance(async_function, Function)
    assert async_function.name == "async_function"
    assert async_function.description == "Test async function"
    result = await async_function.entrypoint(5)
    assert result == 10


def test_sync_generator_decorator():
    @tool
    def sync_generator(count: int) -> Generator[int, None, None]:
        """Test sync generator"""
        for i in range(count):
            yield i

    assert isinstance(sync_generator, Function)
    assert sync_generator.name == "sync_generator"
    gen = sync_generator.entrypoint(3)
    assert list(gen) == [0, 1, 2]


@pytest.mark.asyncio
async def test_async_generator_decorator():
    @tool
    async def async_generator(count: int) -> AsyncIterator[int]:
        """Test async generator"""
        for i in range(count):
            await asyncio.sleep(0.1)
            yield i

    assert isinstance(async_generator, Function)
    assert async_generator.name == "async_generator"
    gen = await async_generator.entrypoint(3)
    result = []
    async for item in gen:
        result.append(item)
    assert result == [0, 1, 2]


def test_decorator_with_parameters():
    @tool(name="custom_name", description="Custom description")
    def function(x: int) -> int:
        return x * 2

    assert isinstance(function, Function)
    assert function.name == "custom_name"
    assert function.description == "Custom description"
    result = function.entrypoint(5)
    assert result == 10


def test_decorator_preserves_type_hints():
    @tool
    def typed_function(x: int, y: str) -> bool:
        return bool(x)

    from inspect import signature

    sig = signature(typed_function.entrypoint)
    assert str(sig.parameters["x"].annotation.__name__) == "int"
    assert str(sig.parameters["y"].annotation.__name__) == "str"


@pytest.mark.asyncio
async def test_decorator_preserves_async_nature():
    @tool
    async def async_function(x: int) -> int:
        await asyncio.sleep(0.1)
        return x * 2

    from inspect import iscoroutinefunction

    assert iscoroutinefunction(async_function.entrypoint)
