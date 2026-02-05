import asyncio

import pytest

from agno.agent.agent import Agent
from agno.run import RunContext


def test_callable_tools_cached_by_user_id():
    calls = {"count": 0}
    tool_instance = object()

    def get_tools(run_context: RunContext):
        calls["count"] += 1
        return [tool_instance]

    agent = Agent(tools=get_tools, cache_callables=True)

    ctx1 = RunContext(run_id="r1", session_id="s1", user_id="alice")
    agent._resolve_callables(run_context=ctx1, session_state={})
    assert ctx1.tools == [tool_instance]

    ctx2 = RunContext(run_id="r2", session_id="s2", user_id="alice")
    agent._resolve_callables(run_context=ctx2, session_state={})
    assert ctx2.tools == [tool_instance]

    # Cached by user_id, so factory runs once and tools list is reused.
    assert calls["count"] == 1
    assert ctx1.tools is ctx2.tools


def test_callable_tools_cached_by_session_id_when_user_id_missing():
    calls = {"count": 0}

    def get_tools(run_context: RunContext):
        calls["count"] += 1
        return [object()]

    agent = Agent(tools=get_tools, cache_callables=True)

    ctx1 = RunContext(run_id="r1", session_id="session-1", user_id=None)
    agent._resolve_callables(run_context=ctx1, session_state={})

    ctx2 = RunContext(run_id="r2", session_id="session-2", user_id=None)
    agent._resolve_callables(run_context=ctx2, session_state={})

    # Different session_id => different cache key => factory runs twice.
    assert calls["count"] == 2
    assert ctx1.tools is not ctx2.tools


def test_callable_cache_key_overrides_default():
    calls = {"count": 0}

    def get_tools(run_context: RunContext):
        calls["count"] += 1
        return [object()]

    agent = Agent(
        tools=get_tools,
        cache_callables=True,
        callable_cache_key=lambda ctx: str((ctx.dependencies or {}).get("tenant_id")),
    )

    ctx_a = RunContext(run_id="r1", session_id="s1", user_id="alice", dependencies={"tenant_id": "acme"})
    agent._resolve_callables(run_context=ctx_a, session_state={})

    ctx_b = RunContext(run_id="r2", session_id="s2", user_id="alice", dependencies={"tenant_id": "globex"})
    agent._resolve_callables(run_context=ctx_b, session_state={})

    assert calls["count"] == 2
    assert ctx_a.tools is not ctx_b.tools


def test_separate_cache_keys_for_tools_and_knowledge():
    calls = {"tools": 0, "knowledge": 0}

    def get_tools(run_context: RunContext):
        calls["tools"] += 1
        return [object()]

    def get_knowledge(run_context: RunContext):
        calls["knowledge"] += 1
        return object()

    agent = Agent(
        tools=get_tools,
        knowledge=get_knowledge,  # type: ignore[arg-type]
        cache_callables=True,
        callable_tools_cache_key=lambda ctx: str((ctx.dependencies or {}).get("tenant_id")),
        callable_knowledge_cache_key=lambda ctx: str(ctx.user_id),
    )

    ctx_a = RunContext(run_id="r1", session_id="s1", user_id="alice", dependencies={"tenant_id": "acme"})
    agent._resolve_callables(run_context=ctx_a, session_state={})

    ctx_b = RunContext(run_id="r2", session_id="s2", user_id="alice", dependencies={"tenant_id": "globex"})
    agent._resolve_callables(run_context=ctx_b, session_state={})

    # Tools cached per tenant_id -> factory called twice
    # Knowledge cached per user_id -> factory called once
    assert calls == {"tools": 2, "knowledge": 1}
    assert ctx_a.tools is not ctx_b.tools
    assert ctx_a.knowledge is ctx_b.knowledge


def test_resolve_callables_raises_for_async_tools_factory_in_sync_path():
    async def get_tools(run_context: RunContext):
        return [object()]

    agent = Agent(tools=get_tools, cache_callables=True)
    ctx = RunContext(run_id="r1", session_id="s1", user_id="alice")

    with pytest.raises(RuntimeError) as excinfo:
        agent._resolve_callables(run_context=ctx, session_state={})

    assert "Tools function is async" in str(excinfo.value)


def test_clear_callable_cache_can_close_sync_resources():
    class Closable:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    tool = Closable()
    knowledge = Closable()

    def get_tools(run_context: RunContext):
        return [tool]

    def get_knowledge(run_context: RunContext):
        return knowledge

    agent = Agent(
        tools=get_tools,
        knowledge=get_knowledge,  # type: ignore[arg-type]
        cache_callables=True,
        callable_cache_key=lambda ctx: "k",
    )

    ctx = RunContext(run_id="r1", session_id="s1", user_id="alice")
    agent._resolve_callables(run_context=ctx, session_state={})

    agent.clear_callable_cache(key="k", close=True)

    assert tool.closed is True
    assert knowledge.closed is True


@pytest.mark.asyncio
async def test_aresolve_callables_supports_async_factories():
    calls = {"tools": 0, "knowledge": 0}
    tool_instance = object()
    knowledge_instance = object()

    async def get_tools(run_context: RunContext):
        await asyncio.sleep(0)
        calls["tools"] += 1
        return [tool_instance]

    async def get_knowledge(run_context: RunContext):
        await asyncio.sleep(0)
        calls["knowledge"] += 1
        return knowledge_instance

    agent = Agent(tools=get_tools, knowledge=get_knowledge, cache_callables=True)

    ctx1 = RunContext(run_id="r1", session_id="s1", user_id="alice")
    await agent._aresolve_callables(run_context=ctx1, session_state={})
    assert ctx1.tools == [tool_instance]
    assert ctx1.knowledge is knowledge_instance

    ctx2 = RunContext(run_id="r2", session_id="s2", user_id="alice")
    await agent._aresolve_callables(run_context=ctx2, session_state={})

    # Cached by user_id, so both factories run once.
    assert calls == {"tools": 1, "knowledge": 1}
    assert ctx1.tools is ctx2.tools
    assert ctx1.knowledge is ctx2.knowledge


@pytest.mark.asyncio
async def test_aclear_callable_cache_can_close_async_resources():
    class AsyncClosable:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    tool = AsyncClosable()
    knowledge = AsyncClosable()

    def get_tools(run_context: RunContext):
        return [tool]

    def get_knowledge(run_context: RunContext):
        return knowledge

    agent = Agent(
        tools=get_tools,
        knowledge=get_knowledge,  # type: ignore[arg-type]
        cache_callables=True,
        callable_cache_key=lambda ctx: "k",
    )

    ctx = RunContext(run_id="r1", session_id="s1", user_id="alice")
    agent._resolve_callables(run_context=ctx, session_state={})

    await agent.aclear_callable_cache(key="k", close=True)

    assert tool.closed is True
    assert knowledge.closed is True
