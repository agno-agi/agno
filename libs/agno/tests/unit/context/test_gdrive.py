"""Unit tests for GDriveContextProvider.

The brief flagged that Slack/GDrive write-filtering had not been
re-verified with the same rigor as GitHub. These tests verify that
upload/download/delete are all filtered out.
"""

import json
from pathlib import Path

import pytest

from agno.context import ContextMode
from agno.context.gdrive import GDriveContextProvider


@pytest.fixture
def fake_key_file(tmp_path: Path) -> Path:
    """Minimal service-account JSON that satisfies the existence check.

    NOTE: the JSON structure is not validated until the first Drive API
    call, so any non-empty file works for construction/status tests.
    """
    f = tmp_path / "sa.json"
    f.write_text(json.dumps({"type": "service_account", "client_email": "x@y.iam.gserviceaccount.com"}))
    return f


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_construction_with_path(fake_key_file: Path):
    p = GDriveContextProvider(service_account_path=str(fake_key_file))
    assert p.service_account_path == str(fake_key_file)
    assert p.id == "gdrive"
    assert p.name == "Google Drive"


def test_construction_reads_env(monkeypatch, fake_key_file: Path):
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(fake_key_file))
    p = GDriveContextProvider()
    assert p.service_account_path == str(fake_key_file)


def test_construction_without_path_raises(monkeypatch):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    with pytest.raises(ValueError, match="GOOGLE_SERVICE_ACCOUNT_FILE"):
        GDriveContextProvider()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_status_ok_when_file_exists(fake_key_file: Path):
    p = GDriveContextProvider(service_account_path=str(fake_key_file))
    s = p.status()
    assert s.ok is True
    assert s.detail == "gdrive"


def test_status_fails_when_file_missing(tmp_path: Path):
    missing = tmp_path / "nope.json"
    p = GDriveContextProvider(service_account_path=str(missing))
    s = p.status()
    assert s.ok is False
    assert "not found" in s.detail


@pytest.mark.asyncio
async def test_astatus_matches_status(fake_key_file: Path):
    p = GDriveContextProvider(service_account_path=str(fake_key_file))
    assert await p.astatus() == p.status()


# ---------------------------------------------------------------------------
# Tool exposure — write tools MUST NOT be present
# ---------------------------------------------------------------------------


def _tool_names(toolkit) -> list[str]:
    return list(toolkit.functions.keys())


def test_default_mode_exposes_readonly_drive_tools(fake_key_file: Path):
    p = GDriveContextProvider(service_account_path=str(fake_key_file), mode=ContextMode.default)
    tools = p.get_tools()
    assert len(tools) == 1
    names = _tool_names(tools[0])

    # Read tools must be enabled
    assert "list_files" in names
    assert "search_files" in names
    assert "read_file" in names


def test_default_mode_filters_write_tools(fake_key_file: Path):
    p = GDriveContextProvider(service_account_path=str(fake_key_file), mode=ContextMode.default)
    names = set(_tool_names(p.get_tools()[0]))

    # Known write / mutation tools exposed by GoogleDriveTools must NOT be present
    forbidden = {"upload_file", "download_file", "delete_file"}
    present = forbidden & names
    assert not present, f"Write tools leaked into GDrive provider: {present}"


def test_tools_mode_matches_default_mode(fake_key_file: Path):
    p_default = GDriveContextProvider(service_account_path=str(fake_key_file), mode=ContextMode.default)
    p_tools = GDriveContextProvider(service_account_path=str(fake_key_file), mode=ContextMode.tools)
    assert _tool_names(p_default.get_tools()[0]) == _tool_names(p_tools.get_tools()[0])


def test_agent_mode_returns_single_query_tool(fake_key_file: Path):
    p = GDriveContextProvider(service_account_path=str(fake_key_file), mode=ContextMode.agent)
    tools = p.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "query_gdrive"


def test_agent_mode_builds_agent(fake_key_file: Path):
    p = GDriveContextProvider(service_account_path=str(fake_key_file), mode=ContextMode.agent)
    agent = p._build_agent()
    assert agent.id == "gdrive"
