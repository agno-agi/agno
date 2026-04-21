"""Unit tests for FilesystemContextProvider."""

from pathlib import Path

import pytest

from agno.context import ContextMode
from agno.context.fs import FilesystemContextProvider

# ---------------------------------------------------------------------------
# Construction + status
# ---------------------------------------------------------------------------


def test_construction_resolves_root(tmp_path: Path):
    p = FilesystemContextProvider(root=tmp_path)
    assert p.root == tmp_path.resolve()
    assert p.id == "fs"
    assert p.name == "Filesystem"


def test_status_ok_for_existing_dir(tmp_path: Path):
    p = FilesystemContextProvider(root=tmp_path)
    s = p.status()
    assert s.ok is True
    assert str(tmp_path) in s.detail


def test_status_fails_when_root_missing(tmp_path: Path):
    missing = tmp_path / "does-not-exist"
    p = FilesystemContextProvider(root=missing)
    s = p.status()
    assert s.ok is False
    assert "does not exist" in s.detail


def test_status_fails_when_root_is_file(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("hi")
    p = FilesystemContextProvider(root=f)
    s = p.status()
    assert s.ok is False
    assert "not a directory" in s.detail


@pytest.mark.asyncio
async def test_astatus_matches_status(tmp_path: Path):
    p = FilesystemContextProvider(root=tmp_path)
    s_sync = p.status()
    s_async = await p.astatus()
    assert s_sync == s_async


# ---------------------------------------------------------------------------
# Tool exposure per mode
# ---------------------------------------------------------------------------


def _tool_names(toolkit) -> list[str]:
    return list(toolkit.functions.keys())


def test_default_mode_exposes_readonly_file_tools(tmp_path: Path):
    p = FilesystemContextProvider(root=tmp_path, mode=ContextMode.default)
    tools = p.get_tools()
    assert len(tools) == 1
    names = _tool_names(tools[0])
    # Read tools should be enabled
    assert "list_files" in names
    assert "search_files" in names
    assert "search_content" in names
    assert "read_file" in names
    assert "read_file_chunk" in names
    # Write tools should be disabled
    assert "save_file" not in names
    assert "delete_file" not in names
    assert "replace_file_chunk" not in names


def test_tools_mode_equals_default_mode(tmp_path: Path):
    p_default = FilesystemContextProvider(root=tmp_path, mode=ContextMode.default)
    p_tools = FilesystemContextProvider(root=tmp_path, mode=ContextMode.tools)
    assert _tool_names(p_default.get_tools()[0]) == _tool_names(p_tools.get_tools()[0])


def test_agent_mode_returns_single_query_tool(tmp_path: Path):
    p = FilesystemContextProvider(root=tmp_path, mode=ContextMode.agent)
    tools = p.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "query_fs"


def test_agent_mode_builds_agent(tmp_path: Path):
    p = FilesystemContextProvider(root=tmp_path, mode=ContextMode.agent)
    agent = p._build_agent()
    assert agent.id == "fs"
    assert agent.name == "Filesystem"
