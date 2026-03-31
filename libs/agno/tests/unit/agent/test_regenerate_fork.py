"""Unit tests for regenerate and branch_session dispatch functions."""

import asyncio
import copy
from typing import Any, List, Optional, Union, cast
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from agno.agent import _init, _messages, _response, _run, _session, _storage, _tools
from agno.agent.agent import Agent
from agno.models.message import Message
from agno.run.agent import RunInput, RunOutput
from agno.run.base import RunStatus
from agno.run.messages import RunMessages
from agno.session import AgentSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    *,
    run_id: str = "run-1",
    messages: Optional[List[Message]] = None,
    status: RunStatus = RunStatus.completed,
    input: Optional[str] = None,
) -> RunOutput:
    run = RunOutput(run_id=run_id, session_id="sess-1")
    run.messages = messages or []
    run.status = status
    if input is not None:
        run.input = RunInput(input_content=input)
    return run


def _make_session(runs: Optional[List[RunOutput]] = None, session_id: str = "sess-1") -> AgentSession:
    return AgentSession(session_id=session_id, runs=cast(Any, runs or []))


def _patch_regenerate_deps(
    agent: Agent,
    monkeypatch: pytest.MonkeyPatch,
    session: AgentSession,
) -> MagicMock:
    """Patch storage/init/tools/response so regenerate_dispatch can run without real infra."""
    monkeypatch.setattr(_init, "has_async_db", lambda a: False)
    monkeypatch.setattr(_init, "set_default_model", lambda a: None)
    monkeypatch.setattr(_storage, "update_metadata", lambda a, session=None: None)
    monkeypatch.setattr(_storage, "load_session_state", lambda a, session=None, session_state=None: session_state or {})
    monkeypatch.setattr(_storage, "read_or_create_session", lambda a, session_id=None, user_id=None: session)
    monkeypatch.setattr(_run, "resolve_run_dependencies", lambda a, run_context: None)
    monkeypatch.setattr(_response, "get_response_format", lambda a, run_context=None: None)
    monkeypatch.setattr(
        _run,
        "resolve_run_options",
        lambda a, **kw: MagicMock(
            stream=False,
            stream_events=False,
            yield_run_output=False,
            dependencies=None,
            knowledge_filters=None,
            metadata=None,
            apply_to_context=MagicMock(),
        ),
    )
    monkeypatch.setattr(agent, "get_tools", lambda **kw: [])
    monkeypatch.setattr(_tools, "determine_tools_for_model", lambda a, **kw: [])

    # Mock _continue_run to return a run output without calling a real model
    mock_continue = MagicMock()
    result_run = RunOutput(run_id="new-run", session_id="sess-1")
    result_run.content = "regenerated response"
    result_run.status = RunStatus.completed
    mock_continue.return_value = result_run
    monkeypatch.setattr(_run, "_continue_run", mock_continue)

    # Mock get_continue_run_messages
    monkeypatch.setattr(
        _messages,
        "get_continue_run_messages",
        lambda a, input=None, session=None, add_history_to_context=False, run_context=None: RunMessages(),
    )

    # Set a mock model on the agent
    mock_model = MagicMock()
    mock_model.id = "test-model"
    mock_model.provider = "test"
    agent.model = mock_model

    return mock_continue


def _patch_branch_deps(
    agent: Agent,
    monkeypatch: pytest.MonkeyPatch,
    session: AgentSession,
) -> MagicMock:
    """Patch storage/init so branch_session_dispatch can run without real infra."""
    monkeypatch.setattr(_init, "has_async_db", lambda a: False)
    monkeypatch.setattr(_storage, "read_or_create_session", lambda a, session_id=None, user_id=None: session)

    mock_save = MagicMock()
    monkeypatch.setattr(_session, "save_session", mock_save)
    return mock_save


# ---------------------------------------------------------------------------
# _strip_final_assistant_messages tests
# ---------------------------------------------------------------------------


