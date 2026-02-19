"""Tests for preserving partial content when a run is cancelled.

When a run is cancelled (via RunCancelledException or KeyboardInterrupt), any partial
content already accumulated on the run_response should be preserved rather than
overwritten with the cancellation message.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from agno.agent import _init, _managers, _messages, _response, _run, _storage, _telemetry, _tools
from agno.agent.agent import Agent
from agno.exceptions import RunCancelledException
from agno.run import RunContext
from agno.run.agent import RunInput, RunOutput
from agno.run.base import RunStatus
from agno.run.cancel import (
    get_cancellation_manager,
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


def _make_agent() -> Agent:
    return Agent(name="test-cancel-agent")


def _patch_sync_deps(agent: Agent, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch dependencies for sync _run / _run_stream functions."""
    monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
    monkeypatch.setattr(_storage, "load_session_state", lambda agent, session=None, session_state=None: session_state)
    monkeypatch.setattr(_run, "resolve_run_dependencies", lambda agent, run_context: None)
    monkeypatch.setattr(
        _run,
        "cleanup_and_store",
        lambda agent, run_response, session, run_context=None, user_id=None: None,
    )
    monkeypatch.setattr(
        _storage,
        "read_or_create_session",
        lambda agent, session_id=None, user_id=None: AgentSession(
            session_id=session_id or "test-session", user_id=user_id
        ),
    )
    monkeypatch.setattr(agent, "get_tools", lambda **kwargs: [])
    monkeypatch.setattr(_tools, "determine_tools_for_model", lambda agent, **kwargs: [])
    monkeypatch.setattr(
        _messages,
        "get_run_messages",
        lambda agent, **kwargs: RunMessages(messages=[]),
    )
    monkeypatch.setattr(_response, "handle_reasoning", lambda agent, run_response, run_messages, run_context: None)


