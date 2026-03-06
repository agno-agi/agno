import inspect
from typing import Any, Optional

import pytest

from agno.agent import _init, _messages, _response, _run, _session, _storage, _tools
from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.run import RunContext
from agno.run.agent import RunErrorEvent, RunOutput
from agno.run.base import RunStatus
from agno.run.cancel import (
    cancel_run,
    cleanup_run,
    get_active_runs,
    get_cancellation_manager,
    is_cancelled,
    register_run,
    set_cancellation_manager,
)
from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager
from agno.run.messages import RunMessages
from agno.session import AgentSession


@pytest.fixture(autouse=True)
def reset_cancellation_manager():
    original_manager = get_cancellation_manager()
    set_cancellation_manager(InMemoryRunCancellationManager())
    try:
        yield
    finally:
        set_cancellation_manager(original_manager)


def _patch_sync_dispatch_dependencies(
    agent: Agent,
    monkeypatch: pytest.MonkeyPatch,
    runs: Optional[list[Any]] = None,
) -> None:
    monkeypatch.setattr(_init, "has_async_db", lambda agent: False)
    monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
    monkeypatch.setattr(_storage, "load_session_state", lambda agent, session=None, session_state=None: session_state)
    monkeypatch.setattr(_run, "resolve_run_dependencies", lambda agent, run_context: None)
    monkeypatch.setattr(_response, "get_response_format", lambda agent, run_context=None: None)
    monkeypatch.setattr(
        _storage,
        "read_or_create_session",
        lambda agent, session_id=None, user_id=None: AgentSession(session_id=session_id, user_id=user_id, runs=runs),
    )


def test_run_dispatch_cleans_up_registered_run_on_setup_failure(monkeypatch: pytest.MonkeyPatch):
    agent = Agent(name="test-agent")
    _patch_sync_dispatch_dependencies(agent, monkeypatch, runs=[])

    def failing_initialize_agent(debug_mode=None):
        raise RuntimeError("initialize failed")

    monkeypatch.setattr(agent, "initialize_agent", failing_initialize_agent)

    run_id = "run-setup-fail"
    with pytest.raises(RuntimeError, match="initialize failed"):
        _run.run_dispatch(agent=agent, input="hello", run_id=run_id, stream=False)

    assert run_id not in get_active_runs()


def test_run_dispatch_does_not_reset_cancellation_before_impl(monkeypatch: pytest.MonkeyPatch):
    agent = Agent(name="test-agent")
    _patch_sync_dispatch_dependencies(agent, monkeypatch, runs=[])

    run_id = "run-preserve-cancelled-state"

    def initialize_and_cancel(debug_mode=None):
        # register_run now happens inside _run, so we register here to test cancellation
        register_run(run_id)
        assert cancel_run(run_id) is True

    monkeypatch.setattr(agent, "initialize_agent", initialize_and_cancel)

    observed: dict[str, bool] = {}

    def fake_run_impl(
        agent: Agent,
        run_response,
        run_context,
        session_id: str = "",
        user_id: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        response_format: Optional[Any] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ):
        observed["cancelled_before_model"] = is_cancelled(run_response.run_id)  # type: ignore[arg-type]
        cleanup_run(run_response.run_id)  # type: ignore[arg-type]
        return run_response

    monkeypatch.setattr(_run, "_run", fake_run_impl)

    _run.run_dispatch(agent=agent, input="hello", run_id=run_id, stream=False)

    assert observed["cancelled_before_model"] is True
    assert run_id not in get_active_runs()


def test_continue_run_dispatch_handles_none_session_runs(monkeypatch: pytest.MonkeyPatch):
    agent = Agent(name="test-agent")
    monkeypatch.setattr(_init, "has_async_db", lambda agent: False)
    monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)
    monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
    monkeypatch.setattr(_storage, "load_session_state", lambda agent, session=None, session_state=None: session_state)
    monkeypatch.setattr(
        _storage,
        "read_or_create_session",
        lambda agent, session_id=None, user_id=None: AgentSession(session_id=session_id, user_id=user_id, runs=None),
    )

    with pytest.raises(RuntimeError, match="No runs found for run ID missing-run"):
        _run.continue_run_dispatch(
            agent=agent,
            run_id="missing-run",
            requirements=[],
            session_id="session-1",
        )