class TestStripFinalAssistantMessages:
    def test_strips_single_trailing_assistant(self):
        msgs = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
        ]
        result = _run._strip_final_assistant_messages(msgs)
        assert len(result) == 1
        assert result[0].role == "user"

    def test_strips_multiple_trailing_assistants(self):
        msgs = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="hello"),
            Message(role="assistant", content="more"),
        ]
        result = _run._strip_final_assistant_messages(msgs)
        assert len(result) == 1

    def test_preserves_assistant_with_tool_calls(self):
        msgs = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="calling tool", tool_calls=[{"id": "1", "type": "function"}]),
            Message(role="tool", content="result"),
            Message(role="assistant", content="final answer"),
        ]
        result = _run._strip_final_assistant_messages(msgs)
        assert len(result) == 3
        assert result[-1].role == "tool"

    def test_empty_list(self):
        assert _run._strip_final_assistant_messages([]) == []

    def test_no_trailing_assistant(self):
        msgs = [
            Message(role="user", content="hi"),
        ]
        result = _run._strip_final_assistant_messages(msgs)
        assert len(result) == 1

    def test_does_not_mutate_original(self):
        msgs = [
            Message(role="user", content="hi"),
            Message(role="assistant", content="bye"),
        ]
        original_len = len(msgs)
        _run._strip_final_assistant_messages(msgs)
        assert len(msgs) == original_len


# ---------------------------------------------------------------------------
# regenerate_dispatch tests
# ---------------------------------------------------------------------------


class TestRegenerateDispatch:
    def test_regenerate_replaces_old_run_by_default(self, monkeypatch: pytest.MonkeyPatch):
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="tell me a joke"),
                Message(role="assistant", content="old joke"),
            ],
            input="tell me a joke",
        )
        session = _make_session(runs=[old_run])
        _patch_regenerate_deps(agent, monkeypatch, session)

        _run.regenerate_dispatch(agent, session_id="sess-1", stream=False)

        # Old run should have been popped (replaced)
        # Session started with 1 run, popped it, then _continue_run adds the new one
        # (in the real code, cleanup_and_store adds it; we mocked _continue_run)
        assert old_run not in (session.runs or [])

    def test_regenerate_preserves_original_when_flagged(self, monkeypatch: pytest.MonkeyPatch):
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])
        _patch_regenerate_deps(agent, monkeypatch, session)

        _run.regenerate_dispatch(agent, session_id="sess-1", preserve_original=True, stream=False)

        # Old run should still be there with regenerated status
        assert old_run.status == RunStatus.regenerated

    def test_regenerate_raises_on_empty_session(self, monkeypatch: pytest.MonkeyPatch):
        agent = Agent(name="test")
        session = _make_session(runs=[])
        _patch_regenerate_deps(agent, monkeypatch, session)

        with pytest.raises(ValueError, match="No runs found"):
            _run.regenerate_dispatch(agent, session_id="sess-1", stream=False)

    def test_regenerate_raises_on_no_messages(self, monkeypatch: pytest.MonkeyPatch):
        agent = Agent(name="test")
        empty_run = _make_run(messages=[])
        session = _make_session(runs=[empty_run])
        _patch_regenerate_deps(agent, monkeypatch, session)

        with pytest.raises(ValueError, match="no messages"):
            _run.regenerate_dispatch(agent, session_id="sess-1", stream=False)

    def test_regenerate_raises_without_session_id(self, monkeypatch: pytest.MonkeyPatch):
        agent = Agent(name="test")
        agent.session_id = None

        with pytest.raises(ValueError, match="session_id is required"):
            _run.regenerate_dispatch(agent, stream=False)

    def test_regenerate_passes_trimmed_messages_to_continue(self, monkeypatch: pytest.MonkeyPatch):
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="question"),
                Message(role="assistant", content="answer"),
            ],
            input="question",
        )
        session = _make_session(runs=[old_run])
        mock_continue = _patch_regenerate_deps(agent, monkeypatch, session)

        captured_inputs = []

        def capture_messages(a, input=None, session=None, add_history_to_context=False, run_context=None):
            captured_inputs.append(input)
            return RunMessages()

        monkeypatch.setattr(_messages, "get_continue_run_messages", capture_messages)

        _run.regenerate_dispatch(agent, session_id="sess-1", stream=False)

        # Should have passed only the user message (assistant stripped)
        assert len(captured_inputs) == 1
        assert len(captured_inputs[0]) == 1
        assert captured_inputs[0][0].role == "user"
        assert captured_inputs[0][0].content == "question"

    def test_regenerate_with_additional_instructions(self, monkeypatch: pytest.MonkeyPatch):
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="question"),
                Message(role="assistant", content="answer"),
            ],
            input="question",
        )
        session = _make_session(runs=[old_run])
        _patch_regenerate_deps(agent, monkeypatch, session)

        captured_inputs: list = []

        def capture_messages(a, input=None, session=None, add_history_to_context=False, run_context=None):
            captured_inputs.append(input)
            return RunMessages()

        monkeypatch.setattr(_messages, "get_continue_run_messages", capture_messages)

        _run.regenerate_dispatch(
            agent,
            session_id="sess-1",
            additional_instructions="Be more concise",
            stream=False,
        )

        # Should have user message + additional instructions message
        assert len(captured_inputs) == 1
        msgs = captured_inputs[0]
        assert len(msgs) == 2
        assert msgs[0].content == "question"
        assert msgs[1].content == "Be more concise"


