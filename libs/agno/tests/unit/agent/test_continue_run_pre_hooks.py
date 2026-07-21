"""Tests for pre-hook execution on Agent continue_run paths.

Regression coverage for the gap where run()/arun() execute pre_hooks but
continue_run()/acontinue_run() (and their streaming variants) used to skip
them — allowing HITL-resumed runs to bypass guardrail/authz hooks.
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
