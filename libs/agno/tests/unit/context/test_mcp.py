"""Unit tests for MCPContextProvider.

Covers the MCP-specific edge cases the brief called out:
- entry missing both `command` and `url` raises
- config-only status (not runtime-validated)
"""

import pytest

from agno.context import ContextMode
from agno.context.mcp import MCPContextProvider

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_construction_with_command():
    p = MCPContextProvider(id="seq", command="npx -y @modelcontextprotocol/server-sequential-thinking")
    assert p.id == "seq"
    assert p.name == "seq"
    assert p.command == "npx -y @modelcontextprotocol/server-sequential-thinking"
    assert p.url is None


def test_construction_with_url():
    p = MCPContextProvider(id="remote", url="https://mcp.example.com/mcp", transport="streamable-http")
    assert p.url == "https://mcp.example.com/mcp"
    assert p.transport == "streamable-http"


def test_construction_with_name_override():
    p = MCPContextProvider(id="seq", name="Sequential Thinking", command="cmd")
    assert p.name == "Sequential Thinking"


def test_construction_without_command_or_url_raises():
    with pytest.raises(ValueError, match="`command` or `url` is required"):
        MCPContextProvider(id="broken")


def test_construction_accepts_env():
    p = MCPContextProvider(id="mcp", command="cmd", env={"FOO": "bar"})
    assert p.env == {"FOO": "bar"}


# ---------------------------------------------------------------------------
# Status — config-only, not runtime-validated
# ---------------------------------------------------------------------------


def test_status_is_config_only_for_command():
    p = MCPContextProvider(id="seq", command="npx -y some-package")
    s = p.status()
    # status() does NOT probe the server — it only confirms config is well-formed.
    # The module docstring documents this explicitly.
    assert s.ok is True
    assert "npx -y some-package" in s.detail


def test_status_for_url():
    p = MCPContextProvider(id="seq", url="https://mcp.example.com/mcp")
    s = p.status()
    assert s.ok is True
    assert "https://mcp.example.com/mcp" in s.detail


@pytest.mark.asyncio
async def test_astatus_matches_status():
    p = MCPContextProvider(id="seq", command="cmd")
    assert await p.astatus() == p.status()


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------


def test_instructions_differ_by_mode():
    p_default = MCPContextProvider(id="seq", command="cmd", mode=ContextMode.default)
    p_agent = MCPContextProvider(id="seq", command="cmd", mode=ContextMode.agent)
    assert p_default.instructions() != p_agent.instructions()
    # Agent mode should advertise the query tool
    assert "query_seq" in p_agent.instructions()


# ---------------------------------------------------------------------------
# Tool exposure per mode (without instantiating the real MCPTools)
# ---------------------------------------------------------------------------


def test_agent_mode_returns_single_query_tool():
    p = MCPContextProvider(id="seq", command="cmd", mode=ContextMode.agent)
    tools = p.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "query_seq"


def test_query_tool_name_sanitized():
    p = MCPContextProvider(id="My Weird ID!", command="cmd", mode=ContextMode.agent)
    tools = p.get_tools()
    assert tools[0].name == "query_my_weird_id"


def test_agent_mode_builds_agent(mocker):
    # Avoid touching real MCPTools during sub-agent construction
    mocker.patch("agno.context.mcp.provider.MCPTools", return_value=object())
    p = MCPContextProvider(id="seq", command="cmd", mode=ContextMode.agent)
    agent = p._build_agent()
    assert agent.id == "seq"


def test_default_mode_returns_mcp_tools_object(mocker):
    fake_mcp = object()
    mocker.patch("agno.context.mcp.provider.MCPTools", return_value=fake_mcp)
    p = MCPContextProvider(id="seq", command="cmd", mode=ContextMode.default)
    tools = p.get_tools()
    assert tools == [fake_mcp]


def test_mcp_tools_cached(mocker):
    mock = mocker.patch("agno.context.mcp.provider.MCPTools", return_value=object())
    p = MCPContextProvider(id="seq", command="cmd")
    p.get_tools()
    p.get_tools()
    assert mock.call_count == 1  # single instantiation


def test_mcp_tools_receives_transport_and_env(mocker):
    mock = mocker.patch("agno.context.mcp.provider.MCPTools", return_value=object())
    p = MCPContextProvider(
        id="seq",
        url="https://mcp.example.com/mcp",
        transport="streamable-http",
        env={"KEY": "value"},
    )
    p.get_tools()
    mock.assert_called_once_with(
        url="https://mcp.example.com/mcp",
        transport="streamable-http",
        env={"KEY": "value"},
    )