@pytest.mark.asyncio
async def test_acontinue_run_dispatch_handles_none_session_runs(monkeypatch: pytest.MonkeyPatch):
    agent = Agent(name="test-agent")
    monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)
    monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
    monkeypatch.setattr(_storage, "load_session_state", lambda agent, session=None, session_state=None: session_state)

    async def fake_aread_or_create_session(agent, session_id: str, user_id: Optional[str] = None):
        return AgentSession(session_id=session_id, user_id=user_id, runs=None)

    async def fake_acleanup_and_store(agent, **kwargs: Any):
        return None

    async def fake_disconnect_mcp_tools(agent):
        return None

    monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
    monkeypatch.setattr(_run, "acleanup_and_store", fake_acleanup_and_store)
    monkeypatch.setattr(_init, "disconnect_connectable_tools", lambda agent: None)
    monkeypatch.setattr(_init, "disconnect_mcp_tools", fake_disconnect_mcp_tools)

    response = await _run.acontinue_run_dispatch(
        agent=agent,
        run_id="missing-run",
        requirements=[],
        session_id="session-1",
        stream=False,
    )

    assert response.status == RunStatus.error
    assert isinstance(response.content, str)
    assert "No runs found for run ID missing-run" in response.content


@pytest.mark.asyncio
async def test_acontinue_run_stream_yields_error_event_without_attribute_error(
    monkeypatch: pytest.MonkeyPatch,
):
    agent = Agent(name="test-agent")
    run_id = "missing-stream-run"

    async def fake_aread_or_create_session(agent, session_id: str, user_id: Optional[str] = None):
        return AgentSession(session_id=session_id, user_id=user_id, runs=None)

    async def fake_disconnect_mcp_tools(agent):
        return None

    monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
    monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
    monkeypatch.setattr(_storage, "load_session_state", lambda agent, session=None, session_state=None: session_state)
    monkeypatch.setattr(_init, "disconnect_connectable_tools", lambda agent: None)
    monkeypatch.setattr(_init, "disconnect_mcp_tools", fake_disconnect_mcp_tools)

    run_context = RunContext(
        run_id=run_id,
        session_id="session-1",
        user_id=None,
        session_state={},
    )

    events = []
    async for event in _run._acontinue_run_stream(
        agent=agent,
        session_id="session-1",
        run_context=run_context,
        run_id=run_id,
        requirements=[],
    ):
        events.append(event)

    assert len(events) == 1
    assert isinstance(events[0], RunErrorEvent)
    assert events[0].run_id == run_id
    assert events[0].content is not None
    assert "No runs found for run ID missing-stream-run" in events[0].content


@pytest.mark.asyncio
async def test_arun_stream_impl_cleans_up_registered_run_on_session_read_failure(monkeypatch: pytest.MonkeyPatch):
    agent = Agent(name="test-agent")
    run_id = "arun-stream-session-fail"

    async def fail_aread_or_create_session(agent, session_id: str, user_id: Optional[str] = None):
        raise RuntimeError("session read failed")

    async def fake_disconnect_mcp_tools(agent):
        return None

    monkeypatch.setattr(_storage, "aread_or_create_session", fail_aread_or_create_session)
    monkeypatch.setattr(_init, "disconnect_connectable_tools", lambda agent: None)
    monkeypatch.setattr(_init, "disconnect_mcp_tools", fake_disconnect_mcp_tools)

    run_context = RunContext(run_id=run_id, session_id="session-1", session_state={})
    run_response = RunOutput(run_id=run_id)

    response_stream = _run._arun_stream(
        agent=agent,
        run_response=run_response,
        run_context=run_context,
        session_id="session-1",
    )

    # Consume the error event yielded by the stream
    events = []
    async for event in response_stream:
        events.append(event)

    # Verify an error event was yielded with the session read failure
    assert len(events) == 1
    assert isinstance(events[0], RunErrorEvent)
    assert "session read failed" in events[0].content

    assert run_id not in get_active_runs()


