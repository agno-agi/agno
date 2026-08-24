"""Tests for pre-hook execution on Agent continue_run paths.

Pre-hooks are opt-in on continue_run — by default they skip since the input was
already validated on the initial run(). Hooks that need to run on continue_run
must be decorated with @hook(run_on_continue=True).
"""

import asyncio

import agno.agent._messages as agent_messages
import agno.agent._response as agent_response
import agno.agent._storage as agent_storage
import agno.agent._telemetry as agent_telemetry
import agno.agent._tools as agent_tools
from agno.agent import _run as agent_run
from agno.agent.agent import Agent
from agno.exceptions import InputCheckError
from agno.hooks import hook
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext, RunStatus
from agno.run.agent import RunInput, RunOutput
from agno.run.messages import RunMessages
from agno.session import AgentSession


def _make_paused_run() -> RunOutput:
    return RunOutput(
        run_id="run-1",
        session_id="session-1",
        status=RunStatus.paused,
        input=RunInput(input_content="original question"),
        messages=[Message(role="user", content="original question")],
    )


def _make_run_context() -> RunContext:
    return RunContext(run_id="run-1", session_id="session-1", user_id="user-1")


def _make_session() -> AgentSession:
    return AgentSession(session_id="session-1", user_id="user-1")


def _make_run_messages() -> RunMessages:
    return RunMessages(messages=[Message(role="user", content="original question")])


def _patch_sync_model(monkeypatch):
    """Stub the model call so it records invocations instead of hitting an LLM."""
    calls = []

    def fake_model(*args, **kwargs):
        calls.append(1)
        return ModelResponse(role="assistant", content="continued")

    monkeypatch.setattr(agent_run, "call_model_with_fallback", fake_model)
    return calls


def _empty_generator(*args, **kwargs):
    return
    yield


async def _empty_async_generator(*args, **kwargs):
    return
    yield


# ---------------------------------------------------------------------------
# Sync, non-streaming (_continue_run)
# ---------------------------------------------------------------------------


