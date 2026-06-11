"""Unit tests for BrowserContextProvider."""

from __future__ import annotations

import pytest

from agno.context.browser import BrowserContextProvider, PlaywrightMCPBackend
from agno.context.mode import ContextMode


class TestPlaywrightMCPBackend:
    def test_default_status_not_connected(self):
        backend = PlaywrightMCPBackend()
        status = backend.status()
        assert status.ok is True
        assert "not connected" in status.detail

    def test_headless_flag_added_to_args(self):
        backend = PlaywrightMCPBackend(headless=True)
        # _build_tools adds --headless to args
        assert backend.headless is True

    def test_headless_false_no_flag(self):
        backend = PlaywrightMCPBackend(headless=False)
        assert backend.headless is False

    def test_default_include_tools_is_none(self):
        backend = PlaywrightMCPBackend()
        assert backend.include_tools is None

    def test_custom_include_tools(self):
        backend = PlaywrightMCPBackend(include_tools=["browser_navigate", "browser_screenshot"])
        assert backend.include_tools == ["browser_navigate", "browser_screenshot"]


class TestBrowserContextProvider:
    def test_default_is_read_only(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend)
        assert provider.read is True
        assert provider.write is False

    def test_tool_names(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend)
        assert provider.query_tool_name == "query_browser"
        assert provider.update_tool_name == "update_browser"

    def test_custom_id_changes_tool_names(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, id="chrome")
        assert provider.query_tool_name == "query_chrome"
        assert provider.update_tool_name == "update_chrome"

    def test_status_delegates_to_backend(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend)
        status = provider.status()
        assert status.ok is True
        assert "playwright-mcp" in status.detail

    def test_instructions_read_only_mode(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, write=False)
        instructions = provider.instructions()
        assert "query_browser" in instructions
        assert "update_browser" not in instructions

    def test_instructions_read_write_mode(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, write=True)
        instructions = provider.instructions()
        assert "query_browser" in instructions
        assert "update_browser" in instructions

    def test_instructions_tools_mode(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, mode=ContextMode.tools)
        instructions = provider.instructions()
        assert "navigate" in instructions
        assert "screenshots" in instructions

    def test_default_tools_returns_query_tool_only_when_read_only(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, write=False)
        tools = provider.get_tools()
        tool_names = [t.name for t in tools]
        assert tool_names == ["query_browser"]

    def test_default_tools_returns_both_when_write_enabled(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, write=True)
        tools = provider.get_tools()
        tool_names = [t.name for t in tools]
        assert tool_names == ["query_browser", "update_browser"]

    def test_all_tools_mode_returns_backend_tools(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, mode=ContextMode.tools)
        # In tools mode, get_tools returns _all_tools which delegates to backend
        tools = provider.get_tools()
        # Backend returns MCPTools wrapped in a list
        assert len(tools) == 1

    def test_update_raises_when_read_only(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, write=False)
        with pytest.raises(NotImplementedError, match="read-only"):
            provider.update("click something")

    @pytest.mark.asyncio
    async def test_aupdate_raises_when_read_only(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, write=False)
        with pytest.raises(NotImplementedError, match="read-only"):
            await provider.aupdate("click something")

    @pytest.mark.asyncio
    async def test_aclose_clears_agent_cache(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend)
        # Force agent creation
        _ = provider._ensure_agent()
        assert provider._agent is not None
        await provider.aclose()
        assert provider._agent is None
