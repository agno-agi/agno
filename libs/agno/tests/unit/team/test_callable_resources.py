"""Tests for Team callable factory support (tools, knowledge, members)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from agno.agent.agent import Agent
from agno.run.base import RunContext
from agno.utils.callables import (
    aresolve_callable_members,
    clear_callable_cache,
    get_resolved_members,
    resolve_callable_members,
    resolve_callable_tools,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_run_context(
    user_id: Optional[str] = None,
    session_id: str = "test-session",
    session_state: Optional[Dict[str, Any]] = None,
) -> RunContext:
    return RunContext(
        run_id="test-run",
        session_id=session_id,
        user_id=user_id,
        session_state=session_state,
    )


def _dummy_tool(x: str) -> str:
    return f"result: {x}"


def _another_tool(x: str) -> str:
    return f"other: {x}"


def _make_team(**kwargs):
    """Create a Team with minimal config."""
    from agno.team.team import Team

    defaults = {
        "name": "test-team",
        "mode": "coordinate",
    }
    defaults.update(kwargs)

    # Members must be provided (list or callable)
    if "members" not in defaults:
        defaults["members"] = [Agent(name="member-1")]

    return Team(**defaults)


# ---------------------------------------------------------------------------
# Team callable tools
# ---------------------------------------------------------------------------


class TestTeamCallableTools:
    def test_callable_tools_stored_as_factory(self):
        def tools_factory():
            return [_dummy_tool]

        team = _make_team(tools=tools_factory)
        assert callable(team.tools)
        assert not isinstance(team.tools, list)

    def test_list_tools_stored_as_list(self):
        team = _make_team(tools=[_dummy_tool])
        assert isinstance(team.tools, list)

    def test_resolve_callable_tools(self):
        def factory(team):
            return [_dummy_tool]

        team = _make_team(tools=factory)
        rc = _make_run_context(user_id="u1")
        resolve_callable_tools(team, rc)
        assert rc.tools == [_dummy_tool]

    def test_tools_caching(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return [_dummy_tool]

        team = _make_team(tools=factory)

        rc1 = _make_run_context(user_id="u1")
        resolve_callable_tools(team, rc1)
        assert call_count == 1

        rc2 = _make_run_context(user_id="u1")
        resolve_callable_tools(team, rc2)
        assert call_count == 1  # Cached

    def test_cache_disabled(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return [_dummy_tool]

        team = _make_team(tools=factory, cache_callables=False)

        rc1 = _make_run_context(user_id="u1")
        resolve_callable_tools(team, rc1)

        rc2 = _make_run_context(user_id="u1")
        resolve_callable_tools(team, rc2)
        assert call_count == 2


# ---------------------------------------------------------------------------
# Team callable members
# ---------------------------------------------------------------------------


class TestTeamCallableMembers:
    def test_callable_members_stored_as_factory(self):
        def members_factory():
            return [Agent(name="dynamic-agent")]

        team = _make_team(members=members_factory)
        assert callable(team.members)
        assert not isinstance(team.members, list)

    def test_list_members_stored_as_list(self):
        agents = [Agent(name="a1"), Agent(name="a2")]
        team = _make_team(members=agents)
        assert isinstance(team.members, list)
        assert len(team.members) == 2

    def test_resolve_callable_members(self):
        agent_a = Agent(name="agent-a")
        agent_b = Agent(name="agent-b")

        def factory(team):
            return [agent_a, agent_b]

        team = _make_team(members=factory)
        rc = _make_run_context(user_id="u1")
        resolve_callable_members(team, rc)
        assert rc.members == [agent_a, agent_b]

    def test_members_caching(self):
        call_count = 0
        agent_a = Agent(name="agent-a")

        def factory():
            nonlocal call_count
            call_count += 1
            return [agent_a]

        team = _make_team(members=factory)

        rc1 = _make_run_context(user_id="u1")
        resolve_callable_members(team, rc1)
        assert call_count == 1

        rc2 = _make_run_context(user_id="u1")
        resolve_callable_members(team, rc2)
        assert call_count == 1  # Cached

    def test_members_different_keys(self):
        call_count = 0

        def factory(run_context):
            nonlocal call_count
            call_count += 1
            return [Agent(name=f"agent-{run_context.user_id}")]

        team = _make_team(members=factory)

        rc1 = _make_run_context(user_id="u1")
        resolve_callable_members(team, rc1)

        rc2 = _make_run_context(user_id="u2")
        resolve_callable_members(team, rc2)
        assert call_count == 2

    def test_members_none_result_becomes_empty_list(self):
        def factory():
            return None

        team = _make_team(members=factory)
        rc = _make_run_context(user_id="u1")
        resolve_callable_members(team, rc)
        assert rc.members == []

    def test_members_invalid_return_raises(self):
        def factory():
            return "not a list"

        team = _make_team(members=factory)
        rc = _make_run_context(user_id="u1")
        with pytest.raises(TypeError, match="must return a list or tuple"):
            resolve_callable_members(team, rc)

    def test_custom_members_cache_key(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return [Agent(name="a")]

        def custom_key(run_context):
            return f"tenant-{run_context.user_id}"

        team = _make_team(
            members=factory,
            callable_members_cache_key=custom_key,
        )

        rc1 = _make_run_context(user_id="u1")
        resolve_callable_members(team, rc1)
        assert call_count == 1

        rc2 = _make_run_context(user_id="u1")
        resolve_callable_members(team, rc2)
        assert call_count == 1


# ---------------------------------------------------------------------------
# Async team members
# ---------------------------------------------------------------------------


class TestAsyncTeamMembers:
    @pytest.mark.asyncio
    async def test_async_members_factory(self):
        agent_a = Agent(name="async-a")

        async def factory(team):
            return [agent_a]

        team = _make_team(members=factory)
        rc = _make_run_context(user_id="u1")
        await aresolve_callable_members(team, rc)
        assert rc.members == [agent_a]

    @pytest.mark.asyncio
    async def test_sync_members_factory_in_async(self):
        agent_a = Agent(name="sync-a")

        def factory():
            return [agent_a]

        team = _make_team(members=factory)
        rc = _make_run_context(user_id="u1")
        await aresolve_callable_members(team, rc)
        assert rc.members == [agent_a]


# ---------------------------------------------------------------------------
# Team cache clearing
# ---------------------------------------------------------------------------


class TestTeamClearCache:
    def test_clear_all(self):
        team = _make_team()
        team._callable_tools_cache["key"] = [_dummy_tool]
        team._callable_members_cache["key"] = [Agent(name="a")]

        clear_callable_cache(team)
        assert len(team._callable_tools_cache) == 0
        assert len(team._callable_members_cache) == 0

    def test_clear_members_only(self):
        team = _make_team()
        team._callable_tools_cache["key"] = [_dummy_tool]
        team._callable_members_cache["key"] = [Agent(name="a")]

        clear_callable_cache(team, kind="members")
        assert len(team._callable_tools_cache) == 1
        assert len(team._callable_members_cache) == 0


# ---------------------------------------------------------------------------
# Team config fields
# ---------------------------------------------------------------------------


class TestTeamConfigFields:
    def test_cache_callables_default_true(self):
        team = _make_team()
        assert team.cache_callables is True

    def test_cache_callables_configurable(self):
        team = _make_team(cache_callables=False)
        assert team.cache_callables is False

    def test_callable_cache_key_functions(self):
        def my_key(run_context):
            return "custom"

        team = _make_team(
            callable_tools_cache_key=my_key,
            callable_members_cache_key=my_key,
        )
        assert team.callable_tools_cache_key is my_key
        assert team.callable_members_cache_key is my_key


# ---------------------------------------------------------------------------
# Team add_tool guard
# ---------------------------------------------------------------------------


class TestTeamAddToolGuard:
    def test_add_tool_raises_with_callable_factory(self):
        from agno.team._init import add_tool

        team = _make_team(tools=lambda: [_dummy_tool])
        with pytest.raises(RuntimeError, match="Cannot add_tool when tools is a callable factory"):
            add_tool(team, _another_tool)


# ---------------------------------------------------------------------------
# Team set_tools
# ---------------------------------------------------------------------------


class TestTeamSetTools:
    def test_set_tools_with_callable(self):
        from agno.team._init import set_tools

        team = _make_team(tools=[_dummy_tool])

        def new_factory():
            return [_another_tool]

        set_tools(team, new_factory)
        assert callable(team.tools)

    def test_set_tools_clears_cache(self):
        from agno.team._init import set_tools

        team = _make_team()
        team._callable_tools_cache["old"] = [_dummy_tool]

        set_tools(team, lambda: [_another_tool])
        assert len(team._callable_tools_cache) == 0


# ---------------------------------------------------------------------------
# get_resolved_members
# ---------------------------------------------------------------------------


class TestGetResolvedMembers:
    def test_from_context(self):
        agents = [Agent(name="a")]
        team = _make_team(members=lambda: agents)
        rc = _make_run_context()
        rc.members = agents
        result = get_resolved_members(team, rc)
        assert result == agents

    def test_from_static(self):
        agents = [Agent(name="a")]
        team = _make_team(members=agents)
        rc = _make_run_context()
        result = get_resolved_members(team, rc)
        assert result == agents

    def test_callable_not_resolved(self):
        team = _make_team(members=lambda: [Agent(name="a")])
        rc = _make_run_context()
        result = get_resolved_members(team, rc)
        assert result is None
