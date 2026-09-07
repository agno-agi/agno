"""Raw ClientSession discovery must consume complete, bounded tool listings."""

import asyncio
from unittest.mock import AsyncMock, call, patch

import pytest
from mcp.types import ListToolsResult, PaginatedRequestParams, Tool

import agno.tools.mcp.mcp as mcp_module
from agno.tools.mcp import MCPTools


def tool(name):
    return Tool(name=name, input_schema={"type": "object", "properties": {}})


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", ["opaque:+/token==", ""])
async def test_raw_session_follows_non_null_cursors_without_mutating_pages(cursor):
    first = ListToolsResult(tools=[tool("first")], next_cursor=cursor)
    session = AsyncMock()
    session.list_tools.side_effect = [first, ListToolsResult(tools=[tool("second")])]
    toolkit = MCPTools(session=session)

    await toolkit.build_tools()

    assert list(toolkit.functions) == ["first", "second"]
    assert [item.name for item in first.tools] == ["first"]
    assert session.list_tools.await_args_list == [call(), call(params=PaginatedRequestParams(cursor=cursor))]


@pytest.mark.asyncio
async def test_empty_page_with_next_cursor_does_not_end_discovery():
    session = AsyncMock()
    session.list_tools.side_effect = [
        ListToolsResult(tools=[], next_cursor="first"),
        ListToolsResult(tools=[tool("first")], next_cursor="empty"),
        ListToolsResult(tools=[], next_cursor="last"),
        ListToolsResult(tools=[tool("last")]),
    ]
    toolkit = MCPTools(session=session)

    await toolkit.build_tools()

    assert list(toolkit.functions) == ["first", "last"]
    assert session.list_tools.await_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filters, expected",
    [({"include_tools": ["second"]}, ["remote_second"]), ({"exclude_tools": ["second"]}, ["remote_first"])],
)
async def test_filters_are_checked_after_collecting_every_page(filters, expected):
    session = AsyncMock()
    session.list_tools.side_effect = [
        ListToolsResult(tools=[tool("first")], next_cursor="next"),
        ListToolsResult(tools=[tool("second")]),
    ]
    toolkit = MCPTools(session=session, tool_name_prefix="remote", **filters)

    await toolkit.build_tools()

    assert list(toolkit.functions) == expected
    assert session.list_tools.await_count == 2


def toolkit_with_existing_function(session):
    toolkit = MCPTools(session=session)

    def existing():
        return "existing"

    toolkit.register(existing)
    return toolkit


@pytest.mark.asyncio
async def test_cursor_cycle_fails_without_registering_partial_results():
    session = AsyncMock()
    session.list_tools.side_effect = [
        ListToolsResult(tools=[tool("first")], next_cursor="a"),
        ListToolsResult(tools=[tool("second")], next_cursor="b"),
        ListToolsResult(tools=[tool("third")], next_cursor="a"),
    ]
    toolkit = toolkit_with_existing_function(session)
    existing = toolkit.functions.copy()

    with pytest.raises(RuntimeError, match="repeated pagination cursor"):
        await toolkit.build_tools()

    assert toolkit.functions == existing
    assert session.list_tools.await_count == 3


@pytest.mark.asyncio
async def test_unique_cursors_are_bounded_by_page_limit(monkeypatch):
    monkeypatch.setattr(mcp_module, "_MCP_TOOL_PAGINATION_MAX_PAGES", 3, raising=False)
    session = AsyncMock()
    session.list_tools.side_effect = [ListToolsResult(tools=[tool(str(i))], next_cursor=str(i)) for i in range(4)]
    toolkit = toolkit_with_existing_function(session)
    existing = toolkit.functions.copy()

    with pytest.raises(RuntimeError, match="page limit.*3"):
        await toolkit.build_tools()

    assert toolkit.functions == existing
    assert session.list_tools.await_count == 3


@pytest.mark.asyncio
async def test_listing_may_finish_on_last_allowed_page(monkeypatch):
    monkeypatch.setattr(mcp_module, "_MCP_TOOL_PAGINATION_MAX_PAGES", 3, raising=False)
    session = AsyncMock()
    session.list_tools.side_effect = [
        ListToolsResult(tools=[tool("first")], next_cursor="a"),
        ListToolsResult(tools=[tool("second")], next_cursor="b"),
        ListToolsResult(tools=[tool("third")]),
    ]
    toolkit = MCPTools(session=session)

    await toolkit.build_tools()

    assert list(toolkit.functions) == ["first", "second", "third"]
    assert session.list_tools.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("second page failed"), asyncio.CancelledError()])
async def test_later_page_failure_or_cancellation_preserves_registry(error):
    session = AsyncMock()
    session.list_tools.side_effect = [ListToolsResult(tools=[tool("first")], next_cursor="next"), error]
    toolkit = toolkit_with_existing_function(session)
    existing = toolkit.functions.copy()

    with pytest.raises(type(error)):
        await toolkit.build_tools()

    assert toolkit.functions == existing
    assert session.list_tools.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("listed", [[tool("only")], ListToolsResult(tools=[tool("only")])])
async def test_complete_listings_need_only_one_request(listed):
    session = AsyncMock()
    session.list_tools.return_value = listed
    toolkit = MCPTools(session=session)

    await toolkit.build_tools()

    assert list(toolkit.functions) == ["only"]
    session.list_tools.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_real_raw_session_discovers_and_calls_second_page_tool():
    from fastmcp import Client, FastMCP
    from mcp import ClientSession

    server = FastMCP("pagination-test", list_page_size=1)

    @server.tool
    def first_tool() -> str:
        return "first"

    @server.tool
    def second_tool() -> str:
        return "second"

    async with Client(server) as client:
        session = client.session
        assert isinstance(session, ClientSession)
        toolkit = MCPTools(session=session)
        with patch.object(session, "list_tools", wraps=session.list_tools) as list_tools:
            await toolkit.build_tools()
            assert list_tools.await_count == 2
        assert set(toolkit.get_async_functions()) == {"first_tool", "second_tool"}
        result = await toolkit.functions["second_tool"].entrypoint()

    assert result.content == "second"