@pytest.mark.asyncio
async def test_arun_impl_preserves_original_error_when_session_read_fails(monkeypatch: pytest.MonkeyPatch):
    agent = Agent(name="test-agent")
    run_id = "arun-session-fail"
    cleanup_calls = []

    async def fail_aread_or_create_session(agent, session_id: str, user_id: Optional[str] = None):
        raise RuntimeError("session read failed")

    async def fake_acleanup_and_store(agent, **kwargs: Any):
        cleanup_calls.append(kwargs)
        return None

    async def fake_disconnect_mcp_tools(agent):
        return None

    monkeypatch.setattr(_storage, "aread_or_create_session", fail_aread_or_create_session)
    monkeypatch.setattr(_run, "acleanup_and_store", fake_acleanup_and_store)
    monkeypatch.setattr(_init, "disconnect_connectable_tools", lambda agent: None)
    monkeypatch.setattr(_init, "disconnect_mcp_tools", fake_disconnect_mcp_tools)

    run_context = RunContext(run_id=run_id, session_id="session-1", session_state={})
    run_response = RunOutput(run_id=run_id)

    response = await _run._arun(
        agent=agent,
        run_response=run_response,
        run_context=run_context,
        session_id="session-1",
    )

    assert response.status == RunStatus.error
    assert response.content == "session read failed"
    assert cleanup_calls == []
    assert run_id not in get_active_runs()


@pytest.mark.asyncio
async def test_acontinue_run_preserves_original_error_when_session_read_fails(monkeypatch: pytest.MonkeyPatch):
    agent = Agent(name="test-agent")
    run_id = "acontinue-session-fail"
    cleanup_calls = []

    async def fail_aread_or_create_session(agent, session_id: str, user_id: Optional[str] = None):
        raise RuntimeError("session read failed")

    async def fake_acleanup_and_store(agent, **kwargs: Any):
        cleanup_calls.append(kwargs)
        return None

    async def fake_disconnect_mcp_tools(agent):
        return None

    monkeypatch.setattr(_storage, "aread_or_create_session", fail_aread_or_create_session)
    monkeypatch.setattr(_run, "acleanup_and_store", fake_acleanup_and_store)
    monkeypatch.setattr(_init, "disconnect_connectable_tools", lambda agent: None)
    monkeypatch.setattr(_init, "disconnect_mcp_tools", fake_disconnect_mcp_tools)

    run_context = RunContext(run_id=run_id, session_id="session-1", session_state={})

    response = await _run._acontinue_run(
        agent=agent,
        session_id="session-1",
        run_context=run_context,
        run_id=run_id,
        requirements=[],
    )

    assert response.status == RunStatus.error
    assert response.content == "session read failed"
    assert cleanup_calls == []
    assert run_id not in get_active_runs()


def test_continue_run_stream_registers_run_for_cancellation():
    agent = Agent(name="test-agent")
    run_id = "continue-stream-register"

    run_response = RunOutput(run_id=run_id)
    run_messages = RunMessages(messages=[])
    run_context = RunContext(run_id=run_id, session_id="session-1", session_state={})
    session = AgentSession(session_id="session-1")

    response_stream = _run._continue_run_stream(
        agent=agent,
        run_response=run_response,
        run_messages=run_messages,
        run_context=run_context,
        session=session,
        tools=[],
        stream_events=True,
    )

    next(response_stream)

    assert run_id in get_active_runs()
    assert cancel_run(run_id) is True

    response_stream.close()
    assert run_id not in get_active_runs()


def test_session_read_wrappers_default_to_agent_session_type():
    read_default = inspect.signature(_storage.read_session).parameters["session_type"].default
    aread_default = inspect.signature(_storage.aread_session).parameters["session_type"].default

    assert read_default == SessionType.AGENT
    assert aread_default == SessionType.AGENT


def _make_precedence_test_agent() -> Agent:
    return Agent(
        name="precedence-agent",
        dependencies={"agent_dep": "default"},
        knowledge_filters={"agent_filter": "default"},
        metadata={"agent_meta": "default"},
        output_schema={"type": "object", "properties": {"agent": {"type": "string"}}},
    )


def _patch_continue_dispatch_dependencies(agent: Agent, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_init, "has_async_db", lambda agent: False)
    monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)
    monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
    monkeypatch.setattr(_storage, "load_session_state", lambda agent, session=None, session_state=None: session_state)
    monkeypatch.setattr(
        _storage,
        "read_or_create_session",
        lambda agent, session_id=None, user_id=None: AgentSession(session_id=session_id, user_id=user_id, runs=[]),
    )
    monkeypatch.setattr(_init, "set_default_model", lambda agent: None)
    monkeypatch.setattr(_response, "get_response_format", lambda agent, run_context=None: None)
    monkeypatch.setattr(agent, "get_tools", lambda **kwargs: [])
    monkeypatch.setattr(_tools, "determine_tools_for_model", lambda agent, **kwargs: [])
    monkeypatch.setattr(_messages, "get_continue_run_messages", lambda agent, input=None: RunMessages(messages=[]))


