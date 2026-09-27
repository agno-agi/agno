from unittest.mock import AsyncMock, MagicMock

import pytest


def test_search_tool_catches_exceptions(knowledge):
    knowledge.search = MagicMock(side_effect=Exception("Connection refused"))

    tool = knowledge._create_search_tool(async_mode=False)
    result = tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Error searching knowledge base" in result
    assert "Exception" in result


def test_search_tool_with_filters_catches_exceptions(knowledge):
    knowledge.search = MagicMock(side_effect=Exception("DB timeout"))

    tool = knowledge._create_search_tool_with_filters(async_mode=False)
    result = tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Error searching knowledge base" in result


@pytest.mark.asyncio
async def test_async_search_tool_catches_exceptions(knowledge):
    knowledge.asearch = AsyncMock(side_effect=Exception("Network error"))

    tool = knowledge._create_search_tool(async_mode=True)
    result = await tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Error searching knowledge base" in result


@pytest.mark.asyncio
async def test_async_search_tool_with_filters_catches_exceptions(knowledge):
    knowledge.asearch = AsyncMock(side_effect=Exception("Connection timeout"))

    tool = knowledge._create_search_tool_with_filters(async_mode=True)
    result = await tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Error searching knowledge base" in result


def test_search_tool_does_not_leak_sensitive_info(knowledge):
    knowledge.search = MagicMock(side_effect=Exception("Connection failed: postgres://user:password@host:5432/db"))

    tool = knowledge._create_search_tool(async_mode=False)
    result = tool.entrypoint(query="test")

    assert "Exception" in result
    assert "password" not in result