def _patch_async_deps(agent: Agent, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch dependencies for async _arun / _arun_stream functions."""
    _patch_sync_deps(agent, monkeypatch)

    async def fake_acleanup_and_store(agent, run_response, session, run_context=None, user_id=None):
        return None

    async def fake_disconnect_mcp_tools(agent):
        return None

    async def fake_aread_or_create_session(agent, session_id=None, user_id=None):
        return AgentSession(session_id=session_id or "test-session", user_id=user_id)

    async def fake_alog_agent_telemetry(agent, session_id, run_id):
        return None

    async def fake_aget_run_messages(agent, **kwargs: Any):
        return RunMessages(messages=[])

    async def fake_astart_memory_task(agent, **kwargs: Any):
        return None

    async def fake_astart_learning_task(agent, **kwargs: Any):
        return None

    async def fake_astart_cultural_knowledge_task(agent, **kwargs: Any):
        return None

    async def fake_ahandle_reasoning(agent, run_response, run_messages, run_context):
        return None

    monkeypatch.setattr(_run, "acleanup_and_store", fake_acleanup_and_store)
    monkeypatch.setattr(_init, "disconnect_connectable_tools", lambda agent: None)
    monkeypatch.setattr(_init, "disconnect_mcp_tools", fake_disconnect_mcp_tools)
    monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
    monkeypatch.setattr(_telemetry, "alog_agent_telemetry", fake_alog_agent_telemetry)
    monkeypatch.setattr(_messages, "aget_run_messages", fake_aget_run_messages)
    monkeypatch.setattr(_managers, "astart_memory_task", fake_astart_memory_task)
    monkeypatch.setattr(_managers, "astart_learning_task", fake_astart_learning_task)
    monkeypatch.setattr(_managers, "astart_cultural_knowledge_task", fake_astart_cultural_knowledge_task)
    monkeypatch.setattr(_response, "ahandle_reasoning", fake_ahandle_reasoning)


def _make_run_response(run_id: str) -> RunOutput:
    """Create a RunOutput with proper input set."""
    run_response = RunOutput(run_id=run_id)
    run_response.input = RunInput(input_content="test input")
    return run_response


def _make_model_that_cancels(run_response: RunOutput, partial_content: str) -> MagicMock:
    """Create a mock model whose response()/aresponse() sets partial content, then raises RunCancelledException."""

    def fake_response(**kwargs: Any):
        # Simulate partial content accumulated before cancellation
        run_response.content = partial_content
        raise RunCancelledException("Run was cancelled")

    async def fake_aresponse(**kwargs: Any):
        run_response.content = partial_content
        raise RunCancelledException("Run was cancelled")

    mock_model = MagicMock()
    mock_model.response = fake_response
    mock_model.aresponse = fake_aresponse
    mock_model.provider = "test"
    return mock_model


def _make_model_that_keyboard_interrupts(run_response: RunOutput, partial_content: str) -> MagicMock:
    """Create a mock model whose response()/aresponse() sets partial content, then raises KeyboardInterrupt."""

    def fake_response(**kwargs: Any):
        run_response.content = partial_content
        raise KeyboardInterrupt()

    async def fake_aresponse(**kwargs: Any):
        run_response.content = partial_content
        raise KeyboardInterrupt()

    mock_model = MagicMock()
    mock_model.response = fake_response
    mock_model.aresponse = fake_aresponse
    mock_model.provider = "test"
    return mock_model


# ---------------------------------------------------------------------------
# Test: sync non-streaming _run preserves partial content on RunCancelledException
# ---------------------------------------------------------------------------
def test_sync_run_preserves_partial_content_on_cancellation(monkeypatch: pytest.MonkeyPatch):
    agent = _make_agent()
    _patch_sync_deps(agent, monkeypatch)

    run_id = "sync-run-cancel"
    run_response = _make_run_response(run_id)
    run_context = RunContext(run_id=run_id, session_id="s1", session_state={})

    agent.model = _make_model_that_cancels(run_response, "This is partial content")

    result = _run._run(
        agent=agent,
        run_response=run_response,
        run_context=run_context,
        session_id="s1",
    )

    assert result.status == RunStatus.cancelled
    assert result.content == "This is partial content"


# ---------------------------------------------------------------------------
# Test: sync non-streaming _run uses cancellation message when no partial content
# ---------------------------------------------------------------------------
def test_sync_run_uses_cancel_message_when_no_partial_content(monkeypatch: pytest.MonkeyPatch):
    agent = _make_agent()
    _patch_sync_deps(agent, monkeypatch)

    run_id = "sync-run-cancel-no-content"
    run_response = _make_run_response(run_id)
    run_context = RunContext(run_id=run_id, session_id="s1", session_state={})

    def fake_response(**kwargs: Any):
        raise RunCancelledException("Run was cancelled")

    mock_model = MagicMock()
    mock_model.response = fake_response
    mock_model.provider = "test"
    agent.model = mock_model

    result = _run._run(
        agent=agent,
        run_response=run_response,
        run_context=run_context,
        session_id="s1",
    )

    assert result.status == RunStatus.cancelled
    assert result.content == "Run was cancelled"


# ---------------------------------------------------------------------------
# Test: sync non-streaming _run preserves partial content on KeyboardInterrupt
# ---------------------------------------------------------------------------
def test_sync_run_preserves_partial_content_on_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch):
    agent = _make_agent()
    _patch_sync_deps(agent, monkeypatch)

    run_id = "sync-run-keyboard"
    run_response = _make_run_response(run_id)
    run_context = RunContext(run_id=run_id, session_id="s1", session_state={})

    agent.model = _make_model_that_keyboard_interrupts(run_response, "Partial content before Ctrl+C")

    result = _run._run(
        agent=agent,
        run_response=run_response,
        run_context=run_context,
        session_id="s1",
    )

    assert result.status == RunStatus.cancelled
    assert result.content == "Partial content before Ctrl+C"


# ---------------------------------------------------------------------------
# Test: KeyboardInterrupt uses default message when no partial content
# ---------------------------------------------------------------------------
def test_sync_run_uses_default_message_on_keyboard_interrupt_without_content(monkeypatch: pytest.MonkeyPatch):
    agent = _make_agent()
    _patch_sync_deps(agent, monkeypatch)

    run_id = "sync-run-keyboard-no-content"
    run_response = _make_run_response(run_id)
    run_context = RunContext(run_id=run_id, session_id="s1", session_state={})

    def fake_response(**kwargs: Any):
        raise KeyboardInterrupt()

    mock_model = MagicMock()
    mock_model.response = fake_response
    mock_model.provider = "test"
    agent.model = mock_model

    result = _run._run(
        agent=agent,
        run_response=run_response,
        run_context=run_context,
        session_id="s1",
    )

    assert result.status == RunStatus.cancelled
    assert result.content == "Operation cancelled by user"


# ---------------------------------------------------------------------------
# Test: sync streaming _run_stream preserves partial content on RunCancelledException
# ---------------------------------------------------------------------------
def test_sync_stream_preserves_partial_content_on_cancellation(monkeypatch: pytest.MonkeyPatch):
    agent = _make_agent()
    _patch_sync_deps(agent, monkeypatch)

    run_id = "sync-stream-cancel"
    run_response = _make_run_response(run_id)
    run_context = RunContext(run_id=run_id, session_id="s1", session_state={})

    def fake_response_stream(**kwargs: Any):
        run_response.content = "Partial streamed content"
        raise RunCancelledException("Run was cancelled during streaming")

    mock_model = MagicMock()
    mock_model.response_stream = fake_response_stream
    mock_model.provider = "test"
    agent.model = mock_model

    events = list(
        _run._run_stream(
            agent=agent,
            run_response=run_response,
            run_context=run_context,
            session_id="s1",
            stream_events=True,
        )
    )

    assert run_response.status == RunStatus.cancelled
    assert run_response.content == "Partial streamed content"
    assert len(events) >= 1


# ---------------------------------------------------------------------------
# Test: async non-streaming _arun preserves partial content on RunCancelledException
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_async_run_preserves_partial_content_on_cancellation(monkeypatch: pytest.MonkeyPatch):
    agent = _make_agent()
    _patch_async_deps(agent, monkeypatch)

    run_id = "async-run-cancel"
    run_response = _make_run_response(run_id)
    run_context = RunContext(run_id=run_id, session_id="s1", session_state={})

    agent.model = _make_model_that_cancels(run_response, "Async partial content")

    result = await _run._arun(
        agent=agent,
        run_response=run_response,
        run_context=run_context,
        session_id="s1",
    )

    assert result.status == RunStatus.cancelled
    assert result.content == "Async partial content"


# ---------------------------------------------------------------------------
# Test: async non-streaming _arun preserves partial content on KeyboardInterrupt
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_async_run_preserves_partial_content_on_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch):
    agent = _make_agent()
    _patch_async_deps(agent, monkeypatch)

    run_id = "async-run-keyboard"
    run_response = _make_run_response(run_id)
    run_context = RunContext(run_id=run_id, session_id="s1", session_state={})

    agent.model = _make_model_that_keyboard_interrupts(run_response, "Async partial before Ctrl+C")

    result = await _run._arun(
        agent=agent,
        run_response=run_response,
        run_context=run_context,
        session_id="s1",
    )

    assert result.status == RunStatus.cancelled
    assert result.content == "Async partial before Ctrl+C"


# ---------------------------------------------------------------------------
# Test: cancelled run stores partial content to session (cleanup_and_store called)
# ---------------------------------------------------------------------------
def test_cancelled_run_stores_partial_content_to_session(monkeypatch: pytest.MonkeyPatch):
    agent = _make_agent()
    _patch_sync_deps(agent, monkeypatch)

    stored_responses: list[RunOutput] = []

    def spy_cleanup_and_store(agent, run_response, session, run_context=None, user_id=None):
        stored_responses.append(run_response)

    monkeypatch.setattr(_run, "cleanup_and_store", spy_cleanup_and_store)

    run_id = "sync-run-store-partial"
    run_response = _make_run_response(run_id)
    run_context = RunContext(run_id=run_id, session_id="s1", session_state={})

    agent.model = _make_model_that_cancels(run_response, "Stored partial content")

    _run._run(
        agent=agent,
        run_response=run_response,
        run_context=run_context,
        session_id="s1",
    )

    assert len(stored_responses) == 1
    assert stored_responses[0].content == "Stored partial content"
    assert stored_responses[0].status == RunStatus.cancelled
