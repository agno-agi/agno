"""Tests for Agent callable factory support (tools, knowledge)."""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from agno.agent.agent import Agent
from agno.run.base import RunContext
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.callables import (
    aclear_callable_cache,
    ainvoke_callable_factory,
    aresolve_callable_tools,
    clear_callable_cache,
    get_resolved_knowledge,
    get_resolved_tools,
    invoke_callable_factory,
    is_callable_factory,
    resolve_callable_knowledge,
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


class _MockKnowledge:
    """A mock that satisfies KnowledgeProtocol."""

    def build_context(self, **kwargs) -> str:
        return "mock context"

    def get_tools(self, **kwargs):
        return []

    async def aget_tools(self, **kwargs):
        return []

    def retrieve(self, query: str, **kwargs):
        return []

    async def aretrieve(self, query: str, **kwargs):
        return []


def _dummy_tool(x: str) -> str:
    return f"result: {x}"


def _another_tool(x: str) -> str:
    return f"other: {x}"


# ---------------------------------------------------------------------------
# is_callable_factory
# ---------------------------------------------------------------------------


class TestIsCallableFactory:
    def test_regular_function_is_factory(self):
        def my_factory():
            return []

        assert is_callable_factory(my_factory) is True

    def test_lambda_is_factory(self):
        assert is_callable_factory(lambda: []) is True

    def test_toolkit_not_factory(self):
        tk = Toolkit(name="test")
        assert is_callable_factory(tk, excluded_types=(Toolkit, Function)) is False

    def test_class_not_factory(self):
        assert is_callable_factory(Toolkit) is False

    def test_none_not_factory(self):
        assert is_callable_factory(None) is False

    def test_string_not_factory(self):
        assert is_callable_factory("hello") is False

    def test_list_not_factory(self):
        assert is_callable_factory([_dummy_tool]) is False


# ---------------------------------------------------------------------------
# invoke_callable_factory
# ---------------------------------------------------------------------------


class TestInvokeCallableFactory:
    def test_no_args_factory(self):
        def factory():
            return [_dummy_tool]

        agent = Agent(name="test")
        rc = _make_run_context()
        result = invoke_callable_factory(factory, agent, rc)
        assert result == [_dummy_tool]

    def test_agent_injection(self):
        captured = {}

        def factory(agent):
            captured["agent"] = agent
            return [_dummy_tool]

        agent = Agent(name="injected")
        rc = _make_run_context()
        invoke_callable_factory(factory, agent, rc)
        assert captured["agent"] is agent

    def test_run_context_injection(self):
        captured = {}

        def factory(run_context):
            captured["run_context"] = run_context
            return [_dummy_tool]

        agent = Agent(name="test")
        rc = _make_run_context(user_id="u1")
        invoke_callable_factory(factory, agent, rc)
        assert captured["run_context"] is rc

    def test_session_state_injection(self):
        captured = {}

        def factory(session_state):
            captured["session_state"] = session_state
            return [_dummy_tool]

        agent = Agent(name="test")
        rc = _make_run_context(session_state={"key": "val"})
        invoke_callable_factory(factory, agent, rc)
        assert captured["session_state"] == {"key": "val"}

    def test_session_state_defaults_to_empty_dict(self):
        captured = {}

        def factory(session_state):
            captured["session_state"] = session_state
            return []

        agent = Agent(name="test")
        rc = _make_run_context(session_state=None)
        invoke_callable_factory(factory, agent, rc)
        assert captured["session_state"] == {}

    def test_multiple_params_injected(self):
        captured = {}

        def factory(agent, run_context, session_state):
            captured["agent"] = agent
            captured["run_context"] = run_context
            captured["session_state"] = session_state
            return [_dummy_tool]

        agent = Agent(name="multi")
        rc = _make_run_context(session_state={"k": "v"})
        invoke_callable_factory(factory, agent, rc)
        assert captured["agent"] is agent
        assert captured["run_context"] is rc
        assert captured["session_state"] == {"k": "v"}

    def test_async_factory_raises_in_sync(self):
        async def async_factory():
            return [_dummy_tool]

        agent = Agent(name="test")
        rc = _make_run_context()
        with pytest.raises(RuntimeError, match="cannot be used in sync mode"):
            invoke_callable_factory(async_factory, agent, rc)


# ---------------------------------------------------------------------------
# ainvoke_callable_factory
# ---------------------------------------------------------------------------


class TestAinvokeCallableFactory:
    @pytest.mark.asyncio
    async def test_sync_factory_works_in_async(self):
        def factory():
            return [_dummy_tool]

        agent = Agent(name="test")
        rc = _make_run_context()
        result = await ainvoke_callable_factory(factory, agent, rc)
        assert result == [_dummy_tool]

    @pytest.mark.asyncio
    async def test_async_factory_awaited(self):
        async def factory(agent):
            return [_dummy_tool]

        agent = Agent(name="test")
        rc = _make_run_context()
        result = await ainvoke_callable_factory(factory, agent, rc)
        assert result == [_dummy_tool]


# ---------------------------------------------------------------------------
# Agent callable tools storage
# ---------------------------------------------------------------------------


class TestAgentCallableToolsStorage:
    def test_callable_stored_as_factory(self):
        def tools_factory():
            return [_dummy_tool]

        agent = Agent(name="test", tools=tools_factory)
        assert callable(agent.tools)
        assert not isinstance(agent.tools, list)

    def test_list_stored_as_list(self):
        agent = Agent(name="test", tools=[_dummy_tool])
        assert isinstance(agent.tools, list)
        assert len(agent.tools) == 1

    def test_none_stored_as_empty_list(self):
        agent = Agent(name="test")
        assert agent.tools == []

    def test_toolkit_not_treated_as_factory(self):
        tk = Toolkit(name="test")
        agent = Agent(name="test", tools=[tk])
        assert isinstance(agent.tools, list)

    def test_cache_dicts_initialized(self):
        agent = Agent(name="test")
        assert hasattr(agent, "_callable_tools_cache")
        assert hasattr(agent, "_callable_knowledge_cache")
        assert isinstance(agent._callable_tools_cache, dict)
        assert isinstance(agent._callable_knowledge_cache, dict)


# ---------------------------------------------------------------------------
# Agent callable knowledge storage
# ---------------------------------------------------------------------------


class TestAgentCallableKnowledgeStorage:
    def test_callable_knowledge_stored_as_factory(self):
        def knowledge_factory():
            return MagicMock()

        agent = Agent(name="test", knowledge=knowledge_factory)
        assert callable(agent.knowledge)

    def test_knowledge_instance_stored_directly(self):
        mock_knowledge = MagicMock()
        # Make it satisfy KnowledgeProtocol (has build_context, get_tools, aget_tools)
        mock_knowledge.build_context = MagicMock()
        mock_knowledge.get_tools = MagicMock()
        mock_knowledge.aget_tools = MagicMock()
        agent = Agent(name="test", knowledge=mock_knowledge)
        assert agent.knowledge is mock_knowledge


# ---------------------------------------------------------------------------
# resolve_callable_tools
# ---------------------------------------------------------------------------


class TestResolveCallableTools:
    def test_static_tools_noop(self):
        agent = Agent(name="test", tools=[_dummy_tool])
        rc = _make_run_context()
        resolve_callable_tools(agent, rc)
        assert rc.tools is None  # Not set because tools is a static list

    def test_factory_resolved_and_stored_on_context(self):
        def factory():
            return [_dummy_tool, _another_tool]

        agent = Agent(name="test", tools=factory)
        rc = _make_run_context(user_id="user1")
        resolve_callable_tools(agent, rc)
        assert rc.tools == [_dummy_tool, _another_tool]

    def test_factory_none_result_becomes_empty_list(self):
        def factory():
            return None

        agent = Agent(name="test", tools=factory)
        rc = _make_run_context(user_id="user1")
        resolve_callable_tools(agent, rc)
        assert rc.tools == []

    def test_factory_invalid_return_raises(self):
        def factory():
            return "not a list"

        agent = Agent(name="test", tools=factory)
        rc = _make_run_context(user_id="user1")
        with pytest.raises(TypeError, match="must return a list or tuple"):
            resolve_callable_tools(agent, rc)

    def test_caching_by_user_id(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return [_dummy_tool]

        agent = Agent(name="test", tools=factory)

        rc1 = _make_run_context(user_id="user1")
        resolve_callable_tools(agent, rc1)
        assert call_count == 1

        rc2 = _make_run_context(user_id="user1")
        resolve_callable_tools(agent, rc2)
        assert call_count == 1  # Cached
        assert rc2.tools == [_dummy_tool]

    def test_different_cache_key_invokes_again(self):
        call_count = 0

        def factory(run_context):
            nonlocal call_count
            call_count += 1
            return [_dummy_tool] if run_context.user_id == "user1" else [_another_tool]

        agent = Agent(name="test", tools=factory)

        rc1 = _make_run_context(user_id="user1")
        resolve_callable_tools(agent, rc1)
        assert call_count == 1

        rc2 = _make_run_context(user_id="user2")
        resolve_callable_tools(agent, rc2)
        assert call_count == 2

    def test_cache_disabled_invokes_every_time(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return [_dummy_tool]

        agent = Agent(name="test", tools=factory, cache_callables=False)

        rc1 = _make_run_context(user_id="user1")
        resolve_callable_tools(agent, rc1)
        assert call_count == 1

        rc2 = _make_run_context(user_id="user1")
        resolve_callable_tools(agent, rc2)
        assert call_count == 2

    def test_no_cache_key_skips_caching(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return [_dummy_tool]

        agent = Agent(name="test", tools=factory)

        # No user_id, no session_id -> no cache key -> skip caching
        rc1 = _make_run_context(user_id=None, session_id=None)
        # session_id can't actually be None in RunContext dataclass, let's use a workaround
        rc1.session_id = None  # type: ignore[assignment]
        rc1.user_id = None
        resolve_callable_tools(agent, rc1)
        assert call_count == 1

        rc2 = _make_run_context(user_id=None, session_id=None)
        rc2.session_id = None  # type: ignore[assignment]
        rc2.user_id = None
        resolve_callable_tools(agent, rc2)
        assert call_count == 2  # Factory invoked again because no cache key

    def test_custom_cache_key_function(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return [_dummy_tool]

        def custom_key(run_context):
            return f"custom-{run_context.user_id}"

        agent = Agent(name="test", tools=factory, callable_tools_cache_key=custom_key)

        rc1 = _make_run_context(user_id="u1")
        resolve_callable_tools(agent, rc1)
        assert call_count == 1

        rc2 = _make_run_context(user_id="u1")
        resolve_callable_tools(agent, rc2)
        assert call_count == 1  # Cached under custom key

    def test_cache_key_falls_back_to_session_id(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return [_dummy_tool]

        agent = Agent(name="test", tools=factory)

        # No user_id but has session_id
        rc1 = _make_run_context(user_id=None, session_id="sess1")
        resolve_callable_tools(agent, rc1)
        assert call_count == 1

        rc2 = _make_run_context(user_id=None, session_id="sess1")
        resolve_callable_tools(agent, rc2)
        assert call_count == 1  # Cached by session_id


# ---------------------------------------------------------------------------
# aresolve_callable_tools (async)
# ---------------------------------------------------------------------------


class TestAresolveCallableTools:
    @pytest.mark.asyncio
    async def test_async_factory_resolved(self):
        async def factory(agent):
            return [_dummy_tool]

        agent = Agent(name="test", tools=factory)
        rc = _make_run_context(user_id="u1")
        await aresolve_callable_tools(agent, rc)
        assert rc.tools == [_dummy_tool]

    @pytest.mark.asyncio
    async def test_sync_factory_works_in_async(self):
        def factory():
            return [_dummy_tool]

        agent = Agent(name="test", tools=factory)
        rc = _make_run_context(user_id="u1")
        await aresolve_callable_tools(agent, rc)
        assert rc.tools == [_dummy_tool]


# ---------------------------------------------------------------------------
# resolve_callable_knowledge
# ---------------------------------------------------------------------------


class TestResolveCallableKnowledge:
    def _make_mock_knowledge(self):
        """Create a mock that satisfies KnowledgeProtocol."""
        mock = MagicMock()
        mock.build_context = MagicMock(return_value="context")
        mock.get_tools = MagicMock(return_value=[])
        mock.aget_tools = MagicMock(return_value=[])
        mock.retrieve = MagicMock(return_value=[])
        mock.aretrieve = MagicMock(return_value=[])
        return mock

    def test_static_knowledge_noop(self):
        mock_k = self._make_mock_knowledge()
        agent = Agent(name="test", knowledge=mock_k)
        rc = _make_run_context()
        resolve_callable_knowledge(agent, rc)
        assert rc.knowledge is None

    def test_factory_resolved(self):
        mock_k = self._make_mock_knowledge()

        def factory():
            return mock_k

        agent = Agent(name="test", knowledge=factory)
        rc = _make_run_context(user_id="u1")
        resolve_callable_knowledge(agent, rc)
        assert rc.knowledge is mock_k

    def test_factory_caching(self):
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            mock.build_context = MagicMock(return_value="context")
            mock.get_tools = MagicMock(return_value=[])
            mock.aget_tools = MagicMock(return_value=[])
            mock.retrieve = MagicMock(return_value=[])
            mock.aretrieve = MagicMock(return_value=[])
            return mock

        agent = Agent(name="test", knowledge=factory)

        rc1 = _make_run_context(user_id="u1")
        resolve_callable_knowledge(agent, rc1)
        assert call_count == 1

        rc2 = _make_run_context(user_id="u1")
        resolve_callable_knowledge(agent, rc2)
        assert call_count == 1  # Cached


# ---------------------------------------------------------------------------
# get_resolved_tools / get_resolved_knowledge
# ---------------------------------------------------------------------------


class TestGetResolvedHelpers:
    def test_get_resolved_tools_from_context(self):
        agent = Agent(name="test", tools=lambda: [_dummy_tool])
        rc = _make_run_context()
        rc.tools = [_dummy_tool]
        result = get_resolved_tools(agent, rc)
        assert result == [_dummy_tool]

    def test_get_resolved_tools_from_static(self):
        agent = Agent(name="test", tools=[_dummy_tool])
        rc = _make_run_context()
        result = get_resolved_tools(agent, rc)
        assert result == [_dummy_tool]

    def test_get_resolved_tools_factory_no_context(self):
        agent = Agent(name="test", tools=lambda: [_dummy_tool])
        rc = _make_run_context()
        result = get_resolved_tools(agent, rc)
        assert result is None  # Factory not resolved, no context.tools

    def test_get_resolved_knowledge_from_context(self):
        mock_k = MagicMock()
        agent = Agent(name="test")
        rc = _make_run_context()
        rc.knowledge = mock_k
        result = get_resolved_knowledge(agent, rc)
        assert result is mock_k

    def test_get_resolved_knowledge_static(self):
        mock_k = _MockKnowledge()
        agent = Agent(name="test", knowledge=mock_k)
        rc = _make_run_context()
        result = get_resolved_knowledge(agent, rc)
        assert result is mock_k


# ---------------------------------------------------------------------------
# clear_callable_cache
# ---------------------------------------------------------------------------


class TestClearCallableCache:
    def test_clear_all(self):
        agent = Agent(name="test")
        agent._callable_tools_cache["key"] = [_dummy_tool]
        agent._callable_knowledge_cache["key"] = MagicMock()

        clear_callable_cache(agent)
        assert len(agent._callable_tools_cache) == 0
        assert len(agent._callable_knowledge_cache) == 0

    def test_clear_tools_only(self):
        agent = Agent(name="test")
        agent._callable_tools_cache["key"] = [_dummy_tool]
        agent._callable_knowledge_cache["key"] = MagicMock()

        clear_callable_cache(agent, kind="tools")
        assert len(agent._callable_tools_cache) == 0
        assert len(agent._callable_knowledge_cache) == 1

    def test_clear_knowledge_only(self):
        agent = Agent(name="test")
        agent._callable_tools_cache["key"] = [_dummy_tool]
        agent._callable_knowledge_cache["key"] = MagicMock()

        clear_callable_cache(agent, kind="knowledge")
        assert len(agent._callable_tools_cache) == 1
        assert len(agent._callable_knowledge_cache) == 0

    def test_close_calls_close_on_cached_tools(self):
        tool_with_close = MagicMock()
        tool_with_close.close = MagicMock(return_value=None)

        agent = Agent(name="test")
        agent._callable_tools_cache["key"] = [tool_with_close]

        clear_callable_cache(agent, kind="tools", close=True)
        tool_with_close.close.assert_called_once()

    def test_close_deduplicates_by_identity(self):
        tool = MagicMock()
        tool.close = MagicMock(return_value=None)

        agent = Agent(name="test")
        # Same tool instance under two cache keys
        agent._callable_tools_cache["key1"] = [tool]
        agent._callable_tools_cache["key2"] = [tool]

        clear_callable_cache(agent, kind="tools", close=True)
        tool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_aclear_prefers_aclose(self):
        aclose_called = False

        async def mock_aclose():
            nonlocal aclose_called
            aclose_called = True

        tool = MagicMock()
        tool.aclose = mock_aclose

        agent = Agent(name="test")
        agent._callable_tools_cache["key"] = [tool]

        await aclear_callable_cache(agent, kind="tools", close=True)
        assert aclose_called


# ---------------------------------------------------------------------------
# Agent.add_tool guard
# ---------------------------------------------------------------------------


class TestAddToolGuard:
    def test_add_tool_raises_with_callable_factory(self):
        from agno.agent._init import add_tool

        agent = Agent(name="test", tools=lambda: [_dummy_tool])
        with pytest.raises(RuntimeError, match="Cannot add_tool.*when tools is a callable factory"):
            add_tool(agent, _another_tool)

    def test_add_tool_works_with_list(self):
        from agno.agent._init import add_tool

        agent = Agent(name="test", tools=[_dummy_tool])
        add_tool(agent, _another_tool)
        assert len(agent.tools) == 2  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Agent.set_tools
# ---------------------------------------------------------------------------


class TestSetTools:
    def test_set_tools_with_callable(self):
        from agno.agent._init import set_tools

        agent = Agent(name="test", tools=[_dummy_tool])

        def new_factory():
            return [_another_tool]

        set_tools(agent, new_factory)
        assert callable(agent.tools)

    def test_set_tools_clears_cache(self):
        from agno.agent._init import set_tools

        agent = Agent(name="test")
        agent._callable_tools_cache["old_key"] = [_dummy_tool]

        def new_factory():
            return [_another_tool]

        set_tools(agent, new_factory)
        assert len(agent._callable_tools_cache) == 0

    def test_set_tools_with_list(self):
        from agno.agent._init import set_tools

        agent = Agent(name="test")
        set_tools(agent, [_dummy_tool, _another_tool])
        assert isinstance(agent.tools, list)
        assert len(agent.tools) == 2


# ---------------------------------------------------------------------------
# Agent config fields
# ---------------------------------------------------------------------------


class TestAgentConfigFields:
    def test_cache_callables_default_true(self):
        agent = Agent(name="test")
        assert agent.cache_callables is True

    def test_cache_callables_configurable(self):
        agent = Agent(name="test", cache_callables=False)
        assert agent.cache_callables is False

    def test_callable_cache_key_functions(self):
        def my_key(run_context):
            return "custom"

        agent = Agent(
            name="test",
            callable_tools_cache_key=my_key,
            callable_knowledge_cache_key=my_key,
        )
        assert agent.callable_tools_cache_key is my_key
        assert agent.callable_knowledge_cache_key is my_key


# ---------------------------------------------------------------------------
# Agent deep_copy with callable tools
# ---------------------------------------------------------------------------


class TestAgentDeepCopyCallable:
    def test_deep_copy_preserves_callable_factory(self):
        def factory():
            return [_dummy_tool]

        agent = Agent(name="test", tools=factory)
        copied = agent.deep_copy()
        # The factory should be shared by reference (not deep-copied)
        assert copied.tools is agent.tools