def test_run_dispatch_respects_run_context_precedence(monkeypatch: pytest.MonkeyPatch):
    agent = _make_precedence_test_agent()
    _patch_sync_dispatch_dependencies(agent, monkeypatch, runs=[])
    monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)

    def fake_run_impl(
        agent: Agent,
        run_response,
        run_context,
        session_id: str = "",
        user_id: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        response_format: Optional[Any] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ):
        cleanup_run(run_response.run_id)  # type: ignore[arg-type]
        return run_response

    monkeypatch.setattr(_run, "_run", fake_run_impl)

    preserved_context = RunContext(
        run_id="ctx-preserve",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
        output_schema={"ctx_schema": "keep"},
    )
    _run.run_dispatch(
        agent=agent,
        input="hello",
        run_id="run-preserve",
        stream=False,
        run_context=preserved_context,
    )
    assert preserved_context.dependencies == {"ctx_dep": "keep"}
    assert preserved_context.knowledge_filters == {"ctx_filter": "keep"}
    assert preserved_context.metadata == {"ctx_meta": "keep"}
    # output_schema is always set from resolved options (for workflow reuse)
    assert preserved_context.output_schema == {"type": "object", "properties": {"agent": {"type": "string"}}}

    override_context = RunContext(
        run_id="ctx-override",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
        output_schema={"ctx_schema": "keep"},
    )
    _run.run_dispatch(
        agent=agent,
        input="hello",
        run_id="run-override",
        stream=False,
        run_context=override_context,
        dependencies={"call_dep": "override"},
        knowledge_filters={"call_filter": "override"},
        metadata={"call_meta": "override"},
        output_schema={"call_schema": "override"},
    )
    assert override_context.dependencies == {"call_dep": "override"}
    assert override_context.knowledge_filters == {"agent_filter": "default", "call_filter": "override"}
    assert override_context.metadata == {"call_meta": "override", "agent_meta": "default"}
    assert override_context.output_schema == {"call_schema": "override"}

    empty_context = RunContext(
        run_id="ctx-empty",
        session_id="session-1",
        session_state={},
        dependencies=None,
        knowledge_filters=None,
        metadata=None,
        output_schema=None,
    )
    _run.run_dispatch(
        agent=agent,
        input="hello",
        run_id="run-empty",
        stream=False,
        run_context=empty_context,
    )
    assert empty_context.dependencies == {"agent_dep": "default"}
    assert empty_context.knowledge_filters == {"agent_filter": "default"}
    assert empty_context.metadata == {"agent_meta": "default"}
    assert empty_context.output_schema == {"type": "object", "properties": {"agent": {"type": "string"}}}


@pytest.mark.asyncio
async def test_arun_dispatch_respects_run_context_precedence(monkeypatch: pytest.MonkeyPatch):
    agent = _make_precedence_test_agent()
    monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)
    monkeypatch.setattr(_response, "get_response_format", lambda agent, run_context=None: None)

    async def fake_arun_impl(
        agent: Agent,
        run_response,
        run_context,
        user_id: Optional[str] = None,
        response_format: Optional[Any] = None,
        session_id: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ):
        return run_response

    monkeypatch.setattr(_run, "_arun", fake_arun_impl)

    preserved_context = RunContext(
        run_id="actx-preserve",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
        output_schema={"ctx_schema": "keep"},
    )
    await _run.arun_dispatch(
        agent=agent,
        input="hello",
        run_id="arun-preserve",
        stream=False,
        run_context=preserved_context,
    )
    assert preserved_context.dependencies == {"ctx_dep": "keep"}
    assert preserved_context.knowledge_filters == {"ctx_filter": "keep"}
    assert preserved_context.metadata == {"ctx_meta": "keep"}
    # output_schema is always set from resolved options (for workflow reuse)
    assert preserved_context.output_schema == {"type": "object", "properties": {"agent": {"type": "string"}}}

    override_context = RunContext(
        run_id="actx-override",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
        output_schema={"ctx_schema": "keep"},
    )
    await _run.arun_dispatch(
        agent=agent,
        input="hello",
        run_id="arun-override",
        stream=False,
        run_context=override_context,
        dependencies={"call_dep": "override"},
        knowledge_filters={"call_filter": "override"},
        metadata={"call_meta": "override"},
        output_schema={"call_schema": "override"},
    )
    assert override_context.dependencies == {"call_dep": "override"}
    assert override_context.knowledge_filters == {"agent_filter": "default", "call_filter": "override"}
    assert override_context.metadata == {"call_meta": "override", "agent_meta": "default"}
    assert override_context.output_schema == {"call_schema": "override"}

    empty_context = RunContext(
        run_id="actx-empty",
        session_id="session-1",
        session_state={},
        dependencies=None,
        knowledge_filters=None,
        metadata=None,
        output_schema=None,
    )
    await _run.arun_dispatch(
        agent=agent,
        input="hello",
        run_id="arun-empty",
        stream=False,
        run_context=empty_context,
    )
    assert empty_context.dependencies == {"agent_dep": "default"}
    assert empty_context.knowledge_filters == {"agent_filter": "default"}
    assert empty_context.metadata == {"agent_meta": "default"}
    assert empty_context.output_schema == {"type": "object", "properties": {"agent": {"type": "string"}}}


