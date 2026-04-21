"""Unit tests for WebContextProvider and its three backends."""

from unittest.mock import patch

import pytest

from agno.context import ContextMode, Status
from agno.context.backend import ContextBackend
from agno.context.web import WebContextProvider
from agno.context.web.exa import ExaBackend
from agno.context.web.exa_mcp import ExaMCPBackend
from agno.context.web.parallel import ParallelBackend

# ---------------------------------------------------------------------------
# StubBackend — drives the WebContextProvider tests without real SDKs
# ---------------------------------------------------------------------------


class StubBackend(ContextBackend):
    def __init__(self, *, ok: bool = True, detail: str = "stub"):
        self._status = Status(ok=ok, detail=detail)
        self._tools_calls = 0

    def status(self) -> Status:
        return self._status

    async def astatus(self) -> Status:
        return self._status

    def get_tools(self) -> list:
        self._tools_calls += 1
        return ["fake_search_tool", "fake_fetch_tool"]


# ---------------------------------------------------------------------------
# WebContextProvider
# ---------------------------------------------------------------------------


def test_construction_defaults():
    p = WebContextProvider(backend=StubBackend())
    assert p.id == "web"
    assert p.name == "Web"
    assert p.mode == ContextMode.default
    assert p.query_tool_name == "query_web"


def test_status_delegates_to_backend():
    backend = StubBackend(ok=False, detail="no-key")
    p = WebContextProvider(backend=backend)
    s = p.status()
    assert s.ok is False
    assert s.detail == "no-key"


@pytest.mark.asyncio
async def test_astatus_delegates_to_backend():
    backend = StubBackend(ok=True, detail="ok")
    p = WebContextProvider(backend=backend)
    s = await p.astatus()
    assert s.ok is True
    assert s.detail == "ok"


def test_default_mode_returns_backend_tools():
    backend = StubBackend()
    p = WebContextProvider(backend=backend, mode=ContextMode.default)
    tools = p.get_tools()
    assert tools == ["fake_search_tool", "fake_fetch_tool"]


def test_tools_mode_returns_backend_tools():
    backend = StubBackend()
    p = WebContextProvider(backend=backend, mode=ContextMode.tools)
    tools = p.get_tools()
    assert tools == ["fake_search_tool", "fake_fetch_tool"]


def test_agent_mode_returns_single_query_tool():
    backend = StubBackend()
    p = WebContextProvider(backend=backend, mode=ContextMode.agent)
    tools = p.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "query_web"


def test_agent_mode_builds_agent_without_error():
    """Agent mode is implemented but not exercised end-to-end in scout.
    At minimum, constructing the sub-agent should not raise."""
    backend = StubBackend()
    p = WebContextProvider(backend=backend, mode=ContextMode.agent)
    agent = p._build_agent()
    assert agent.id == "web"
    assert agent.name == "Web"


def test_instructions_differs_by_mode():
    backend = StubBackend()
    p_default = WebContextProvider(backend=backend, mode=ContextMode.default)
    p_agent = WebContextProvider(backend=backend, mode=ContextMode.agent)
    assert p_default.instructions() != p_agent.instructions()


# ---------------------------------------------------------------------------
# ParallelBackend
# ---------------------------------------------------------------------------


def test_parallel_status_without_key(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    b = ParallelBackend()
    s = b.status()
    assert s.ok is False
    assert "PARALLEL_API_KEY" in s.detail


def test_parallel_status_with_key():
    b = ParallelBackend(api_key="fake-key")
    s = b.status()
    assert s.ok is True
    assert "parallel" in s.detail.lower()


def test_parallel_get_tools_shape():
    b = ParallelBackend(api_key="fake-key")
    tools = b.get_tools()
    names = [t.name for t in tools]
    assert names == ["web_search", "web_extract"]


# ---------------------------------------------------------------------------
# ExaBackend
# ---------------------------------------------------------------------------


def test_exa_status_without_key(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    b = ExaBackend()
    s = b.status()
    assert s.ok is False
    assert "EXA_API_KEY" in s.detail


def test_exa_status_with_key():
    b = ExaBackend(api_key="fake-key")
    s = b.status()
    assert s.ok is True
    assert "exa" in s.detail.lower()


def test_exa_get_tools_shape():
    b = ExaBackend(api_key="fake-key")
    tools = b.get_tools()
    names = [t.name for t in tools]
    assert names == ["web_search", "web_extract"]


# ---------------------------------------------------------------------------
# ExaMCPBackend
# ---------------------------------------------------------------------------


def test_exa_mcp_keyless_url(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    b = ExaMCPBackend()
    assert b.api_key is None
    assert "exaApiKey" not in b.url
    assert "tools=" in b.url


def test_exa_mcp_keyed_url():
    b = ExaMCPBackend(api_key="secret")
    assert b.api_key == "secret"
    assert "exaApiKey=secret" in b.url


def test_exa_mcp_status_is_ok_either_way(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    b = ExaMCPBackend()
    assert b.status().ok is True
    assert "keyless" in b.status().detail

    b_keyed = ExaMCPBackend(api_key="secret")
    assert b_keyed.status().ok is True
    assert "keyed" in b_keyed.status().detail


def test_exa_mcp_get_tools_is_cached():
    b = ExaMCPBackend(api_key="secret")
    # Stub out MCPTools so we don't hit real transport setup
    with patch("agno.tools.mcp.MCPTools") as mock_mcp:
        mock_mcp.return_value = object()
        tools1 = b.get_tools()
        tools2 = b.get_tools()
        assert tools1 == tools2  # cached
        assert mock_mcp.call_count == 1
