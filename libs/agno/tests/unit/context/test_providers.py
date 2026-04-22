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
from agno.context.slack import SlackContextProvider
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


def test_slack_default_surface_is_single_query_tool():
    p = SlackContextProvider(token="xoxb-x")
    tools = p.get_tools()
    assert [t.name for t in tools] == ["query_slack"]


def test_slack_status_reports_configured():
    p = SlackContextProvider(token="xoxb-x")
    status = p.status()
    assert status.ok is True
    assert "token configured" in status.detail


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