def test_continue_run_executes_pre_hooks(monkeypatch):
    calls = []

    @hook(run_on_continue=True)
    def pre_hook(run_input=None, session=None, user_id=None):
        calls.append({"session_id": getattr(session, "session_id", None), "user_id": user_id})

    agent = Agent(name="hook-test-agent", pre_hooks=[pre_hook])
    _patch_sync_model(monkeypatch)
    monkeypatch.setattr(agent_run, "cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(agent_telemetry, "log_agent_telemetry", lambda *a, **k: None)

    result = agent_run._continue_run(
        agent,
        run_response=_make_paused_run(),
        run_messages=_make_run_messages(),
        run_context=_make_run_context(),
        session=_make_session(),
        tools=[],
        user_id="user-1",
    )

    assert result.status == RunStatus.completed
    assert calls == [{"session_id": "session-1", "user_id": "user-1"}]


def test_continue_run_pre_hook_guardrail_blocks_model_call(monkeypatch):
    """A guardrail raising InputCheckError in a pre-hook must prevent the model
    loop on continue_run, with the same error behavior as run()."""

    @hook(run_on_continue=True)
    def blocking_hook(run_input=None):
        raise InputCheckError("authz denied on resume")

    agent = Agent(name="guard-test-agent", pre_hooks=[blocking_hook])
    model_calls = _patch_sync_model(monkeypatch)
    monkeypatch.setattr(agent_run, "cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(agent_telemetry, "log_agent_telemetry", lambda *a, **k: None)

    result = agent_run._continue_run(
        agent,
        run_response=_make_paused_run(),
        run_messages=_make_run_messages(),
        run_context=_make_run_context(),
        session=_make_session(),
        tools=[],
        user_id="user-1",
    )

    assert model_calls == [], "model must not be invoked when a pre-hook guardrail fails"
    assert result.status == RunStatus.error
    assert "authz denied on resume" in str(result.content)


# ---------------------------------------------------------------------------
# Sync, streaming (_continue_run_stream)
# ---------------------------------------------------------------------------


def test_continue_run_stream_executes_pre_hooks(monkeypatch):
    calls = []

    @hook(run_on_continue=True)
    def pre_hook(run_input=None, session=None, user_id=None):
        calls.append(getattr(session, "session_id", None))

    agent = Agent(name="hook-test-agent-stream", pre_hooks=[pre_hook])
    monkeypatch.setattr(agent_response, "handle_model_response_stream", _empty_generator)
    monkeypatch.setattr(agent_response, "parse_response_with_parser_model_stream", _empty_generator)
    monkeypatch.setattr(agent_response, "generate_followups_stream", _empty_generator)
    monkeypatch.setattr(agent_run, "cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(agent_telemetry, "log_agent_telemetry", lambda *a, **k: None)

    list(
        agent_run._continue_run_stream(
            agent,
            run_response=_make_paused_run(),
            run_messages=_make_run_messages(),
            run_context=_make_run_context(),
            session=_make_session(),
            tools=[],
            user_id="user-1",
        )
    )

    assert calls == ["session-1"]


def test_continue_run_stream_pre_hook_guardrail_blocks_model_stream(monkeypatch):
    @hook(run_on_continue=True)
    def blocking_hook(run_input=None):
        raise InputCheckError("authz denied on resume")

    agent = Agent(name="guard-test-agent-stream", pre_hooks=[blocking_hook])
    model_stream_calls = []

    def recording_model_stream(*args, **kwargs):
        model_stream_calls.append(1)
        return
        yield

    monkeypatch.setattr(agent_response, "handle_model_response_stream", recording_model_stream)
    monkeypatch.setattr(agent_response, "parse_response_with_parser_model_stream", _empty_generator)
    monkeypatch.setattr(agent_response, "generate_followups_stream", _empty_generator)
    monkeypatch.setattr(agent_run, "cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(agent_telemetry, "log_agent_telemetry", lambda *a, **k: None)

    list(
        agent_run._continue_run_stream(
            agent,
            run_response=_make_paused_run(),
            run_messages=_make_run_messages(),
            run_context=_make_run_context(),
            session=_make_session(),
            tools=[],
            user_id="user-1",
        )
    )

    assert model_stream_calls == [], "model stream must not be invoked when a pre-hook guardrail fails"


# ---------------------------------------------------------------------------
# Async, non-streaming (_acontinue_run)
# ---------------------------------------------------------------------------


def _patch_async_storage_and_tail(monkeypatch, model_calls):
    async def fake_session(agent, session_id=None, user_id=None):
        return AgentSession(session_id=session_id, user_id=user_id)

    async def fake_model(*args, **kwargs):
        model_calls.append(1)
        return ModelResponse(role="assistant", content="continued")

    async def async_noop(*args, **kwargs):
        return None

    monkeypatch.setattr(agent_storage, "aread_or_create_session", fake_session)
    monkeypatch.setattr(agent_storage, "load_session_state", lambda *a, **k: k.get("session_state") or {})
    monkeypatch.setattr(agent_storage, "update_metadata", lambda *a, **k: None)
    monkeypatch.setattr(agent_tools, "determine_tools_for_model", lambda *a, **k: [])
    monkeypatch.setattr(
        agent_messages,
        "get_continue_run_messages",
        lambda *a, **k: _make_run_messages(),
    )
    monkeypatch.setattr(agent_run, "acall_model_with_fallback", fake_model)
    monkeypatch.setattr(agent_run, "acleanup_and_store", async_noop)
    monkeypatch.setattr(agent_telemetry, "alog_agent_telemetry", async_noop)


def test_acontinue_run_executes_pre_hooks(monkeypatch):
    async def main():
        calls = []

        @hook(run_on_continue=True)
        async def pre_hook(run_input=None, session=None):
            calls.append(getattr(session, "session_id", None))

        agent = Agent(name="hook-test-agent-async", pre_hooks=[pre_hook])
        model_calls = []
        _patch_async_storage_and_tail(monkeypatch, model_calls)

        result = await agent_run._acontinue_run(
            agent,
            session_id="session-1",
            run_context=_make_run_context(),
            run_response=_make_paused_run(),
            updated_tools=[],
            user_id="user-1",
        )

        assert result.status == RunStatus.completed
        assert model_calls == [1]
        assert calls == ["session-1"]

    asyncio.run(main())


def test_acontinue_run_pre_hook_guardrail_blocks_model_call(monkeypatch):
    async def main():
        @hook(run_on_continue=True)
        def blocking_hook(run_input=None):
            raise InputCheckError("authz denied on resume")

        agent = Agent(name="guard-test-agent-async", pre_hooks=[blocking_hook])
        model_calls = []
        _patch_async_storage_and_tail(monkeypatch, model_calls)

        result = await agent_run._acontinue_run(
            agent,
            session_id="session-1",
            run_context=_make_run_context(),
            run_response=_make_paused_run(),
            updated_tools=[],
            user_id="user-1",
        )

        assert model_calls == [], "model must not be invoked when a pre-hook guardrail fails"
        assert result.status == RunStatus.error
        assert "authz denied on resume" in str(result.content)

    asyncio.run(main())


# ---------------------------------------------------------------------------
# Async, streaming (_acontinue_run_stream)
# ---------------------------------------------------------------------------


def test_acontinue_run_stream_executes_pre_hooks(monkeypatch):
    async def main():
        calls = []

        @hook(run_on_continue=True)
        async def pre_hook(run_input=None, session=None):
            calls.append(getattr(session, "session_id", None))

        agent = Agent(name="hook-test-agent-async-stream", pre_hooks=[pre_hook])
        model_calls = []
        _patch_async_storage_and_tail(monkeypatch, model_calls)
        monkeypatch.setattr(agent_response, "ahandle_model_response_stream", _empty_async_generator)
        monkeypatch.setattr(agent_response, "aparse_response_with_parser_model_stream", _empty_async_generator)
        monkeypatch.setattr(agent_response, "agenerate_followups_stream", _empty_async_generator)

        async for _ in agent_run._acontinue_run_stream(
            agent,
            session_id="session-1",
            run_context=_make_run_context(),
            run_response=_make_paused_run(),
            updated_tools=[],
            user_id="user-1",
        ):
            pass

        assert calls == ["session-1"]

    asyncio.run(main())


# ---------------------------------------------------------------------------
# Background hooks mode (run_hooks_in_background=True)
# ---------------------------------------------------------------------------


class _FakeBackgroundTasks:
    """Minimal stand-in for fastapi.BackgroundTasks."""

    def __init__(self):
        self.queued = []

    def add_task(self, func, **kwargs):
        self.queued.append(func)


def test_continue_run_background_mode_queues_non_guardrail_hooks(monkeypatch):
    """With background mode on, non-guardrail pre-hooks must be queued (not run
    inline) on continue_run — they must not silently vanish."""
    executed = []

    @hook(run_on_continue=True)
    def audit_hook(run_input=None, session=None):
        executed.append(1)

    agent = Agent(name="bg-continue-agent", pre_hooks=[audit_hook])
    agent._run_hooks_in_background = True
    _patch_sync_model(monkeypatch)
    monkeypatch.setattr(agent_run, "cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(agent_telemetry, "log_agent_telemetry", lambda *a, **k: None)
    background_tasks = _FakeBackgroundTasks()

    result = agent_run._continue_run(
        agent,
        run_response=_make_paused_run(),
        run_messages=_make_run_messages(),
        run_context=_make_run_context(),
        session=_make_session(),
        tools=[],
        user_id="user-1",
        background_tasks=background_tasks,
    )

    assert result.status == RunStatus.completed
    assert executed == [], "non-guardrail pre-hook must not run inline in background mode"
    assert background_tasks.queued == [audit_hook], "pre-hook should be queued for background execution"


def test_continue_run_background_mode_guardrail_runs_sync_and_blocks(monkeypatch):
    """Guardrail-shaped pre-hooks must still run synchronously in background mode
    so rejection propagates before the model loop (same as run())."""
    from agno.guardrails.base import BaseGuardrail

    class BlockingGuardrail(BaseGuardrail):
        def check(self, run_input=None):
            raise InputCheckError("blocked on resume")

        async def async_check(self, run_input=None):
            raise InputCheckError("blocked on resume (async)")

    agent = Agent(name="bg-guard-agent", pre_hooks=[BlockingGuardrail().check])
    agent._run_hooks_in_background = True
    model_calls = _patch_sync_model(monkeypatch)
    monkeypatch.setattr(agent_run, "cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(agent_telemetry, "log_agent_telemetry", lambda *a, **k: None)
    background_tasks = _FakeBackgroundTasks()

    result = agent_run._continue_run(
        agent,
        run_response=_make_paused_run(),
        run_messages=_make_run_messages(),
        run_context=_make_run_context(),
        session=_make_session(),
        tools=[],
        user_id="user-1",
        background_tasks=background_tasks,
    )

    assert model_calls == [], "guardrail must block the model call even in background mode"
    assert result.status == RunStatus.error
    assert "blocked on resume" in str(result.content)
    assert background_tasks.queued == [], "no hooks should be queued once a guardrail rejects"


def test_acontinue_run_background_mode_guardrail_runs_sync_and_blocks(monkeypatch):
    async def main():
        from agno.guardrails.base import BaseGuardrail

        class BlockingGuardrail(BaseGuardrail):
            def check(self, run_input=None):
                raise InputCheckError("blocked on resume")

            async def async_check(self, run_input=None):
                raise InputCheckError("blocked on resume (async)")

        agent = Agent(name="bg-guard-agent-async", pre_hooks=[BlockingGuardrail().check])
        agent._run_hooks_in_background = True
        model_calls = []
        _patch_async_storage_and_tail(monkeypatch, model_calls)
        background_tasks = _FakeBackgroundTasks()

        result = await agent_run._acontinue_run(
            agent,
            session_id="session-1",
            run_context=_make_run_context(),
            run_response=_make_paused_run(),
            updated_tools=[],
            user_id="user-1",
            background_tasks=background_tasks,
        )

        assert model_calls == [], "guardrail must block the model call even in background mode"
        assert result.status == RunStatus.error
        assert "blocked on resume" in str(result.content)

    asyncio.run(main())


# ---------------------------------------------------------------------------
# Streaming hook events (stream_events=True)
# ---------------------------------------------------------------------------


def test_continue_run_stream_emits_pre_hook_events(monkeypatch):
    """With stream_events=True, continue_run must emit the same hook lifecycle
    events as run()."""
    calls = []

    @hook(run_on_continue=True)
    def pre_hook(run_input=None, session=None):
        calls.append(1)

    agent = Agent(name="stream-ev-agent", pre_hooks=[pre_hook])
    monkeypatch.setattr(agent_response, "handle_model_response_stream", _empty_generator)
    monkeypatch.setattr(agent_response, "parse_response_with_parser_model_stream", _empty_generator)
    monkeypatch.setattr(agent_response, "generate_followups_stream", _empty_generator)
    monkeypatch.setattr(agent_run, "cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(agent_telemetry, "log_agent_telemetry", lambda *a, **k: None)

    events = list(
        agent_run._continue_run_stream(
            agent,
            run_response=_make_paused_run(),
            run_messages=_make_run_messages(),
            run_context=_make_run_context(),
            session=_make_session(),
            tools=[],
            user_id="user-1",
            stream_events=True,
        )
    )

    assert calls == [1]
    event_names = [type(e).__name__ for e in events]
    assert any(name.startswith("PreHookStarted") for name in event_names), event_names
    assert any(name.startswith("PreHookCompleted") for name in event_names), event_names


# ---------------------------------------------------------------------------
# @hook(run_on_continue=True) decorator filtering
# ---------------------------------------------------------------------------


def test_continue_run_skips_pre_hooks_by_default(monkeypatch):
    """Hooks without @hook(run_on_continue=True) are skipped on continue_run."""
    calls = []

    def pre_hook(run_input=None, session=None):
        calls.append(1)

    agent = Agent(name="default-skip-hook-agent", pre_hooks=[pre_hook])
    _patch_sync_model(monkeypatch)
    monkeypatch.setattr(agent_run, "cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(agent_telemetry, "log_agent_telemetry", lambda *a, **k: None)

    result = agent_run._continue_run(
        agent,
        run_response=_make_paused_run(),
        run_messages=_make_run_messages(),
        run_context=_make_run_context(),
        session=_make_session(),
        tools=[],
        user_id="user-1",
    )

    assert result.status == RunStatus.completed
    assert calls == [], "pre-hooks should be skipped by default on continue_run"


def test_continue_run_runs_pre_hooks_when_decorated(monkeypatch):
    """Pre-hooks decorated with @hook(run_on_continue=True) run on continue_run."""
    calls = []

    @hook(run_on_continue=True)
    def opt_in_hook(run_input=None, session=None):
        calls.append("opt_in")

    def regular_hook(run_input=None, session=None):
        calls.append("regular")

    agent = Agent(name="mixed-hooks-agent", pre_hooks=[opt_in_hook, regular_hook])
    _patch_sync_model(monkeypatch)
    monkeypatch.setattr(agent_run, "cleanup_and_store", lambda *a, **k: None)
    monkeypatch.setattr(agent_telemetry, "log_agent_telemetry", lambda *a, **k: None)

    result = agent_run._continue_run(
        agent,
        run_response=_make_paused_run(),
        run_messages=_make_run_messages(),
        run_context=_make_run_context(),
        session=_make_session(),
        tools=[],
        user_id="user-1",
    )

    assert result.status == RunStatus.completed
    assert calls == ["opt_in"], "only hooks with @hook(run_on_continue=True) should run"


# ---------------------------------------------------------------------------
# Decorator attribute tests
# ---------------------------------------------------------------------------


def test_decorator_combined_options():
    """@hook with both run_in_background and run_on_continue works."""
    from agno.hooks.decorator import should_run_in_background, should_run_on_continue

    @hook(run_in_background=True, run_on_continue=True)
    def background_audit(run_input=None):
        pass

    assert should_run_in_background(background_audit) is True
    assert should_run_on_continue(background_audit) is True


def test_decorator_default_false():
    """Hooks without decorator return False for should_run_on_continue."""
    from agno.hooks.decorator import should_run_on_continue

    def plain_hook():
        pass

    assert should_run_on_continue(plain_hook) is False


def test_decorator_bare_hook():
    """@hook without parentheses returns False for run_on_continue."""
    from agno.hooks.decorator import should_run_on_continue

    @hook
    def bare_hook():
        pass

    assert should_run_on_continue(bare_hook) is False


def test_decorator_async_hook():
    """Async hooks work with @hook(run_on_continue=True)."""
    from agno.hooks.decorator import should_run_on_continue

    @hook(run_on_continue=True)
    async def async_hook():
        pass

    assert should_run_on_continue(async_hook) is True
