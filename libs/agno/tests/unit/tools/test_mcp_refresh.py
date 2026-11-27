"""MCP discovery must replace its previous snapshot without dropping local tools."""

from unittest.mock import AsyncMock

import pytest
from mcp.types import ListToolsResult, Tool

from agno.tools.mcp import MCPTools


def make_tool(name, **properties):
    return Tool(name=name, description=name, inputSchema={"type": "object", "properties": properties})


@pytest.mark.asyncio
@pytest.mark.parametrize("list_result", [False, True])
@pytest.mark.parametrize("change", ["removed", "empty", "include", "exclude", "prefix"])
async def test_refresh_removes_stale_discovered_functions(list_result, change):
    session = AsyncMock()
    listing = [make_tool("old"), make_tool("keep")]
    session.list_tools.return_value = ListToolsResult(tools=listing) if list_result else listing
    tools = MCPTools(session=session)
    await tools.build_tools()
    registry = tools.functions

    if change == "removed":
        listing = [make_tool("keep"), make_tool("new")]
        expected = {"keep", "new"}
    elif change == "empty":
        listing = []
        expected = set()
    elif change == "include":
        tools.include_tools = ["keep"]
        expected = {"keep"}
    elif change == "exclude":
        tools.exclude_tools = ["old"]
        expected = {"keep"}
    else:
        tools.tool_name_prefix = "remote"
        expected = {"remote_old", "remote_keep"}

    session.list_tools.return_value = ListToolsResult(tools=listing) if list_result else listing
    await tools.build_tools()

    assert tools.functions is registry
    assert set(tools.get_functions()) == expected
    assert set(tools.get_async_functions()) == expected


@pytest.mark.asyncio
async def test_refresh_updates_schema_and_keeps_tool_settings():
    session = AsyncMock()
    session.list_tools.return_value = [make_tool("search", query={"type": "string"})]
    tools = MCPTools(session=session, requires_confirmation_tools=["search"], cache_results=True)
    await tools.build_tools()
    previous = tools.functions["search"]
    session.list_tools.return_value = [make_tool("search", count={"type": "integer"})]

    await tools.build_tools()

    current = tools.functions["search"]
    assert current is not previous
    assert current.parameters["properties"] == {"count": {"type": "integer"}}
    assert current.requires_confirmation is True
    assert current.cache_results is True


@pytest.mark.asyncio
async def test_refresh_preserves_locally_registered_functions_and_replacements():
    session = AsyncMock()
    session.list_tools.return_value = [make_tool("old")]
    tools = MCPTools(session=session)
    await tools.build_tools()

    def local() -> str:
        return "local"

    async def async_local() -> str:
        return "async local"

    tools.register(local)
    tools.register(async_local)
    tools.register(local, name="old")
    replacement = tools.functions["old"]
    session.list_tools.return_value = []

    await tools.build_tools()

    assert set(tools.get_async_functions()) == {"local", "async_local", "old"}
    assert tools.functions["old"] is replacement


@pytest.mark.asyncio
async def test_failed_listing_preserves_registry_and_next_refresh_can_remove_it():
    session = AsyncMock()
    session.list_tools.return_value = [make_tool("old")]
    tools = MCPTools(session=session)
    await tools.build_tools()
    previous = dict(tools.functions)
    session.list_tools.side_effect = RuntimeError("server unavailable")

    with pytest.raises(RuntimeError, match="server unavailable"):
        await tools.build_tools()

    assert tools.functions == previous
    session.list_tools.side_effect = None
    session.list_tools.return_value = []
    await tools.build_tools()
    assert tools.functions == {}


@pytest.mark.asyncio
async def test_refresh_follows_real_server_visibility_changes():
    from fastmcp import Client, FastMCP

    server = FastMCP("refresh-test")

    @server.tool
    def old_tool() -> str:
        return "old"

    @server.tool
    def new_tool() -> str:
        return "new"

    server.disable(names={"new_tool"}, components={"tool"})
    async with Client(server) as client:
        tools = MCPTools(session=client, refresh_connection=True)
        await tools.build_tools()
        assert list(tools.get_async_functions()) == ["old_tool"]

        server.disable(names={"old_tool"}, components={"tool"})
        server.enable(names={"new_tool"}, components={"tool"})
        assert [tool.name for tool in await client.list_tools()] == ["new_tool"]
        await tools.build_tools()

        assert list(tools.get_async_functions()) == ["new_tool"]
        result = await tools.functions["new_tool"].entrypoint()
        assert result.content == "new"
