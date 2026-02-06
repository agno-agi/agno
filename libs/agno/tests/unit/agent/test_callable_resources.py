from unittest.mock import patch
from uuid import uuid4

import pytest

from agno.agent.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.session import AgentSession


class DummyKnowledge:
    def __init__(self):
        self.get_tools_calls = 0

    def build_context(self, **kwargs) -> str:
        return "dummy-context"

    def get_tools(self, **kwargs):
        self.get_tools_calls += 1
        return []

    async def aget_tools(self, **kwargs):
        self.get_tools_calls += 1
        return []

    def retrieve(self, query: str, **kwargs):
        return []

    async def aretrieve(self, query: str, **kwargs):
        return []


def test_callable_resource_cache_uses_user_id_then_session_id():
    tool_factory_calls = 0
    knowledge_factory_calls = 0

    def static_tool() -> str:
        return "ok"

    def tools_factory(**kwargs):
        nonlocal tool_factory_calls
        tool_factory_calls += 1
        return [static_tool]

    def knowledge_factory(**kwargs):
        nonlocal knowledge_factory_calls
        knowledge_factory_calls += 1
        return DummyKnowledge()

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=tools_factory,
        knowledge=knowledge_factory,
        cache_callables=True,
    )

    # Same user_id should reuse cache even with different session_id.
    ctx_user_1 = RunContext(run_id=str(uuid4()), session_id="session-1", user_id="user-1")
    agent._resolve_runtime_resources(ctx_user_1)
    ctx_user_2 = RunContext(run_id=str(uuid4()), session_id="session-2", user_id="user-1")
    agent._resolve_runtime_resources(ctx_user_2)

    assert tool_factory_calls == 1
    assert knowledge_factory_calls == 1
    assert ctx_user_1.tools is ctx_user_2.tools
    assert ctx_user_1.knowledge is ctx_user_2.knowledge

    # No user_id: fallback to session_id.
    ctx_session_1 = RunContext(run_id=str(uuid4()), session_id="session-3", user_id=None)
    agent._resolve_runtime_resources(ctx_session_1)
    ctx_session_2 = RunContext(run_id=str(uuid4()), session_id="session-3", user_id=None)
    agent._resolve_runtime_resources(ctx_session_2)

    assert tool_factory_calls == 2
    assert knowledge_factory_calls == 2
    assert ctx_session_1.tools is ctx_session_2.tools
    assert ctx_session_1.knowledge is ctx_session_2.knowledge


def test_callable_resource_cache_can_be_disabled():
    tool_factory_calls = 0
    knowledge_factory_calls = 0

    def static_tool() -> str:
        return "ok"

    def tools_factory(**kwargs):
        nonlocal tool_factory_calls
        tool_factory_calls += 1
        return [static_tool]

    def knowledge_factory(**kwargs):
        nonlocal knowledge_factory_calls
        knowledge_factory_calls += 1
        return DummyKnowledge()

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=tools_factory,
        knowledge=knowledge_factory,
        cache_callables=False,
    )

    ctx1 = RunContext(run_id=str(uuid4()), session_id="session-1", user_id="user-1")
    ctx2 = RunContext(run_id=str(uuid4()), session_id="session-2", user_id="user-1")
    agent._resolve_runtime_resources(ctx1)
    agent._resolve_runtime_resources(ctx2)

    assert tool_factory_calls == 2
    assert knowledge_factory_calls == 2


def test_set_tools_accepts_callable_factory_and_replaces_cached_factory_result():
    old_factory_calls = 0
    new_factory_calls = 0

    def old_tool() -> str:
        return "old"

    def new_tool() -> str:
        return "new"

    def old_factory(**kwargs):
        nonlocal old_factory_calls
        old_factory_calls += 1
        return [old_tool]

    def new_factory(**kwargs):
        nonlocal new_factory_calls
        new_factory_calls += 1
        return [new_tool]

    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), tools=old_factory, cache_callables=True)

    # Seed cache for user-1 using old factory.
    ctx_old = RunContext(run_id=str(uuid4()), session_id="session-1", user_id="user-1")
    agent._resolve_runtime_resources(ctx_old)
    assert old_factory_calls == 1
    assert new_factory_calls == 0
    assert callable(agent.tools)

    # Replace callable factory and ensure stale cache is not reused.
    agent.set_tools(new_factory)
    assert callable(agent.tools)
    ctx_new = RunContext(run_id=str(uuid4()), session_id="session-2", user_id="user-1")
    agent._resolve_runtime_resources(ctx_new)

    assert old_factory_calls == 1
    assert new_factory_calls == 1
    assert ctx_new.tools == [new_tool]


def test_callable_resource_cache_keys_can_be_overridden_per_kind():
    tool_factory_calls = 0
    knowledge_factory_calls = 0

    def static_tool() -> str:
        return "ok"

    def tools_factory(**kwargs):
        nonlocal tool_factory_calls
        tool_factory_calls += 1
        return [static_tool]

    def knowledge_factory(**kwargs):
        nonlocal knowledge_factory_calls
        knowledge_factory_calls += 1
        return DummyKnowledge()

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=tools_factory,
        knowledge=knowledge_factory,
        callable_tools_cache_key=lambda run_context: "shared-tools-key",
        callable_knowledge_cache_key=lambda run_context: f"knowledge:{run_context.session_id}",
    )

    ctx1 = RunContext(run_id=str(uuid4()), session_id="session-1", user_id="user-1")
    ctx2 = RunContext(run_id=str(uuid4()), session_id="session-2", user_id="user-1")
    agent._resolve_runtime_resources(ctx1)
    agent._resolve_runtime_resources(ctx2)

    # Tools share a single key; knowledge key varies by session_id.
    assert tool_factory_calls == 1
    assert knowledge_factory_calls == 2