def test_continue_run_dispatch_respects_run_context_precedence(monkeypatch: pytest.MonkeyPatch):
    agent = _make_precedence_test_agent()
    _patch_continue_dispatch_dependencies(agent, monkeypatch)

    def fake_continue_run(
        agent: Agent,
        run_response: RunOutput,
        run_messages: RunMessages,
        run_context: RunContext,
        session: AgentSession,
        tools,
        user_id: Optional[str] = None,
        response_format: Optional[Any] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> RunOutput:
        return run_response

    monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

    preserved_context = RunContext(
        run_id="continue-preserve",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
    )
    _run.continue_run_dispatch(
        agent=agent,
        run_response=RunOutput(run_id="continue-run-1", session_id="session-1", messages=[]),
        stream=False,
        run_context=preserved_context,
    )
    assert preserved_context.dependencies == {"ctx_dep": "keep"}
    assert preserved_context.knowledge_filters == {"ctx_filter": "keep"}
    assert preserved_context.metadata == {"ctx_meta": "keep"}

    override_context = RunContext(
        run_id="continue-override",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
    )
    _run.continue_run_dispatch(
        agent=agent,
        run_response=RunOutput(run_id="continue-run-2", session_id="session-1", messages=[]),
        stream=False,
        run_context=override_context,
        dependencies={"call_dep": "override"},
        knowledge_filters={"call_filter": "override"},
        metadata={"call_meta": "override"},
    )
    assert override_context.dependencies == {"call_dep": "override"}
    assert override_context.knowledge_filters == {"agent_filter": "default", "call_filter": "override"}
    assert override_context.metadata == {"call_meta": "override", "agent_meta": "default"}

    empty_context = RunContext(
        run_id="continue-empty",
        session_id="session-1",
        session_state={},
        dependencies=None,
        knowledge_filters=None,
        metadata=None,
    )
    _run.continue_run_dispatch(
        agent=agent,
        run_response=RunOutput(run_id="continue-run-3", session_id="session-1", messages=[]),
        stream=False,
        run_context=empty_context,
    )
    assert empty_context.dependencies == {"agent_dep": "default"}
    assert empty_context.knowledge_filters == {"agent_filter": "default"}
    assert empty_context.metadata == {"agent_meta": "default"}


@pytest.mark.asyncio
async def test_acontinue_run_dispatch_respects_run_context_precedence(monkeypatch: pytest.MonkeyPatch):
    agent = _make_precedence_test_agent()
    monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)
    monkeypatch.setattr(_response, "get_response_format", lambda agent, run_context=None: None)

    async def fake_acontinue_run(
        agent: Agent,
        session_id: str,
        run_context: RunContext,
        run_response: Optional[RunOutput] = None,
        updated_tools=None,
        requirements=None,
        run_id: Optional[str] = None,
        user_id: Optional[str] = None,
        response_format: Optional[Any] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> RunOutput:
        return run_response if run_response is not None else RunOutput(run_id=run_id, session_id=session_id)  # type: ignore[arg-type]

    monkeypatch.setattr(_run, "_acontinue_run", fake_acontinue_run)

    preserved_context = RunContext(
        run_id="acontinue-preserve",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
    )
    await _run.acontinue_run_dispatch(
        agent=agent,
        run_response=RunOutput(run_id="acontinue-run-1", session_id="session-1", messages=[]),
        stream=False,
        run_context=preserved_context,
    )
    assert preserved_context.dependencies == {"ctx_dep": "keep"}
    assert preserved_context.knowledge_filters == {"ctx_filter": "keep"}
    assert preserved_context.metadata == {"ctx_meta": "keep"}

    override_context = RunContext(
        run_id="acontinue-override",
        session_id="session-1",
        session_state={},
        dependencies={"ctx_dep": "keep"},
        knowledge_filters={"ctx_filter": "keep"},
        metadata={"ctx_meta": "keep"},
    )
    await _run.acontinue_run_dispatch(
        agent=agent,
        run_response=RunOutput(run_id="acontinue-run-2", session_id="session-1", messages=[]),
        stream=False,
        run_context=override_context,
        dependencies={"call_dep": "override"},
        knowledge_filters={"call_filter": "override"},
        metadata={"call_meta": "override"},
    )
    assert override_context.dependencies == {"call_dep": "override"}
    assert override_context.knowledge_filters == {"agent_filter": "default", "call_filter": "override"}
    assert override_context.metadata == {"call_meta": "override", "agent_meta": "default"}

    empty_context = RunContext(
        run_id="acontinue-empty",
        session_id="session-1",
        session_state={},
        dependencies=None,
        knowledge_filters=None,
        metadata=None,
    )
    await _run.acontinue_run_dispatch(
        agent=agent,
        run_response=RunOutput(run_id="acontinue-run-3", session_id="session-1", messages=[]),
        stream=False,
        run_context=empty_context,
    )
    assert empty_context.dependencies == {"agent_dep": "default"}
    assert empty_context.knowledge_filters == {"agent_filter": "default"}
    assert empty_context.metadata == {"agent_meta": "default"}


def test_all_pause_handlers_accept_run_context():
    for fn in [
        _run.handle_agent_run_paused,
        _run.handle_agent_run_paused_stream,
        _run.ahandle_agent_run_paused,
        _run.ahandle_agent_run_paused_stream,
    ]:
        params = inspect.signature(fn).parameters
        assert "run_context" in params, f"{fn.__name__} missing run_context param"


def test_handle_agent_run_paused_forwards_run_context_to_cleanup(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    def spy_cleanup_and_store(agent, run_response, session, run_context=None, user_id=None):
        captured["run_context"] = run_context

    monkeypatch.setattr(_run, "cleanup_and_store", spy_cleanup_and_store)
    monkeypatch.setattr(_run, "create_approval_from_pause", lambda **kwargs: None)

    agent = Agent(name="test-hitl")
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"key": "val"})

    _run.handle_agent_run_paused(
        agent=agent,
        run_response=RunOutput(run_id="r1", session_id="s1", messages=[]),
        session=AgentSession(session_id="s1"),
        user_id="u1",
        run_context=run_context,
    )

    assert captured["run_context"] is run_context