# ---------------------------------------------------------------------------
# Regenerate session persistence tests
# ---------------------------------------------------------------------------


class TestRegenerateSessionPersistence:
    """Verify that regenerate saves session to DB before async continue re-reads it.

    The async _acontinue_run / _acontinue_run_stream functions re-read the session
    from DB.  If regenerate doesn't persist the session (with the old run removed or
    marked) *before* that re-read, the old run reappears and both runs end up stored.
    """

    def test_sync_regenerate_passes_session_with_old_run_removed(self, monkeypatch: pytest.MonkeyPatch):
        """regenerate_dispatch (sync) passes session with old run removed to _continue_run."""
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])
        _patch_regenerate_deps(agent, monkeypatch, session)

        # Capture the session object passed to _continue_run
        captured_sessions: list = []

        def capture_continue(agent_arg, run_response=None, run_messages=None, run_context=None, session=None, **kw):
            captured_sessions.append((list(session.runs) if session and session.runs else [], session))
            result = RunOutput(run_id="new-run", session_id="sess-1")
            result.content = "regenerated"
            result.status = RunStatus.completed
            return result

        monkeypatch.setattr(_run, "_continue_run", capture_continue)

        _run.regenerate_dispatch(agent, session_id="sess-1", preserve_original=False, stream=False)

        # _continue_run should receive session with old run already removed
        assert len(captured_sessions) == 1
        assert len(captured_sessions[0][0]) == 0

    def test_sync_regenerate_passes_session_with_old_run_marked_regenerated(self, monkeypatch: pytest.MonkeyPatch):
        """regenerate_dispatch (sync) passes session with old run marked as regenerated."""
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])
        _patch_regenerate_deps(agent, monkeypatch, session)

        captured_sessions: list = []

        def capture_continue(agent_arg, run_response=None, run_messages=None, run_context=None, session=None, **kw):
            if session and session.runs:
                captured_sessions.append([(r.run_id, r.status) for r in session.runs])
            result = RunOutput(run_id="new-run", session_id="sess-1")
            result.content = "regenerated"
            result.status = RunStatus.completed
            return result

        monkeypatch.setattr(_run, "_continue_run", capture_continue)

        _run.regenerate_dispatch(agent, session_id="sess-1", preserve_original=True, stream=False)

        # _continue_run should receive session with old run marked as regenerated
        assert len(captured_sessions) == 1
        assert len(captured_sessions[0]) == 1
        assert captured_sessions[0][0][1] == RunStatus.regenerated

    def test_async_regenerate_saves_session_before_continue(self, monkeypatch: pytest.MonkeyPatch):
        """aregenerate_dispatch (sync DB path) must persist session before _acontinue_run re-reads."""
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])

        # Patch deps for aregenerate_dispatch
        monkeypatch.setattr(_init, "has_async_db", lambda a: False)
        monkeypatch.setattr(_init, "set_default_model", lambda a: None)
        monkeypatch.setattr(_storage, "update_metadata", lambda a, session=None: None)
        monkeypatch.setattr(
            _storage, "load_session_state", lambda a, session=None, session_state=None: session_state or {}
        )
        monkeypatch.setattr(_storage, "read_or_create_session", lambda a, session_id=None, user_id=None: session)
        monkeypatch.setattr(_response, "get_response_format", lambda a, run_context=None: None)
        monkeypatch.setattr(
            _run,
            "resolve_run_options",
            lambda a, **kw: MagicMock(
                stream=False,
                stream_events=False,
                yield_run_output=False,
                dependencies=None,
                knowledge_filters=None,
                metadata=None,
                apply_to_context=MagicMock(),
            ),
        )

        mock_model = MagicMock()
        mock_model.id = "test-model"
        mock_model.provider = "test"
        agent.model = mock_model

        # Track the order of operations: save_session then _acontinue_run
        call_order: list = []
        saved_run_counts: list = []

        def tracking_save(agent_arg, session=None):
            call_order.append("save_session")
            saved_run_counts.append(len(session.runs) if session and session.runs else 0)

        monkeypatch.setattr(_session, "save_session", tracking_save)

        # Mock _acontinue_run as an async function
        result_run = RunOutput(run_id="new-run", session_id="sess-1")
        result_run.content = "regenerated"
        result_run.status = RunStatus.completed

        async def mock_acontinue_run(*args, **kwargs):
            call_order.append("_acontinue_run")
            return result_run

        monkeypatch.setattr(_run, "_acontinue_run", mock_acontinue_run)

        # Run the async dispatch
        result = _run.aregenerate_dispatch(agent, session_id="sess-1", preserve_original=False, stream=False)
        # aregenerate_dispatch returns a coroutine for non-streaming
        asyncio.new_event_loop().run_until_complete(result)  # type: ignore[arg-type]

        # save_session must come before _acontinue_run
        assert call_order == ["save_session", "_acontinue_run"]
        # At save time, old run should be gone
        assert saved_run_counts[0] == 0

    def test_async_regenerate_stream_saves_session_before_continue(self, monkeypatch: pytest.MonkeyPatch):
        """aregenerate_dispatch (sync DB, stream=True) must persist session before _acontinue_run_stream re-reads."""
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])

        monkeypatch.setattr(_init, "has_async_db", lambda a: False)
        monkeypatch.setattr(_init, "set_default_model", lambda a: None)
        monkeypatch.setattr(_storage, "update_metadata", lambda a, session=None: None)
        monkeypatch.setattr(
            _storage, "load_session_state", lambda a, session=None, session_state=None: session_state or {}
        )
        monkeypatch.setattr(_storage, "read_or_create_session", lambda a, session_id=None, user_id=None: session)
        monkeypatch.setattr(_response, "get_response_format", lambda a, run_context=None: None)
        monkeypatch.setattr(
            _run,
            "resolve_run_options",
            lambda a, **kw: MagicMock(
                stream=True,
                stream_events=False,
                yield_run_output=False,
                dependencies=None,
                knowledge_filters=None,
                metadata=None,
                apply_to_context=MagicMock(),
            ),
        )

        mock_model = MagicMock()
        mock_model.id = "test-model"
        mock_model.provider = "test"
        agent.model = mock_model

        call_order: list = []
        saved_run_counts: list = []

        def tracking_save(agent_arg, session=None):
            call_order.append("save_session")
            saved_run_counts.append(len(session.runs) if session and session.runs else 0)

        monkeypatch.setattr(_session, "save_session", tracking_save)

        # Mock _acontinue_run_stream as an async generator
        async def mock_acontinue_run_stream(*args, **kwargs):
            call_order.append("_acontinue_run_stream")
            yield RunOutput(run_id="new-run", session_id="sess-1")

        monkeypatch.setattr(_run, "_acontinue_run_stream", mock_acontinue_run_stream)

        # aregenerate_dispatch with stream=True returns an async iterator directly
        async_iter = _run.aregenerate_dispatch(agent, session_id="sess-1", preserve_original=False, stream=True)

        # Consume the async iterator
        async def consume():
            results = []
            async for item in async_iter:  # type: ignore[union-attr]
                results.append(item)
            return results

        asyncio.new_event_loop().run_until_complete(consume())

        # save_session must come before _acontinue_run_stream
        assert call_order == ["save_session", "_acontinue_run_stream"]
        assert saved_run_counts[0] == 0

    def test_async_regenerate_preserve_original_saves_both_statuses(self, monkeypatch: pytest.MonkeyPatch):
        """aregenerate_dispatch with preserve_original=True saves the old run as regenerated before continue."""
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])

        monkeypatch.setattr(_init, "has_async_db", lambda a: False)
        monkeypatch.setattr(_init, "set_default_model", lambda a: None)
        monkeypatch.setattr(_storage, "update_metadata", lambda a, session=None: None)
        monkeypatch.setattr(
            _storage, "load_session_state", lambda a, session=None, session_state=None: session_state or {}
        )
        monkeypatch.setattr(_storage, "read_or_create_session", lambda a, session_id=None, user_id=None: session)
        monkeypatch.setattr(_response, "get_response_format", lambda a, run_context=None: None)
        monkeypatch.setattr(
            _run,
            "resolve_run_options",
            lambda a, **kw: MagicMock(
                stream=False,
                stream_events=False,
                yield_run_output=False,
                dependencies=None,
                knowledge_filters=None,
                metadata=None,
                apply_to_context=MagicMock(),
            ),
        )

        mock_model = MagicMock()
        mock_model.id = "test-model"
        mock_model.provider = "test"
        agent.model = mock_model

        saved_statuses: list = []

        def tracking_save(agent_arg, session=None):
            if session and session.runs:
                saved_statuses.append([(r.run_id, r.status) for r in session.runs])

        monkeypatch.setattr(_session, "save_session", tracking_save)

        result_run = RunOutput(run_id="new-run", session_id="sess-1")
        result_run.content = "regenerated"
        result_run.status = RunStatus.completed

        async def mock_acontinue_run(*args, **kwargs):
            return result_run

        monkeypatch.setattr(_run, "_acontinue_run", mock_acontinue_run)

        result = _run.aregenerate_dispatch(agent, session_id="sess-1", preserve_original=True, stream=False)
        asyncio.new_event_loop().run_until_complete(result)  # type: ignore[arg-type]

        # First save should have the old run with regenerated status
        assert len(saved_statuses) >= 1
        assert len(saved_statuses[0]) == 1
        assert saved_statuses[0][0][1] == RunStatus.regenerated


