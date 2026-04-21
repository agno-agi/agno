"""Unit tests for SlackContextProvider.

Verifies write-tool filtering with the same rigor as GitHub — the brief
flagged that scout has not re-verified Slack's filter as carefully as
GitHub's.
"""

import pytest

from agno.context import ContextMode
from agno.context.slack import SlackContextProvider

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_construction_with_token():
    p = SlackContextProvider(token="xoxb-fake")
    assert p.token == "xoxb-fake"
    assert p.id == "slack"
    assert p.name == "Slack"


def test_construction_reads_bot_token_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-from-env")
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    p = SlackContextProvider()
    assert p.token == "xoxb-from-env"


def test_construction_falls_back_to_slack_token(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_TOKEN", "xoxb-fallback")
    p = SlackContextProvider()
    assert p.token == "xoxb-fallback"


def test_construction_without_token_raises(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    with pytest.raises(ValueError, match="SLACK_BOT_TOKEN"):
        SlackContextProvider()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_status_ok_when_token_set():
    p = SlackContextProvider(token="xoxb-fake")
    s = p.status()
    assert s.ok is True
    assert "slack" in s.detail.lower()


@pytest.mark.asyncio
async def test_astatus_matches_status():
    p = SlackContextProvider(token="xoxb-fake")
    assert await p.astatus() == p.status()


# ---------------------------------------------------------------------------
# Tool exposure — write tools MUST NOT be present
# ---------------------------------------------------------------------------


def _tool_names(toolkit) -> list[str]:
    return list(toolkit.functions.keys())


def test_default_mode_exposes_readonly_slack_tools():
    p = SlackContextProvider(token="xoxb-fake", mode=ContextMode.default)
    tools = p.get_tools()
    assert len(tools) == 1
    names = _tool_names(tools[0])

    # Read tools must be enabled
    assert "list_channels" in names
    assert "get_channel_history" in names
    assert "search_workspace" in names
    assert "get_thread" in names
    assert "list_users" in names
    assert "get_user_info" in names
    assert "get_channel_info" in names


def test_default_mode_filters_write_tools():
    p = SlackContextProvider(token="xoxb-fake", mode=ContextMode.default)
    names = _tool_names(p.get_tools()[0])

    # Known write / mutation tools must NOT be present
    forbidden = {
        "send_message",
        "send_message_thread",
        "upload_file",
        "download_file",
    }
    present = forbidden & set(names)
    assert not present, f"Write tools leaked into Slack provider: {present}"


def test_tools_mode_matches_default_mode():
    p_default = SlackContextProvider(token="xoxb-fake", mode=ContextMode.default)
    p_tools = SlackContextProvider(token="xoxb-fake", mode=ContextMode.tools)
    assert _tool_names(p_default.get_tools()[0]) == _tool_names(p_tools.get_tools()[0])


def test_agent_mode_returns_single_query_tool():
    p = SlackContextProvider(token="xoxb-fake", mode=ContextMode.agent)
    tools = p.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "query_slack"


def test_agent_mode_builds_agent():
    p = SlackContextProvider(token="xoxb-fake", mode=ContextMode.agent)
    agent = p._build_agent()
    assert agent.id == "slack"