def test_sync_resolver_rejects_async_factories():
    async def async_tools_factory(**kwargs):
        return []

    async def async_knowledge_factory(**kwargs):
        return DummyKnowledge()

    agent_tools = Agent(model=OpenAIChat(id="gpt-4o-mini"), tools=async_tools_factory)
    run_context_tools = RunContext(run_id=str(uuid4()), session_id="session-1", user_id="user-1")
    with pytest.raises(RuntimeError, match="Async tools factory"):
        agent_tools._resolve_runtime_resources(run_context_tools)

    agent_knowledge = Agent(model=OpenAIChat(id="gpt-4o-mini"), knowledge=async_knowledge_factory)
    run_context_knowledge = RunContext(run_id=str(uuid4()), session_id="session-1", user_id="user-1")
    with pytest.raises(RuntimeError, match="Async knowledge factory"):
        agent_knowledge._resolve_runtime_resources(run_context_knowledge)


@pytest.mark.asyncio
async def test_async_resolver_supports_sync_and_async_factories():
    def sync_tool() -> str:
        return "sync-tool"

    async def async_tools_factory(**kwargs):
        return [sync_tool]

    async def async_knowledge_factory(**kwargs):
        return DummyKnowledge()

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=async_tools_factory,
        knowledge=async_knowledge_factory,
    )
    run_context = RunContext(run_id=str(uuid4()), session_id="session-1", user_id="user-1")

    await agent._aresolve_runtime_resources(run_context)

    assert run_context.tools == [sync_tool]
    assert isinstance(run_context.knowledge, DummyKnowledge)


def test_clear_callable_cache_dedupes_tools_before_close():
    class CloseTrackingTool:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    tracked_tool = CloseTrackingTool()

    def tools_factory(**kwargs):
        return [tracked_tool, tracked_tool]

    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), tools=tools_factory)
    run_context = RunContext(run_id=str(uuid4()), session_id="session-1", user_id="user-1")
    agent._resolve_runtime_resources(run_context)

    agent.clear_callable_cache(user_id="user-1", kind="tools", close=True)

    assert tracked_tool.close_calls == 1
    assert agent._callable_tools_cache == {}


def test_sync_clear_callable_cache_warns_when_close_returns_awaitable():
    class AwaitableResult:
        def __await__(self):
            if False:
                yield
            return None

    class AwaitableCloseTool:
        def close(self):
            return AwaitableResult()

    awaitable_tool = AwaitableCloseTool()

    def tools_factory(**kwargs):
        return [awaitable_tool]

    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), tools=tools_factory)
    run_context = RunContext(run_id=str(uuid4()), session_id="session-1", user_id="user-1")
    agent._resolve_runtime_resources(run_context)

    with patch("agno.agent.trait.tools.log_warning") as warning_mock:
        agent.clear_callable_cache(user_id="user-1", kind="tools", close=True)

    assert warning_mock.call_count >= 1
    assert any("awaitable" in str(call.args[0]) for call in warning_mock.call_args_list)


@pytest.mark.asyncio
async def test_async_clear_callable_cache_prefers_aclose():
    class AsyncCloseKnowledge(DummyKnowledge):
        def __init__(self):
            super().__init__()
            self.aclose_calls = 0
            self.close_calls = 0

        async def aclose(self):
            self.aclose_calls += 1

        def close(self):
            self.close_calls += 1

    tracked_knowledge = AsyncCloseKnowledge()

    def knowledge_factory(**kwargs):
        return tracked_knowledge

    agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), knowledge=knowledge_factory)
    run_context = RunContext(run_id=str(uuid4()), session_id="session-1", user_id="user-1")
    await agent._aresolve_runtime_resources(run_context)

    await agent.aclear_callable_cache(user_id="user-1", kind="knowledge", close=True)

    assert tracked_knowledge.aclose_calls == 1
    assert tracked_knowledge.close_calls == 0
    assert agent._callable_knowledge_cache == {}


def test_get_tools_uses_run_context_resolved_resources():
    tools_factory_calls = 0
    knowledge_factory_calls = 0

    def runtime_tool() -> str:
        return "runtime-tool"

    def tools_factory(**kwargs):
        nonlocal tools_factory_calls
        tools_factory_calls += 1
        return []

    def knowledge_factory(**kwargs):
        nonlocal knowledge_factory_calls
        knowledge_factory_calls += 1
        return DummyKnowledge()

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=tools_factory,
        knowledge=knowledge_factory,
    )
    run_context = RunContext(
        run_id=str(uuid4()),
        session_id="session-1",
        user_id="user-1",
        tools=[runtime_tool],
        knowledge=DummyKnowledge(),
    )
    run_response = RunOutput(run_id=str(uuid4()), session_id="session-1", messages=[])
    session = AgentSession(session_id="session-1")

    resolved_tools = agent.get_tools(
        run_response=run_response,
        run_context=run_context,
        session=session,
        user_id="user-1",
    )

    assert runtime_tool in resolved_tools
    assert tools_factory_calls == 0
    assert knowledge_factory_calls == 0


def test_to_dict_does_not_serialize_callable_tools_factory():
    def tools_factory(**kwargs):
        return []

    agent = Agent(
        id="callable-tools-agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=tools_factory,
        cache_callables=False,
    )
    config = agent.to_dict()
    reconstructed = Agent.from_dict(config)

    assert "tools" not in config
    assert config["cache_callables"] is False
    assert reconstructed.cache_callables is False
