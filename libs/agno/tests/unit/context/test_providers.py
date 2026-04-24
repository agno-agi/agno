"""Smoke tests for the concrete context providers.

These don't hit any external service — they only check constructor
defaults, tool-surface shape, and status behaviour on invalid input.
The full end-to-end behaviour is covered by the cookbooks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from agno.context.database import DatabaseContextProvider
from agno.context.fs import FilesystemContextProvider
from agno.context.gdrive import GDriveContextProvider
from agno.context.mcp import MCPContextProvider
from agno.context.slack import SlackContextProvider
from agno.context.web import ExaBackend, ExaMCPBackend, ParallelMCPBackend, WebContextProvider

# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


def test_fs_status_ok_for_existing_dir(tmp_path: Path):
    p = FilesystemContextProvider(root=tmp_path)
    status = p.status()
    assert status.ok is True
    assert str(tmp_path) in status.detail


def test_fs_status_reports_missing_root(tmp_path: Path):
    missing = tmp_path / "does-not-exist"
    p = FilesystemContextProvider(root=missing)
    status = p.status()
    assert status.ok is False
    assert "does not exist" in status.detail


def test_fs_status_reports_non_directory(tmp_path: Path):
    file_ = tmp_path / "a.txt"
    file_.write_text("hi")
    p = FilesystemContextProvider(root=file_)
    status = p.status()
    assert status.ok is False
    assert "not a directory" in status.detail


def test_fs_default_surface_is_single_query_tool(tmp_path: Path):
    p = FilesystemContextProvider(root=tmp_path, id="docs")
    tools = p.get_tools()
    assert [t.name for t in tools] == ["query_docs"]


# ---------------------------------------------------------------------------
# Web / ExaBackend
# ---------------------------------------------------------------------------


def test_exa_backend_missing_api_key_fails_status(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    b = ExaBackend()
    status = b.status()
    assert status.ok is False
    assert "EXA_API_KEY" in status.detail


def test_web_provider_exposes_query_tool():
    p = WebContextProvider(backend=ExaBackend(api_key="x"))
    tools = p.get_tools()
    assert [t.name for t in tools] == ["query_web"]


def test_web_provider_forwards_status_from_backend():
    p = WebContextProvider(backend=ExaBackend(api_key="x"))
    assert p.status().ok is True


def test_exa_mcp_backend_keyless_status_ok(monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    b = ExaMCPBackend()
    status = b.status()
    assert status.ok is True
    assert status.detail == "mcp.exa.ai (keyless)"


def test_exa_mcp_backend_keyed_status_reports_keyed():
    b = ExaMCPBackend(api_key="secret")
    assert b.status().detail == "mcp.exa.ai (keyed)"


def test_exa_mcp_backend_default_include_tools():
    b = ExaMCPBackend(api_key="x")
    assert b.include_tools == ["web_search_exa", "web_fetch_exa"]
    assert "tools=web_search_exa,web_fetch_exa" in b.url


def test_exa_mcp_backend_custom_include_tools():
    b = ExaMCPBackend(api_key="x", include_tools=["web_search_exa"])
    assert b.include_tools == ["web_search_exa"]
    assert "tools=web_search_exa" in b.url


def test_exa_mcp_backend_include_tools_none_passes_empty():
    b = ExaMCPBackend(api_key="x", include_tools=None)
    assert b.include_tools is None
    assert "tools=" in b.url


def test_exa_mcp_backend_exclude_tools_propagates():
    b = ExaMCPBackend(api_key="x", exclude_tools=["web_fetch_exa"])
    assert b.exclude_tools == ["web_fetch_exa"]
    tools = b.get_tools()
    assert tools[0].exclude_tools == ["web_fetch_exa"]


def test_exa_mcp_backend_tool_name_prefix_propagates():
    b = ExaMCPBackend(api_key="x", tool_name_prefix="exa")
    assert b.tool_name_prefix == "exa"
    tools = b.get_tools()
    assert tools[0].tool_name_prefix == "exa"


def test_parallel_mcp_backend_keyless_status_ok(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    b = ParallelMCPBackend()
    status = b.status()
    assert status.ok is True
    assert status.detail == "search.parallel.ai/mcp (keyless)"


def test_parallel_mcp_backend_keyed_status_reports_keyed():
    b = ParallelMCPBackend(api_key="secret")
    status = b.status()
    assert status.ok is True
    assert status.detail == "search.parallel.ai/mcp (keyed)"


def test_parallel_mcp_backend_picks_up_env_var(monkeypatch):
    monkeypatch.setenv("PARALLEL_API_KEY", "env-secret")
    b = ParallelMCPBackend()
    assert b.api_key == "env-secret"
    assert b.status().detail == "search.parallel.ai/mcp (keyed)"


def test_parallel_mcp_backend_authenticated_requires_api_key(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="authenticated=True requires api_key"):
        ParallelMCPBackend(authenticated=True)


def test_parallel_mcp_backend_authenticated_uses_oauth_endpoint():
    b = ParallelMCPBackend(api_key="secret", authenticated=True)
    assert b.url == "https://search.parallel.ai/mcp-oauth"
    assert b.status().detail == "search.parallel.ai/mcp-oauth (keyed)"


def test_parallel_mcp_backend_builds_mcp_tools_with_bearer_header():
    b = ParallelMCPBackend(api_key="secret")
    tools = b.get_tools()
    assert len(tools) == 1
    mcp_tools = tools[0]
    params = mcp_tools.server_params
    assert params.url == "https://search.parallel.ai/mcp"
    assert params.headers == {"Authorization": "Bearer secret"}
    assert mcp_tools.include_tools == ["web_search", "web_fetch"]
    assert mcp_tools.timeout_seconds == 60


def test_parallel_mcp_backend_keyless_has_no_auth_header(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    b = ParallelMCPBackend()
    tools = b.get_tools()
    assert tools[0].server_params.headers is None


def test_parallel_mcp_backend_custom_timeout_propagates():
    b = ParallelMCPBackend(api_key="x", timeout_seconds=120)
    tools = b.get_tools()
    assert tools[0].timeout_seconds == 120


def test_parallel_mcp_backend_custom_include_tools():
    b = ParallelMCPBackend(api_key="x", include_tools=["web_search"])
    tools = b.get_tools()
    assert tools[0].include_tools == ["web_search"]


def test_parallel_mcp_backend_include_tools_none_passes_none():
    b = ParallelMCPBackend(api_key="x", include_tools=None)
    tools = b.get_tools()
    assert tools[0].include_tools is None


def test_parallel_mcp_backend_exclude_tools_propagates():
    b = ParallelMCPBackend(api_key="x", exclude_tools=["web_fetch"])
    assert b.exclude_tools == ["web_fetch"]
    tools = b.get_tools()
    assert tools[0].exclude_tools == ["web_fetch"]


def test_parallel_mcp_backend_tool_name_prefix_propagates():
    b = ParallelMCPBackend(api_key="x", tool_name_prefix="parallel")
    assert b.tool_name_prefix == "parallel"
    tools = b.get_tools()
    assert tools[0].tool_name_prefix == "parallel"


def test_web_provider_accepts_parallel_mcp_backend(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    p = WebContextProvider(backend=ParallelMCPBackend())
    assert [t.name for t in p.get_tools()] == ["query_web"]
    assert p.status().ok is True


@pytest.mark.asyncio
async def test_parallel_mcp_backend_asetup_swallows_errors_and_retries(monkeypatch):
    from agno.tools.mcp import MCPTools

    b = ParallelMCPBackend(api_key="test-key", timeout_seconds=1)

    calls = {"n": 0}

    async def _fail(self_):
        calls["n"] += 1
        raise RuntimeError("connect failed")

    monkeypatch.setattr(MCPTools, "_connect", _fail)

    await b.asetup()
    assert b._mcp_tools is None

    await b.asetup()
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_parallel_mcp_backend_aclose_noop_when_never_connected():
    b = ParallelMCPBackend(api_key="test-key")
    await b.aclose()
    assert b._mcp_tools is None


@pytest.mark.asyncio
async def test_parallel_mcp_backend_aclose_swallows_close_errors(monkeypatch):
    from agno.tools.mcp import MCPTools

    b = ParallelMCPBackend(api_key="test-key")
    b._mcp_tools = b._build_tools()

    async def _close_fails(self_):
        raise RuntimeError("close failed")

    monkeypatch.setattr(MCPTools, "close", _close_fails)

    await b.aclose()
    assert b._mcp_tools is None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def test_db_default_surface_is_query_plus_update():
    engine = create_engine("sqlite:///:memory:")
    p = DatabaseContextProvider(
        id="crm",
        name="CRM",
        sql_engine=engine,
        readonly_engine=engine,
    )
    tools = p.get_tools()
    assert [t.name for t in tools] == ["query_crm", "update_crm"]


def test_db_status_ok_on_connectable_engine():
    engine = create_engine("sqlite:///:memory:")
    p = DatabaseContextProvider(
        id="crm",
        name="CRM",
        sql_engine=engine,
        readonly_engine=engine,
    )
    assert p.status().ok is True


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


def test_slack_requires_token(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
        SlackContextProvider()


def test_slack_falls_back_to_slack_token(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_TOKEN", "xoxb-fallback")
    p = SlackContextProvider()
    assert p.token == "xoxb-fallback"


def test_slack_default_surface_is_query_plus_update():
    p = SlackContextProvider(token="xoxb-x")
    tools = p.get_tools()
    assert [t.name for t in tools] == ["query_slack", "update_slack"]


def test_slack_status_reports_configured():
    p = SlackContextProvider(token="xoxb-x")
    status = p.status()
    assert status.ok is True
    assert "token configured" in status.detail


@pytest.mark.asyncio
async def test_slack_aupdate_routes_through_write_agent(monkeypatch):
    """aupdate must hit the write sub-agent, not the read one."""
    from agno.context.provider import Answer

    p = SlackContextProvider(token="xoxb-x")

    calls: dict[str, int] = {"read": 0, "write": 0}

    class _StubAgent:
        def __init__(self, bucket: str):
            self._bucket = bucket

        async def arun(self, instruction: str, **kwargs):
            calls[self._bucket] += 1

            class _Out:
                content = f"{self._bucket}:{instruction}"

                def get_content_as_string(self):
                    return self.content

            return _Out()

    p._read_agent = _StubAgent("read")  # type: ignore[assignment]
    p._write_agent = _StubAgent("write")  # type: ignore[assignment]

    out = await p.aupdate("post hello to #ops")
    assert isinstance(out, Answer)
    assert calls == {"read": 0, "write": 1}
    assert out.text == "write:post hello to #ops"


@pytest.mark.asyncio
async def test_slack_aquery_threads_action_token_metadata_to_subagent(monkeypatch):
    """The BLOCKER this PR fixes: Slack's search_workspace needs
    run_context.metadata["action_token"] to authenticate. If the
    caller's RunContext has action_token in metadata, aquery must
    forward it into sub_agent.arun(metadata=...) so the sub-agent's
    call to search_workspace sees it.
    """
    from unittest.mock import AsyncMock, MagicMock

    from agno.context.provider import Answer
    from agno.run import RunContext

    p = SlackContextProvider(token="xoxb-x")

    # Replace the read sub-agent with a mock whose arun tracks kwargs.
    # (After upstream's write-access split, aquery goes through
    # _ensure_read_agent, not _ensure_agent.)
    mock_agent = MagicMock()
    mock_run_output = MagicMock()
    mock_run_output.get_content_as_string = MagicMock(return_value="mock answer")
    mock_run_output.content = "mock answer"
    mock_agent.arun = AsyncMock(return_value=mock_run_output)
    monkeypatch.setattr(p, "_ensure_read_agent", lambda: mock_agent)

    # Caller's RunContext carries the action_token the Slack interface
    # would have injected.
    rc = RunContext(
        run_id="r-slack-1",
        session_id="s-slack-1",
        user_id="U123",
        metadata={"action_token": "xoxa-2-abc-def"},
    )
    answer = await p.aquery("find recent chatter about launch", run_context=rc)

    # Sub-agent must have been called with the metadata threaded through.
    mock_agent.arun.assert_awaited_once()
    _, kwargs = mock_agent.arun.call_args
    assert kwargs.get("metadata") == {"action_token": "xoxa-2-abc-def"}, (
        f"expected action_token to propagate; got kwargs={kwargs}"
    )
    assert kwargs.get("user_id") == "U123"
    assert kwargs.get("session_id") == "s-slack-1"
    assert isinstance(answer, Answer)


# ---------------------------------------------------------------------------
# Google Drive
# ---------------------------------------------------------------------------


def test_gdrive_requires_service_account_path(monkeypatch):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    with pytest.raises(ValueError, match="GOOGLE_SERVICE_ACCOUNT_FILE"):
        GDriveContextProvider()


def test_gdrive_status_reports_missing_sa_file(tmp_path):
    missing = tmp_path / "no-such-sa.json"
    p = GDriveContextProvider(service_account_path=str(missing))
    status = p.status()
    assert status.ok is False
    assert "service account file not found" in status.detail


def test_gdrive_status_ok_when_sa_file_exists(tmp_path):
    sa = tmp_path / "sa.json"
    sa.write_text("{}")
    p = GDriveContextProvider(service_account_path=str(sa))
    assert p.status().ok is True


def test_gdrive_default_surface_is_single_query_tool(tmp_path):
    sa = tmp_path / "sa.json"
    sa.write_text("{}")
    p = GDriveContextProvider(service_account_path=str(sa))
    tools = p.get_tools()
    assert [t.name for t in tools] == ["query_gdrive"]


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------


def test_mcp_stdio_requires_command():
    with pytest.raises(ValueError, match="transport=stdio requires `command`"):
        MCPContextProvider("srv", transport="stdio")


def test_mcp_http_requires_url():
    with pytest.raises(ValueError, match="requires `url`"):
        MCPContextProvider("srv", transport="streamable-http")


def test_mcp_id_auto_sanitized_from_server_name():
    p = MCPContextProvider("My.Server", transport="streamable-http", url="https://example.com/mcp")
    assert p.id == "mcp_my_server"
    assert p.query_tool_name == "query_mcp_my_server"


def test_mcp_status_before_connect_reports_pending():
    p = MCPContextProvider("srv", transport="streamable-http", url="https://example.com/mcp")
    status = p.status()
    # Not yet connected — sync status() must not force an async connect.
    assert status.ok is True
    assert "not yet connected" in status.detail


def test_mcp_sync_query_raises_not_implemented():
    p = MCPContextProvider("srv", transport="streamable-http", url="https://example.com/mcp")
    with pytest.raises(NotImplementedError, match="sync query"):
        p.query("anything")


def test_mcp_kwargs_escape_hatch_forwards_to_mcptools():
    p = MCPContextProvider(
        "srv",
        transport="streamable-http",
        url="https://example.com/mcp",
        timeout_seconds=5,
        mcp_kwargs={"tool_name_prefix": "srv_", "timeout_seconds": 99},
    )
    tools = p._build_tools_instance()
    # User-provided keys win over provider-computed ones (timeout 99 > 5).
    assert tools.timeout_seconds == 99
    assert tools.tool_name_prefix == "srv_"


@pytest.mark.asyncio
async def test_mcp_asetup_swallows_errors_and_is_retriable(monkeypatch):
    p = MCPContextProvider(
        "srv",
        transport="streamable-http",
        url="https://example.com/mcp",
        timeout_seconds=1,
    )

    calls = {"n": 0}

    async def _fail(self_):
        calls["n"] += 1
        raise RuntimeError("connect failed")

    monkeypatch.setattr(MCPContextProvider, "_ensure_session", _fail)

    # Must not raise — asetup logs and clears partial state.
    await p.asetup()
    assert p._tools is None
    assert p._tool_descriptions == []

    # Second call is also safe (idempotent under failure) and retries.
    await p.asetup()
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_mcp_asetup_timeout_bounded_by_timeout_seconds(monkeypatch):
    """asetup must give up after timeout_seconds rather than hang forever."""
    import asyncio as _asyncio

    p = MCPContextProvider(
        "srv",
        transport="streamable-http",
        url="https://example.com/mcp",
        timeout_seconds=0,  # wait_for(timeout=0) → immediate TimeoutError
    )

    async def _hang(self_):
        await _asyncio.sleep(60)  # would hang if not bounded

    monkeypatch.setattr(MCPContextProvider, "_ensure_session", _hang)

    # Must return promptly without raising.
    await p.asetup()
    assert p._tools is None


@pytest.mark.asyncio
async def test_mcp_aclose_noop_when_never_connected():
    p = MCPContextProvider("srv", transport="streamable-http", url="https://example.com/mcp")
    # Must not raise even though asetup was never called.
    await p.aclose()
