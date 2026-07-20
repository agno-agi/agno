"""Unit tests for BrowserContextProvider and its backends.

Tests the 2x2 matrix of browser backends:
- PlaywrightMCPBackend: local MCP server
- PlaywrightBackend: local SDK (PlaywrightTools)
- BrowserbaseMCPBackend: cloud MCP (Stagehand)
- BrowserbaseBackend: cloud SDK (BrowserbaseTools)

Following the codebase pattern from test_provider.py — test the contract,
not the implementation details.
"""

from __future__ import annotations

import pytest

from agno.context.browser import (
    BrowserbaseBackend,
    BrowserbaseMCPBackend,
    BrowserContextProvider,
    PlaywrightBackend,
    PlaywrightMCPBackend,
)
from agno.context.mode import ContextMode

# ---------------------------------------------------------------------------
# PlaywrightMCPBackend — local MCP server
# ---------------------------------------------------------------------------


class TestPlaywrightMCPBackend:
    def test_status_ok(self):
        backend = PlaywrightMCPBackend()
        status = backend.status()
        assert status.ok is True
        assert "playwright-mcp" in status.detail

    def test_headless_default_true(self):
        backend = PlaywrightMCPBackend()
        assert backend.headless is True

    def test_headless_false_stored(self):
        backend = PlaywrightMCPBackend(headless=False)
        assert backend.headless is False

    def test_include_tools_default_none(self):
        backend = PlaywrightMCPBackend()
        assert backend.include_tools is None

    def test_include_tools_custom(self):
        backend = PlaywrightMCPBackend(include_tools=["browser_navigate", "browser_snapshot"])
        assert backend.include_tools == ["browser_navigate", "browser_snapshot"]

    def test_exclude_tools_default_none(self):
        backend = PlaywrightMCPBackend()
        assert backend.exclude_tools is None

    def test_exclude_tools_custom(self):
        backend = PlaywrightMCPBackend(exclude_tools=["browser_pdf_save"])
        assert backend.exclude_tools == ["browser_pdf_save"]

    def test_tool_name_prefix_default_none(self):
        backend = PlaywrightMCPBackend()
        assert backend.tool_name_prefix is None

    def test_tool_name_prefix_custom(self):
        backend = PlaywrightMCPBackend(tool_name_prefix="pw")
        assert backend.tool_name_prefix == "pw"

    def test_timeout_seconds_default(self):
        backend = PlaywrightMCPBackend()
        assert backend.timeout_seconds == 60

    def test_timeout_seconds_custom(self):
        backend = PlaywrightMCPBackend(timeout_seconds=120)
        assert backend.timeout_seconds == 120


# ---------------------------------------------------------------------------
# PlaywrightBackend — local SDK (PlaywrightTools)
# ---------------------------------------------------------------------------


class TestPlaywrightBackend:
    def test_status_shows_local(self):
        backend = PlaywrightBackend()
        status = backend.status()
        assert status.ok is True
        assert "playwright" in status.detail
        assert "local" in status.detail

    def test_headless_default_true(self):
        backend = PlaywrightBackend()
        assert backend.headless is True

    def test_headless_false_reflected_in_status(self):
        backend = PlaywrightBackend(headless=False)
        assert backend.headless is False
        assert "headed" in backend.status().detail


# ---------------------------------------------------------------------------
# BrowserbaseBackend — cloud SDK (BrowserbaseTools)
# ---------------------------------------------------------------------------


class TestBrowserbaseBackend:
    def test_status_ok_with_credentials(self):
        backend = BrowserbaseBackend(api_key="bb_live_xxx", project_id="proj_123")
        status = backend.status()
        assert status.ok is True
        assert "browserbase" in status.detail


# ---------------------------------------------------------------------------
# BrowserbaseMCPBackend — cloud MCP (Stagehand)
# ---------------------------------------------------------------------------


class TestBrowserbaseMCPBackend:
    def test_status_ok_with_all_credentials(self):
        backend = BrowserbaseMCPBackend(api_key="bb_live_xxx", project_id="proj_123", model_api_key="xxx")
        status = backend.status()
        assert status.ok is True
        assert "browserbase-mcp" in status.detail

    def test_include_tools_default_none(self):
        backend = BrowserbaseMCPBackend(api_key="x", project_id="y")
        assert backend.include_tools is None

    def test_exclude_tools_custom(self):
        backend = BrowserbaseMCPBackend(api_key="x", project_id="y", exclude_tools=["tool1"])
        assert backend.exclude_tools == ["tool1"]

    def test_tool_name_prefix_default(self):
        backend = BrowserbaseMCPBackend(api_key="x", project_id="y")
        assert backend.tool_name_prefix == "browser"

    def test_timeout_seconds_default(self):
        backend = BrowserbaseMCPBackend(api_key="x", project_id="y")
        assert backend.timeout_seconds == 60


# ---------------------------------------------------------------------------
# BrowserContextProvider — wraps any backend
# ---------------------------------------------------------------------------


class TestBrowserContextProvider:
    def test_default_id_and_name(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend)
        assert provider.id == "browser"
        assert provider.name == "Browser"

    def test_custom_id_and_name(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, id="chrome", name="Chrome Browser")
        assert provider.id == "chrome"
        assert provider.name == "Chrome Browser"

    def test_query_tool_name(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend)
        assert provider.query_tool_name == "query_browser"

    def test_custom_id_changes_query_tool_name(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, id="chrome")
        assert provider.query_tool_name == "query_chrome"

    def test_status_delegates_to_backend(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend)
        status = provider.status()
        assert status.ok is True
        assert "playwright-mcp" in status.detail

    def test_status_delegates_to_browserbase_backend(self):
        backend = BrowserbaseBackend(api_key="bb_live_xxx", project_id="proj_123")
        provider = BrowserContextProvider(backend=backend)
        status = provider.status()
        assert status.ok is True
        assert "browserbase" in status.detail

    def test_instructions_default_mode(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend)
        instructions = provider.instructions()
        assert "query_browser" in instructions

    def test_instructions_tools_mode(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, mode=ContextMode.tools)
        instructions = provider.instructions()
        assert "browser" in instructions.lower()

    def test_default_tools_returns_query_tool(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend)
        tools = provider.get_tools()
        tool_names = [t.name for t in tools]
        assert tool_names == ["query_browser"]

    def test_all_tools_mode_returns_backend_tools(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend, mode=ContextMode.tools)
        tools = provider.get_tools()
        assert len(tools) == 1

    def test_sync_query_raises_not_implemented(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend)
        with pytest.raises(NotImplementedError, match="async-only"):
            provider.query("search something")

    @pytest.mark.asyncio
    async def test_aclose_clears_agent_cache(self):
        backend = PlaywrightMCPBackend()
        provider = BrowserContextProvider(backend=backend)
        _ = provider._ensure_agent()
        assert provider._agent is not None
        await provider.aclose()
        assert provider._agent is None