@pytest.mark.asyncio
async def test_ahandle_agent_run_paused_forwards_run_context_to_cleanup(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def spy_acleanup_and_store(agent, run_response, session, run_context=None, user_id=None):
        captured["run_context"] = run_context

    async def noop_acreate_approval(**kwargs):
        return None

    monkeypatch.setattr(_run, "acleanup_and_store", spy_acleanup_and_store)
    monkeypatch.setattr(_run, "acreate_approval_from_pause", noop_acreate_approval)

    agent = Agent(name="test-hitl-async")
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"key": "val"})

    await _run.ahandle_agent_run_paused(
        agent=agent,
        run_response=RunOutput(run_id="r1", session_id="s1", messages=[]),
        session=AgentSession(session_id="s1"),
        user_id="u1",
        run_context=run_context,
    )

    assert captured["run_context"] is run_context


def test_handle_agent_run_paused_persists_session_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_session, "save_session", lambda agent, session: None)
    monkeypatch.setattr(_run, "create_approval_from_pause", lambda **kwargs: None)
    monkeypatch.setattr(_run, "scrub_run_output_for_storage", lambda agent, run_response: None)
    monkeypatch.setattr(_run, "save_run_response_to_file", lambda agent, **kwargs: None)
    monkeypatch.setattr(_run, "update_session_metrics", lambda agent, session, run_response: None)

    agent = Agent(name="test-hitl")
    session = AgentSession(session_id="s1", session_data={})
    run_response = RunOutput(run_id="r1", session_id="s1", messages=[])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"watchlist": ["AAPL"]})

    result = _run.handle_agent_run_paused(
        agent=agent,
        run_response=run_response,
        session=session,
        user_id="u1",
        run_context=run_context,
    )

    assert result.status == RunStatus.paused
    assert session.session_data["session_state"] == {"watchlist": ["AAPL"]}
    assert result.session_state == {"watchlist": ["AAPL"]}


