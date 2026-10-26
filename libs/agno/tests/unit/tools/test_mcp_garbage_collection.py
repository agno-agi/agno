"""Discarded MCP toolkits must not be retained by process-global callbacks."""

import gc
import weakref

import pytest
from fastmcp import Client, FastMCP

from agno.tools.mcp import MCPTools


def test_unused_toolkit_releases_its_header_provider_state():
    class RequestState:
        pass

    state = RequestState()
    state_ref = weakref.ref(state)
    toolkit = MCPTools(url="http://localhost:8080/mcp", header_provider=lambda state=state: {})
    toolkit_ref = weakref.ref(toolkit)

    del toolkit, state
    gc.collect()

    assert toolkit_ref() is None
    assert state_ref() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("use_context_manager", [False, True])
async def test_closed_toolkit_can_be_collected(monkeypatch, use_context_manager):
    """Exercise discovery and close with a real in-memory FastMCP connection."""
    server = FastMCP("gc-test")

    @server.tool
    def echo(message: str) -> str:
        return message

    client = Client(server)
    monkeypatch.setattr("agno.tools.mcp.mcp._build_fastmcp_client", lambda *args: client)
    toolkit = MCPTools(url="http://localhost:8080/mcp")
    toolkit_ref = weakref.ref(toolkit)

    if use_context_manager:
        async with toolkit:
            assert client.is_connected()
            assert "echo" in toolkit.functions
    else:
        await toolkit.connect()
        assert client.is_connected()
        assert "echo" in toolkit.functions
        await toolkit.close()

    assert not client.is_connected()
    del toolkit
    gc.collect()

    assert toolkit_ref() is None


@pytest.mark.asyncio
async def test_failed_connection_does_not_retain_toolkit(monkeypatch):
    class FailingClient:
        exited = False

        async def __aenter__(self):
            raise ConnectionRefusedError("server unreachable")

        async def __aexit__(self, *args):
            self.exited = True

    client = FailingClient()
    monkeypatch.setattr("agno.tools.mcp.mcp._build_fastmcp_client", lambda *args: client)
    toolkit = MCPTools(url="http://localhost:8080/mcp")
    toolkit_ref = weakref.ref(toolkit)

    await toolkit.connect()
    assert client.exited
    assert not toolkit.initialized
    assert toolkit.session is None
    del toolkit
    gc.collect()

    assert toolkit_ref() is None
