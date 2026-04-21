"""Unit tests for GitHubContextProvider.

GitHub is the canonical reference for write-tool filtering — scout has
verified 21 read tools and 0 writes. These tests lock that invariant
in place.
"""

import pytest

from agno.context import ContextMode
from agno.context.github import READ_ONLY_TOOLS, GitHubContextProvider

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_construction_with_token():
    p = GitHubContextProvider(access_token="ghp_fake")
    assert p.access_token == "ghp_fake"
    assert p.id == "github"
    assert p.name == "GitHub"


def test_construction_reads_env(monkeypatch):
    monkeypatch.setenv("GITHUB_ACCESS_TOKEN", "ghp_from_env")
    p = GitHubContextProvider()
    assert p.access_token == "ghp_from_env"


def test_construction_without_token_raises(monkeypatch):
    monkeypatch.delenv("GITHUB_ACCESS_TOKEN", raising=False)
    with pytest.raises(ValueError, match="GITHUB_ACCESS_TOKEN"):
        GitHubContextProvider()


def test_construction_with_enterprise_base_url():
    p = GitHubContextProvider(access_token="ghp_fake", base_url="https://ghe.example.com")
    assert p.base_url == "https://ghe.example.com"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_status_ok_when_token_set():
    p = GitHubContextProvider(access_token="ghp_fake")
    s = p.status()
    assert s.ok is True
    assert "github.com" in s.detail


def test_status_detail_includes_enterprise_host():
    p = GitHubContextProvider(access_token="ghp_fake", base_url="https://ghe.example.com")
    assert "ghe.example.com" in p.status().detail


@pytest.mark.asyncio
async def test_astatus_matches_status():
    p = GitHubContextProvider(access_token="ghp_fake")
    assert await p.astatus() == p.status()


# ---------------------------------------------------------------------------
# Tool exposure — READ_ONLY_TOOLS is the canonical filter
# ---------------------------------------------------------------------------


def _tool_names(toolkit) -> list[str]:
    return list(toolkit.functions.keys())


def test_read_only_tools_has_21_entries():
    assert len(READ_ONLY_TOOLS) == 21
    assert len(set(READ_ONLY_TOOLS)) == len(READ_ONLY_TOOLS)


def test_default_mode_exposes_21_read_tools():
    p = GitHubContextProvider(access_token="ghp_fake", mode=ContextMode.default)
    tools = p.get_tools()
    assert len(tools) == 1
    names = _tool_names(tools[0])
    assert len(names) == 21
    assert set(names) == set(READ_ONLY_TOOLS)


def test_default_mode_filters_write_tools():
    p = GitHubContextProvider(access_token="ghp_fake", mode=ContextMode.default)
    names = set(_tool_names(p.get_tools()[0]))

    # Well-known write / mutation tools from GithubTools must NOT be present.
    forbidden = {
        "create_issue",
        "close_issue",
        "reopen_issue",
        "comment_on_issue",
        "assign_issue",
        "label_issue",
        "edit_issue",
        "create_pull_request",
        "create_pull_request_comment",
        "edit_pull_request_comment",
        "create_repository",
        "delete_repository",
        "create_branch",
        "set_default_branch",
        "create_file",
        "update_file",
        "delete_file",
        "create_review_request",
    }
    present = forbidden & names
    assert not present, f"Write tools leaked into GitHub provider: {present}"


def test_tools_mode_matches_default_mode():
    p_default = GitHubContextProvider(access_token="ghp_fake", mode=ContextMode.default)
    p_tools = GitHubContextProvider(access_token="ghp_fake", mode=ContextMode.tools)
    assert _tool_names(p_default.get_tools()[0]) == _tool_names(p_tools.get_tools()[0])


def test_agent_mode_returns_single_query_tool():
    p = GitHubContextProvider(access_token="ghp_fake", mode=ContextMode.agent)
    tools = p.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "query_github"


def test_agent_mode_builds_agent():
    p = GitHubContextProvider(access_token="ghp_fake", mode=ContextMode.agent)
    agent = p._build_agent()
    assert agent.id == "github"