def test_handle_agent_run_paused_without_run_context_does_not_set_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_session, "save_session", lambda agent, session: None)
    monkeypatch.setattr(_run, "create_approval_from_pause", lambda **kwargs: None)
    monkeypatch.setattr(_run, "scrub_run_output_for_storage", lambda agent, run_response: None)
    monkeypatch.setattr(_run, "save_run_response_to_file", lambda agent, **kwargs: None)
    monkeypatch.setattr(_run, "update_session_metrics", lambda agent, session, run_response: None)

    agent = Agent(name="test-hitl")
    session = AgentSession(session_id="s1", session_data={})

    result = _run.handle_agent_run_paused(
        agent=agent,
        run_response=RunOutput(run_id="r1", session_id="s1", messages=[]),
        session=session,
        user_id="u1",
    )

    assert result.status == RunStatus.paused
    assert "session_state" not in session.session_data


def test_handle_agent_run_paused_persists_state_when_session_data_is_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_session, "save_session", lambda agent, session: None)
    monkeypatch.setattr(_run, "create_approval_from_pause", lambda **kwargs: None)
    monkeypatch.setattr(_run, "scrub_run_output_for_storage", lambda agent, run_response: None)
    monkeypatch.setattr(_run, "save_run_response_to_file", lambda agent, **kwargs: None)
    monkeypatch.setattr(_run, "update_session_metrics", lambda agent, session, run_response: None)

    agent = Agent(name="test-hitl")
    session = AgentSession(session_id="s1", session_data=None)
    run_response = RunOutput(run_id="r1", session_id="s1", messages=[])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"watchlist": ["AAPL"]})

    result = _run.handle_agent_run_paused(
        agent=agent,
        run_response=run_response,
        session=session,
        user_id="u1",
        run_context=run_context,
    )

    assert result.status == RunStatus.paused
    assert result.session_state == {"watchlist": ["AAPL"]}
    assert session.session_data == {"session_state": {"watchlist": ["AAPL"]}}


@pytest.mark.asyncio
async def test_ahandle_agent_run_paused_persists_state_when_session_data_is_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_session, "save_session", lambda agent, session: None)
    monkeypatch.setattr(_run, "scrub_run_output_for_storage", lambda agent, run_response: None)
    monkeypatch.setattr(_run, "save_run_response_to_file", lambda agent, **kwargs: None)
    monkeypatch.setattr(_run, "update_session_metrics", lambda agent, session, run_response: None)

    async def noop_acreate_approval(**kwargs):
        return None

    monkeypatch.setattr(_run, "acreate_approval_from_pause", noop_acreate_approval)

    agent = Agent(name="test-hitl-async")
    session = AgentSession(session_id="s1", session_data=None)
    run_response = RunOutput(run_id="r1", session_id="s1", messages=[])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"cart": ["item-1"]})

    result = await _run.ahandle_agent_run_paused(
        agent=agent,
        run_response=run_response,
        session=session,
        user_id="u1",
        run_context=run_context,
    )

    assert result.status == RunStatus.paused
    assert result.session_state == {"cart": ["item-1"]}
    assert session.session_data == {"session_state": {"cart": ["item-1"]}}


@pytest.mark.asyncio
async def test_ahandle_agent_run_paused_persists_session_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_session, "save_session", lambda agent, session: None)
    monkeypatch.setattr(_run, "scrub_run_output_for_storage", lambda agent, run_response: None)
    monkeypatch.setattr(_run, "save_run_response_to_file", lambda agent, **kwargs: None)
    monkeypatch.setattr(_run, "update_session_metrics", lambda agent, session, run_response: None)

    async def noop_acreate_approval(**kwargs):
        return None

    monkeypatch.setattr(_run, "acreate_approval_from_pause", noop_acreate_approval)

    agent = Agent(name="test-hitl-async")
    session = AgentSession(session_id="s1", session_data={})
    run_response = RunOutput(run_id="r1", session_id="s1", messages=[])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"cart": ["item-1"]})

    result = await _run.ahandle_agent_run_paused(
        agent=agent,
        run_response=run_response,
        session=session,
        user_id="u1",
        run_context=run_context,
    )

    assert result.status == RunStatus.paused
    assert session.session_data["session_state"] == {"cart": ["item-1"]}
    assert result.session_state == {"cart": ["item-1"]}


