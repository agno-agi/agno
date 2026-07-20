"""Unit tests for BrowserContextProvider and its backends.

Smoke tests for the 2x2 browser backend matrix:
- PlaywrightMCPBackend: local MCP server
- PlaywrightBackend: local SDK (PlaywrightTools)
- BrowserbaseMCPBackend: cloud MCP (Stagehand)
- BrowserbaseBackend: cloud SDK (BrowserbaseTools)

Following the codebase pattern from test_providers.py — test constructor
defaults, tool-surface shape, and status behaviour. No network calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agno.context.backend import ContextBackend
from agno.context.browser import (
    BrowserbaseBackend,
    BrowserbaseMCPBackend,
    BrowserContextProvider,
    PlaywrightBackend,
    PlaywrightMCPBackend,
)
from agno.context.mode import ContextMode

# ---------------------------------------------------------------------------
# Backend Contract
# ---------------------------------------------------------------------------


def test_all_backends_are_context_backend_subclasses():
    assert issubclass(PlaywrightMCPBackend, ContextBackend)
    assert issubclass(PlaywrightBackend, ContextBackend)
    assert issubclass(BrowserbaseBackend, ContextBackend)
    assert issubclass(BrowserbaseMCPBackend, ContextBackend)


def test_all_backends_have_required_methods():
    for cls in [PlaywrightMCPBackend, PlaywrightBackend, BrowserbaseBackend, BrowserbaseMCPBackend]:
        assert hasattr(cls, "status")
        assert hasattr(cls, "astatus")
        assert hasattr(cls, "get_tools")
        assert hasattr(cls, "asetup")
        assert hasattr(cls, "aclose")


# ---------------------------------------------------------------------------
# PlaywrightMCPBackend
# ---------------------------------------------------------------------------


def test_playwright_mcp_status_ok_before_connect():
    backend = PlaywrightMCPBackend()
    status = backend.status()
    assert status.ok is True
    assert "playwright-mcp" in status.detail
    assert "not yet connected" in status.detail


def test_playwright_mcp_status_ok_when_initialized():
    backend = PlaywrightMCPBackend()
    backend._mcp_tools = MagicMock()
    backend._mcp_tools.initialized = True
    status = backend.status()
    assert status.ok is True
    assert status.detail == "playwright-mcp"


def test_playwright_mcp_default_configuration():
    backend = PlaywrightMCPBackend()
    assert backend.headless is True
    assert backend.include_tools is None
    assert backend.exclude_tools is None
    assert backend.tool_name_prefix is None
    assert backend.timeout_seconds == 60


def test_playwright_mcp_custom_configuration():
    backend = PlaywrightMCPBackend(
        headless=False,
        include_tools=["browser_navigate", "browser_snapshot"],
        exclude_tools=["browser_pdf_save"],
        tool_name_prefix="pw",
        timeout_seconds=120,
    )
    assert backend.headless is False
    assert backend.include_tools == ["browser_navigate", "browser_snapshot"]
    assert backend.exclude_tools == ["browser_pdf_save"]
    assert backend.tool_name_prefix == "pw"
    assert backend.timeout_seconds == 120


def test_playwright_mcp_get_tools_returns_list():
    backend = PlaywrightMCPBackend()
    tools = backend.get_tools()
    assert isinstance(tools, list)
    assert len(tools) == 1


@pytest.mark.asyncio
async def test_playwright_mcp_astatus_not_ok_when_connect_fails():
    backend = PlaywrightMCPBackend()

    async def failing_connect():
        raise ConnectionError("MCP server not found")

    with patch.object(backend, "_ensure_session", failing_connect):
        status = await backend.astatus()
        assert status.ok is False
        assert "ConnectionError" in status.detail


@pytest.mark.asyncio
async def test_playwright_mcp_asetup_swallows_connect_errors():
    backend = PlaywrightMCPBackend()

    async def failing_connect():
        raise RuntimeError("npx not found")

    with patch.object(backend, "_ensure_session", failing_connect):
        await backend.asetup()


@pytest.mark.asyncio
async def test_playwright_mcp_aclose_noop_when_never_connected():
    backend = PlaywrightMCPBackend()
    await backend.aclose()
    assert backend._mcp_tools is None


@pytest.mark.asyncio
async def test_playwright_mcp_aclose_clears_cache():
    backend = PlaywrightMCPBackend()
    mock_tools = MagicMock()
    mock_tools.close = MagicMock(return_value=None)
    backend._mcp_tools = mock_tools

    await backend.aclose()
    assert backend._mcp_tools is None


# ---------------------------------------------------------------------------
# PlaywrightBackend
# ---------------------------------------------------------------------------


def test_playwright_backend_status_ok_headless():
    backend = PlaywrightBackend()
    status = backend.status()
    assert status.ok is True
    assert "playwright" in status.detail
    assert "local" in status.detail
    assert "headless" in status.detail


def test_playwright_backend_status_ok_headed():
    backend = PlaywrightBackend(headless=False)
    status = backend.status()
    assert status.ok is True
    assert "headed" in status.detail


def test_playwright_backend_default_configuration():
    backend = PlaywrightBackend()
    assert backend.headless is True


def test_playwright_backend_get_tools_returns_list():
    backend = PlaywrightBackend()
    tools = backend.get_tools()
    assert isinstance(tools, list)
    assert len(tools) == 1


@pytest.mark.asyncio
async def test_playwright_backend_astatus_delegates_to_status():
    backend = PlaywrightBackend()
    sync_status = backend.status()
    async_status = await backend.astatus()
    assert sync_status.ok == async_status.ok
    assert sync_status.detail == async_status.detail


@pytest.mark.asyncio
async def test_playwright_backend_aclose_noop_when_never_used():
    backend = PlaywrightBackend()
    await backend.aclose()
    assert backend._tools is None


# ---------------------------------------------------------------------------
# BrowserbaseBackend
# ---------------------------------------------------------------------------


def test_browserbase_backend_status_ok_with_credentials():
    backend = BrowserbaseBackend(api_key="bb_live_xxx", project_id="proj_123")
    status = backend.status()
    assert status.ok is True
    assert "browserbase" in status.detail


def test_browserbase_backend_status_not_ok_missing_api_key(monkeypatch):
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    monkeypatch.delenv("BROWSERBASE_PROJECT_ID", raising=False)
    backend = BrowserbaseBackend()
    status = backend.status()
    assert status.ok is False
    assert "BROWSERBASE_API_KEY" in status.detail


def test_browserbase_backend_status_not_ok_missing_project_id(monkeypatch):
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    monkeypatch.delenv("BROWSERBASE_PROJECT_ID", raising=False)
    backend = BrowserbaseBackend(api_key="bb_live_xxx")
    status = backend.status()
    assert status.ok is False
    assert "BROWSERBASE_PROJECT_ID" in status.detail


def test_browserbase_backend_reads_credentials_from_env(monkeypatch):
    monkeypatch.setenv("BROWSERBASE_API_KEY", "bb_env_key")
    monkeypatch.setenv("BROWSERBASE_PROJECT_ID", "proj_env")
    backend = BrowserbaseBackend()
    assert backend.api_key == "bb_env_key"
    assert backend.project_id == "proj_env"
    status = backend.status()
    assert status.ok is True


def test_browserbase_backend_get_tools_returns_list():
    backend = BrowserbaseBackend(api_key="x", project_id="y")
    tools = backend.get_tools()
    assert isinstance(tools, list)
    assert len(tools) == 1


@pytest.mark.asyncio
async def test_browserbase_backend_astatus_delegates_to_status():
    backend = BrowserbaseBackend(api_key="x", project_id="y")
    sync_status = backend.status()
    async_status = await backend.astatus()
    assert sync_status.ok == async_status.ok


# ---------------------------------------------------------------------------
# BrowserbaseMCPBackend
# ---------------------------------------------------------------------------


def test_browserbase_mcp_status_ok_with_credentials():
    backend = BrowserbaseMCPBackend(api_key="bb_live_xxx", project_id="proj_123", model_api_key="gemini_key")
    status = backend.status()
    assert status.ok is True
    assert "browserbase-mcp" in status.detail


def test_browserbase_mcp_status_not_ok_missing_api_key(monkeypatch):
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    monkeypatch.delenv("BROWSERBASE_PROJECT_ID", raising=False)
    backend = BrowserbaseMCPBackend()
    status = backend.status()
    assert status.ok is False
    assert "BROWSERBASE_API_KEY" in status.detail


def test_browserbase_mcp_status_not_ok_missing_project_id(monkeypatch):
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    monkeypatch.delenv("BROWSERBASE_PROJECT_ID", raising=False)
    backend = BrowserbaseMCPBackend(api_key="bb_live_xxx")
    status = backend.status()
    assert status.ok is False
    assert "BROWSERBASE_PROJECT_ID" in status.detail


def test_browserbase_mcp_default_configuration():
    backend = BrowserbaseMCPBackend(api_key="x", project_id="y")
    assert backend.include_tools is None
    assert backend.exclude_tools is None
    assert backend.tool_name_prefix == "browser"
    assert backend.timeout_seconds == 60


def test_browserbase_mcp_custom_configuration():
    backend = BrowserbaseMCPBackend(
        api_key="x",
        project_id="y",
        include_tools=["navigate"],
        exclude_tools=["screenshot"],
        tool_name_prefix="bb",
        timeout_seconds=90,
    )
    assert backend.include_tools == ["navigate"]
    assert backend.exclude_tools == ["screenshot"]
    assert backend.tool_name_prefix == "bb"
    assert backend.timeout_seconds == 90


def test_browserbase_mcp_get_tools_returns_list():
    backend = BrowserbaseMCPBackend(api_key="x", project_id="y")
    tools = backend.get_tools()
    assert isinstance(tools, list)
    assert len(tools) == 1


@pytest.mark.asyncio
async def test_browserbase_mcp_astatus_not_ok_when_connect_fails():
    backend = BrowserbaseMCPBackend(api_key="x", project_id="y")

    async def failing_connect():
        raise ConnectionError("MCP server not found")

    with patch.object(backend, "_ensure_session", failing_connect):
        status = await backend.astatus()
        assert status.ok is False
        assert "ConnectionError" in status.detail


@pytest.mark.asyncio
async def test_browserbase_mcp_aclose_noop_when_never_connected():
    backend = BrowserbaseMCPBackend(api_key="x", project_id="y")
    await backend.aclose()
    assert backend._mcp_tools is None


# ---------------------------------------------------------------------------
# BrowserContextProvider — Default Backend Creation
# ---------------------------------------------------------------------------


def test_provider_creates_default_backend_when_none_provided():
    provider = BrowserContextProvider()
    assert provider.backend is not None
    assert isinstance(provider.backend, PlaywrightMCPBackend)


def test_provider_default_backend_excludes_write_tools():
    provider = BrowserContextProvider()
    backend = provider.backend
    assert isinstance(backend, PlaywrightMCPBackend)
    assert backend.exclude_tools == [
        "browser_type",
        "browser_select_option",
        "browser_press_key",
        "browser_file_upload",
    ]


def test_provider_default_backend_is_headless():
    provider = BrowserContextProvider()
    backend = provider.backend
    assert isinstance(backend, PlaywrightMCPBackend)
    assert backend.headless is True


def test_provider_default_backend_headed_when_specified():
    provider = BrowserContextProvider(headless=False)
    backend = provider.backend
    assert isinstance(backend, PlaywrightMCPBackend)
    assert backend.headless is False


# ---------------------------------------------------------------------------
# BrowserContextProvider — write=True/False
# ---------------------------------------------------------------------------


def test_provider_write_false_excludes_write_tools():
    provider = BrowserContextProvider(write=False)
    backend = provider.backend
    assert isinstance(backend, PlaywrightMCPBackend)
    assert backend.exclude_tools == [
        "browser_type",
        "browser_select_option",
        "browser_press_key",
        "browser_file_upload",
    ]


def test_provider_write_true_does_not_exclude_write_tools():
    provider = BrowserContextProvider(write=True)
    backend = provider.backend
    assert isinstance(backend, PlaywrightMCPBackend)
    assert backend.exclude_tools is None


def test_provider_explicit_backend_ignores_write_flag():
    explicit_backend = PlaywrightMCPBackend(exclude_tools=["custom_excluded"])
    provider = BrowserContextProvider(backend=explicit_backend, write=False)
    assert provider.backend.exclude_tools == ["custom_excluded"]


# ---------------------------------------------------------------------------
# BrowserContextProvider — Identity
# ---------------------------------------------------------------------------


def test_provider_default_id_and_name():
    provider = BrowserContextProvider()
    assert provider.id == "browser"
    assert provider.name == "Browser"


def test_provider_custom_id_and_name():
    provider = BrowserContextProvider(id="chrome", name="Chrome Browser")
    assert provider.id == "chrome"
    assert provider.name == "Chrome Browser"


def test_provider_query_tool_name_derives_from_id():
    provider = BrowserContextProvider()
    assert provider.query_tool_name == "query_browser"


def test_provider_custom_id_changes_query_tool_name():
    provider = BrowserContextProvider(id="selenium")
    assert provider.query_tool_name == "query_selenium"


# ---------------------------------------------------------------------------
# BrowserContextProvider — Status Delegation
# ---------------------------------------------------------------------------


def test_provider_status_delegates_to_playwright_mcp_backend():
    backend = PlaywrightMCPBackend()
    provider = BrowserContextProvider(backend=backend)
    status = provider.status()
    assert status.ok is True
    assert "playwright-mcp" in status.detail


def test_provider_status_delegates_to_browserbase_backend():
    backend = BrowserbaseBackend(api_key="bb_live_xxx", project_id="proj_123")
    provider = BrowserContextProvider(backend=backend)
    status = provider.status()
    assert status.ok is True
    assert "browserbase" in status.detail


def test_provider_status_reflects_backend_failure(monkeypatch):
    monkeypatch.delenv("BROWSERBASE_API_KEY", raising=False)
    monkeypatch.delenv("BROWSERBASE_PROJECT_ID", raising=False)
    backend = BrowserbaseBackend()
    provider = BrowserContextProvider(backend=backend)
    status = provider.status()
    assert status.ok is False


# ---------------------------------------------------------------------------
# BrowserContextProvider — Mode and Tools
# ---------------------------------------------------------------------------


def test_provider_default_mode_returns_query_tool():
    provider = BrowserContextProvider()
    tools = provider.get_tools()
    tool_names = [t.name for t in tools]
    assert tool_names == ["query_browser"]


def test_provider_tools_mode_returns_backend_tools():
    provider = BrowserContextProvider(mode=ContextMode.tools)
    tools = provider.get_tools()
    assert len(tools) == 1


def test_provider_agent_mode_returns_query_tool():
    provider = BrowserContextProvider(mode=ContextMode.agent)
    tools = provider.get_tools()
    tool_names = [t.name for t in tools]
    assert tool_names == ["query_browser"]


# ---------------------------------------------------------------------------
# BrowserContextProvider — Instructions
# ---------------------------------------------------------------------------


def test_provider_instructions_default_mode_mentions_query_tool():
    provider = BrowserContextProvider()
    instructions = provider.instructions()
    assert "query_browser" in instructions


def test_provider_instructions_tools_mode_mentions_browser():
    provider = BrowserContextProvider(mode=ContextMode.tools)
    instructions = provider.instructions()
    assert "browser" in instructions.lower()


def test_provider_custom_instructions():
    custom = "Use the browser to search the web."
    provider = BrowserContextProvider(instructions=custom)
    assert provider.instructions_text == custom


def test_provider_default_instructions_exist():
    provider = BrowserContextProvider()
    assert provider.instructions_text is not None
    assert len(provider.instructions_text) > 0
    assert "Navigate" in provider.instructions_text or "navigate" in provider.instructions_text


# ---------------------------------------------------------------------------
# BrowserContextProvider — Agent Building
# ---------------------------------------------------------------------------


def test_provider_ensure_agent_creates_agent():
    provider = BrowserContextProvider()
    agent = provider._ensure_agent()
    assert agent is not None
    assert agent.id == "browser"
    assert agent.name == "Browser"


def test_provider_ensure_agent_caches_agent():
    provider = BrowserContextProvider()
    agent1 = provider._ensure_agent()
    agent2 = provider._ensure_agent()
    assert agent1 is agent2


def test_provider_build_agent_uses_backend_tools():
    backend = PlaywrightMCPBackend()
    provider = BrowserContextProvider(backend=backend)
    agent = provider._build_agent()
    assert agent.tools is not None
    assert len(agent.tools) > 0


def test_provider_build_agent_uses_custom_model():
    from agno.models.openai import OpenAIResponses

    model = OpenAIResponses(id="gpt-5.5")
    provider = BrowserContextProvider(model=model)
    agent = provider._build_agent()
    assert agent.model is model


# ---------------------------------------------------------------------------
# BrowserContextProvider — Query
# ---------------------------------------------------------------------------


def test_provider_sync_query_raises_not_implemented():
    provider = BrowserContextProvider()
    with pytest.raises(NotImplementedError, match="async-only"):
        provider.query("search something")


# ---------------------------------------------------------------------------
# BrowserContextProvider — Async Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_aclose_clears_agent_cache():
    provider = BrowserContextProvider()
    _ = provider._ensure_agent()
    assert provider._agent is not None
    await provider.aclose()
    assert provider._agent is None


@pytest.mark.asyncio
async def test_provider_astatus_delegates_to_backend():
    backend = PlaywrightMCPBackend()
    backend._mcp_tools = MagicMock()
    backend._mcp_tools.initialized = True

    async def mock_ensure_session():
        return backend._mcp_tools

    with patch.object(backend, "_ensure_session", mock_ensure_session):
        provider = BrowserContextProvider(backend=backend)
        status = await provider.astatus()
        assert status.ok is True
        assert "playwright-mcp" in status.detail


@pytest.mark.asyncio
async def test_provider_asetup_delegates_to_backend():
    backend = PlaywrightMCPBackend()
    setup_called = False

    async def mock_asetup():
        nonlocal setup_called
        setup_called = True

    with patch.object(backend, "asetup", mock_asetup):
        provider = BrowserContextProvider(backend=backend)
        await provider.asetup()
        assert setup_called