# ---------------------------------------------------------------------------
# branch_session_dispatch tests
# ---------------------------------------------------------------------------


class TestBranchSessionDispatch:
    def test_branch_creates_new_session_with_copied_runs(self, monkeypatch: pytest.MonkeyPatch):
        agent = Agent(name="test")
        run1 = _make_run(run_id="r1", messages=[Message(role="user", content="hi")])
        run2 = _make_run(run_id="r2", messages=[Message(role="user", content="hello")])
        session = _make_session(runs=[run1, run2], session_id="original")
        mock_save = _patch_branch_deps(agent, monkeypatch, session)

        new_id = _run.branch_session_dispatch(agent, source_session_id="original")

        assert new_id != "original"
        mock_save.assert_called_once()
        saved_session = mock_save.call_args[1].get("session") or mock_save.call_args[0][1]
        assert saved_session.session_id == new_id
        assert len(saved_session.runs) == 2

    def test_branch_deep_copies_runs(self, monkeypatch: pytest.MonkeyPatch):
        agent = Agent(name="test")
        run1 = _make_run(run_id="r1", messages=[Message(role="user", content="hi")])
        session = _make_session(runs=[run1], session_id="original")
        mock_save = _patch_branch_deps(agent, monkeypatch, session)

        _run.branch_session_dispatch(agent, source_session_id="original")

        saved_session = mock_save.call_args[1].get("session") or mock_save.call_args[0][1]
        # Ensure it's a deep copy, not the same object
        assert saved_session.runs[0] is not run1

    def test_branch_raises_on_empty_session(self, monkeypatch: pytest.MonkeyPatch):
        agent = Agent(name="test")
        session = _make_session(runs=[], session_id="empty")
        _patch_branch_deps(agent, monkeypatch, session)

        with pytest.raises(ValueError, match="no runs to branch"):
            _run.branch_session_dispatch(agent, source_session_id="empty")

    def test_branch_raises_without_session_id(self, monkeypatch: pytest.MonkeyPatch):
        agent = Agent(name="test")
        agent.session_id = None

        with pytest.raises(ValueError, match="source_session_id is required"):
            _run.branch_session_dispatch(agent)

    def test_branch_preserves_user_id(self, monkeypatch: pytest.MonkeyPatch):
        agent = Agent(name="test")
        run1 = _make_run(run_id="r1", messages=[Message(role="user", content="hi")])
        session = _make_session(runs=[run1], session_id="original")
        session.user_id = "alice"
        mock_save = _patch_branch_deps(agent, monkeypatch, session)

        _run.branch_session_dispatch(agent, source_session_id="original", user_id="bob")

        saved_session = mock_save.call_args[1].get("session") or mock_save.call_args[0][1]
        assert saved_session.user_id == "bob"

    def test_branch_rewrites_session_id_on_copied_runs(self, monkeypatch: pytest.MonkeyPatch):
        """Branched runs must reference the new session_id, not the source."""
        agent = Agent(name="test")
        run1 = _make_run(run_id="r1", messages=[Message(role="user", content="hi")])
        run1.session_id = "original"
        run2 = _make_run(run_id="r2", messages=[Message(role="user", content="hello")])
        run2.session_id = "original"
        session = _make_session(runs=[run1, run2], session_id="original")
        mock_save = _patch_branch_deps(agent, monkeypatch, session)

        new_id = _run.branch_session_dispatch(agent, source_session_id="original")

        saved_session = mock_save.call_args[1].get("session") or mock_save.call_args[0][1]
        for run in saved_session.runs:
            assert run.session_id == new_id, f"Run {run.run_id} still has old session_id"
            assert run.run_id not in ("r1", "r2"), "Branched run must get a new run_id"
        # Source runs must be unchanged
        assert run1.session_id == "original"
        assert run1.run_id == "r1"
        assert run2.session_id == "original"
        assert run2.run_id == "r2"

    def test_branch_reads_source_session_scoped_to_caller(self, monkeypatch: pytest.MonkeyPatch):
        """Branch must read the source session scoped to the caller's user_id for access control."""
        agent = Agent(name="test")
        run1 = _make_run(run_id="r1", messages=[Message(role="user", content="hi")])
        session = _make_session(runs=[run1], session_id="original")
        session.user_id = "alice"

        monkeypatch.setattr(_init, "has_async_db", lambda a: False)

        # Track what user_id is passed to read_or_create_session
        read_calls: list = []

        def tracking_read(agent_arg, session_id=None, user_id=None):
            read_calls.append({"session_id": session_id, "user_id": user_id})
            return session

        monkeypatch.setattr(_storage, "read_or_create_session", tracking_read)
        monkeypatch.setattr(_session, "save_session", MagicMock())

        _run.branch_session_dispatch(agent, source_session_id="original", user_id="alice")

        # Source session should be read with the caller's user_id for access control
        assert len(read_calls) == 1
        assert read_calls[0]["session_id"] == "original"
        assert read_calls[0]["user_id"] == "alice"