def test_handle_agent_run_paused_stream_forwards_run_context_to_cleanup(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    def spy_cleanup_and_store(agent, run_response, session, run_context=None, user_id=None):
        captured["run_context"] = run_context

    monkeypatch.setattr(_run, "cleanup_and_store", spy_cleanup_and_store)
    monkeypatch.setattr(_run, "create_approval_from_pause", lambda **kwargs: None)

    agent = Agent(name="test-hitl-stream")
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"key": "val"})

    events = list(
        _run.handle_agent_run_paused_stream(
            agent=agent,
            run_response=RunOutput(run_id="r1", session_id="s1", messages=[]),
            session=AgentSession(session_id="s1"),
            user_id="u1",
            run_context=run_context,
        )
    )

    assert captured["run_context"] is run_context
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_ahandle_agent_run_paused_stream_forwards_run_context_to_cleanup(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def spy_acleanup_and_store(agent, run_response, session, run_context=None, user_id=None):
        captured["run_context"] = run_context

    async def noop_acreate_approval(**kwargs):
        return None

    monkeypatch.setattr(_run, "acleanup_and_store", spy_acleanup_and_store)
    monkeypatch.setattr(_run, "acreate_approval_from_pause", noop_acreate_approval)

    agent = Agent(name="test-hitl-stream-async")
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"key": "val"})

    events = []
    async for event in _run.ahandle_agent_run_paused_stream(
        agent=agent,
        run_response=RunOutput(run_id="r1", session_id="s1", messages=[]),
        session=AgentSession(session_id="s1"),
        user_id="u1",
        run_context=run_context,
    ):
        events.append(event)

    assert captured["run_context"] is run_context
    assert len(events) >= 1


def test_handle_agent_run_paused_stream_persists_session_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_session, "save_session", lambda agent, session: None)
    monkeypatch.setattr(_run, "create_approval_from_pause", lambda **kwargs: None)
    monkeypatch.setattr(_run, "scrub_run_output_for_storage", lambda agent, run_response: None)
    monkeypatch.setattr(_run, "save_run_response_to_file", lambda agent, **kwargs: None)
    monkeypatch.setattr(_run, "update_session_metrics", lambda agent, session, run_response: None)

    agent = Agent(name="test-hitl-stream")
    session = AgentSession(session_id="s1", session_data={})
    run_response = RunOutput(run_id="r1", session_id="s1", messages=[])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"watchlist": ["AAPL"]})

    events = list(
        _run.handle_agent_run_paused_stream(
            agent=agent,
            run_response=run_response,
            session=session,
            user_id="u1",
            run_context=run_context,
        )
    )

    assert len(events) >= 1
    assert session.session_data["session_state"] == {"watchlist": ["AAPL"]}
    assert run_response.session_state == {"watchlist": ["AAPL"]}


@pytest.mark.asyncio
async def test_ahandle_agent_run_paused_stream_persists_session_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_session, "save_session", lambda agent, session: None)
    monkeypatch.setattr(_run, "scrub_run_output_for_storage", lambda agent, run_response: None)
    monkeypatch.setattr(_run, "save_run_response_to_file", lambda agent, **kwargs: None)
    monkeypatch.setattr(_run, "update_session_metrics", lambda agent, session, run_response: None)

    async def noop_acreate_approval(**kwargs):
        return None

    monkeypatch.setattr(_run, "acreate_approval_from_pause", noop_acreate_approval)

    agent = Agent(name="test-hitl-stream-async")
    session = AgentSession(session_id="s1", session_data={})
    run_response = RunOutput(run_id="r1", session_id="s1", messages=[])
    run_context = RunContext(run_id="r1", session_id="s1", session_state={"cart": ["item-1"]})

    events = []
    async for event in _run.ahandle_agent_run_paused_stream(
        agent=agent,
        run_response=run_response,
        session=session,
        user_id="u1",
        run_context=run_context,
    ):
        events.append(event)

    assert len(events) >= 1
    assert session.session_data["session_state"] == {"cart": ["item-1"]}
    assert run_response.session_state == {"cart": ["item-1"]}
