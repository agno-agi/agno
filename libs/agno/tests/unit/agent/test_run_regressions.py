from typing import Any, Optional

import pytest

from agno.agent import _run
from agno.agent.agent import Agent
from agno.run import RunContext
from agno.run.agent import RunErrorEvent
from agno.run.base import RunStatus
from agno.run.cancel import (
    cancel_run,
    cleanup_run,
    get_active_runs,
    get_cancellation_manager,
    is_cancelled,
    set_cancellation_manager,
)
from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager
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
    monkeypatch.setattr(agent, "_has_async_db", lambda: False)
    monkeypatch.setattr(agent, "_update_metadata", lambda session: None)
    monkeypatch.setattr(agent, "_load_session_state", lambda session, session_state: session_state)
    monkeypatch.setattr(agent, "_resolve_run_dependencies", lambda run_context: None)
    monkeypatch.setattr(agent, "_get_response_format", lambda run_context=None: None)
    monkeypatch.setattr(
        agent,
        "_read_or_create_session",
        lambda session_id, user_id: AgentSession(session_id=session_id, user_id=user_id, runs=runs),
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
        assert cancel_run(run_id) is True

    monkeypatch.setattr(agent, "initialize_agent", initialize_and_cancel)

    observed: dict[str, bool] = {}

    def fake_run_impl(
        agent: Agent,
        run_response,
        run_context,
        session,
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

    monkeypatch.setattr(_run, "run_impl", fake_run_impl)

    _run.run_dispatch(agent=agent, input="hello", run_id=run_id, stream=False)

    assert observed["cancelled_before_model"] is True
    assert run_id not in get_active_runs()


def test_continue_run_dispatch_handles_none_session_runs(monkeypatch: pytest.MonkeyPatch):
    agent = Agent(name="test-agent")
    monkeypatch.setattr(agent, "_has_async_db", lambda: False)
    monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)
    monkeypatch.setattr(agent, "_update_metadata", lambda session: None)
    monkeypatch.setattr(agent, "_load_session_state", lambda session, session_state: session_state)
    monkeypatch.setattr(
        agent,
        "_read_or_create_session",
        lambda session_id, user_id: AgentSession(session_id=session_id, user_id=user_id, runs=None),
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
    monkeypatch.setattr(agent, "_update_metadata", lambda session: None)
    monkeypatch.setattr(agent, "_load_session_state", lambda session, session_state: session_state)

    async def fake_aread_or_create_session(session_id: str, user_id: Optional[str] = None):
        return AgentSession(session_id=session_id, user_id=user_id, runs=None)

    async def fake_acleanup_and_store(**kwargs: Any):
        return None

    async def fake_disconnect_mcp_tools():
        return None

    monkeypatch.setattr(agent, "_aread_or_create_session", fake_aread_or_create_session)
    monkeypatch.setattr(agent, "_acleanup_and_store", fake_acleanup_and_store)
    monkeypatch.setattr(agent, "_disconnect_connectable_tools", lambda: None)
    monkeypatch.setattr(agent, "_disconnect_mcp_tools", fake_disconnect_mcp_tools)

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
async def test_acontinue_run_stream_impl_yields_error_event_without_attribute_error(
    monkeypatch: pytest.MonkeyPatch,
):
    agent = Agent(name="test-agent")
    run_id = "missing-stream-run"

    async def fake_aread_or_create_session(session_id: str, user_id: Optional[str] = None):
        return AgentSession(session_id=session_id, user_id=user_id, runs=None)

    async def fake_disconnect_mcp_tools():
        return None

    monkeypatch.setattr(agent, "_aread_or_create_session", fake_aread_or_create_session)
    monkeypatch.setattr(agent, "_update_metadata", lambda session: None)
    monkeypatch.setattr(agent, "_load_session_state", lambda session, session_state: session_state)
    monkeypatch.setattr(agent, "_disconnect_connectable_tools", lambda: None)
    monkeypatch.setattr(agent, "_disconnect_mcp_tools", fake_disconnect_mcp_tools)

    run_context = RunContext(
        run_id=run_id,
        session_id="session-1",
        user_id=None,
        session_state={},
    )

    events = []
    async for event in _run.acontinue_run_stream_impl(
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
