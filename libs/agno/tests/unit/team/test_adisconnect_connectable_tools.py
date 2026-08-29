"""Async connectable-tool disconnect must prefer ``aclose()`` when available.

``adisconnect_connectable_tools`` / ``_adisconnect_connectable_tools`` were
added so async run paths await async shutdown semantics instead of tearing
down through the synchronous ``close()`` path, which can lose work scheduled
on an event loop that is about to be destroyed.
"""

import pytest

from agno.agent._init import adisconnect_connectable_tools
from agno.team._init import _adisconnect_connectable_tools


class _AsyncTool:
    """A connectable tool with async shutdown semantics."""

    def __init__(self):
        self.aclose_called = False
        self.close_called = False

    async def aclose(self):
        self.aclose_called = True

    def close(self):
        self.close_called = True


class _SyncOnlyTool:
    """A connectable tool with only synchronous shutdown."""

    def __init__(self):
        self.close_called = False

    def close(self):
        self.close_called = True


@pytest.mark.asyncio
async def test_agent_async_tool_uses_aclose():
    tool = _AsyncTool()
    agent = MagicMock()
    agent._connectable_tools_initialized_on_run = [tool]

    await adisconnect_connectable_tools(agent)

    assert tool.aclose_called, "aclose-capable tool must be closed via aclose()"
    assert not tool.close_called, "must not fall back to close() when aclose() exists"


@pytest.mark.asyncio
async def test_agent_sync_only_tool_uses_close():
    tool = _SyncOnlyTool()
    agent = MagicMock()
    agent._connectable_tools_initialized_on_run = [tool]

    await adisconnect_connectable_tools(agent)

    assert tool.close_called, "sync-only tool must fall back to close()"


@pytest.mark.asyncio
async def test_agent_clears_initialized_tools():
    tool = _AsyncTool()
    agent = MagicMock()
    agent._connectable_tools_initialized_on_run = [tool]

    await adisconnect_connectable_tools(agent)

    assert agent._connectable_tools_initialized_on_run == []


@pytest.mark.asyncio
async def test_team_async_tool_uses_aclose():
    tool = _AsyncTool()
    team = MagicMock()
    team._connectable_tools_initialized_on_run = [tool]

    await _adisconnect_connectable_tools(team)

    assert tool.aclose_called
    assert not tool.close_called


@pytest.mark.asyncio
async def test_team_sync_only_tool_uses_close():
    tool = _SyncOnlyTool()
    team = MagicMock()
    team._connectable_tools_initialized_on_run = [tool]

    await _adisconnect_connectable_tools(team)

    assert tool.close_called


@pytest.mark.asyncio
async def test_team_clears_initialized_tools():
    tool = _AsyncTool()
    team = MagicMock()
    team._connectable_tools_initialized_on_run = [tool]

    await _adisconnect_connectable_tools(team)

    assert team._connectable_tools_initialized_on_run == []
