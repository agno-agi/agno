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
from agno.context.mcp import MCPContextProvider
from agno.context.web import ExaBackend, WebContextProvider

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
    # Not yet connected — we don't want to force an async connect from sync code.
    assert status.ok is True
    assert "not yet connected" in status.detail


def test_mcp_sync_query_raises_not_implemented():
    p = MCPContextProvider("srv", transport="streamable-http", url="https://example.com/mcp")
    with pytest.raises(NotImplementedError, match="sync query"):
        p.query("anything")
