"""Unit tests for regenerate and branch_session dispatch functions."""

import asyncio
from typing import Any, List, Optional, cast
from unittest.mock import MagicMock

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

    def test_regenerate_sets_regenerated_from_on_new_run(self, monkeypatch: pytest.MonkeyPatch):
        """The new run should record the predecessor run_id it was regenerated from."""
        agent = Agent(name="test")
        old_run = _make_run(
            run_id="run-original",
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])
        _patch_regenerate_deps(agent, monkeypatch, session)

        captured: list = []

        def capture_continue(agent_arg, run_response=None, **kw):
            captured.append(run_response)
            return run_response

        monkeypatch.setattr(_run, "_continue_run", capture_continue)

        _run.regenerate_dispatch(agent, session_id="sess-1", stream=False)

        assert len(captured) == 1
        assert captured[0].regenerated_from == "run-original"
        assert captured[0].run_id != "run-original"

    def test_regenerate_chains_regenerated_from_immediate_predecessor(self, monkeypatch: pytest.MonkeyPatch):
        """When regenerating a preserved-original run, lineage points at the immediate predecessor."""
        agent = Agent(name="test")
        # Simulate a run that itself came from a prior regenerate (run-A -> run-B)
        run_b = _make_run(
            run_id="run-B",
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="second answer"),
            ],
            input="hi",
        )
        run_b.regenerated_from = "run-A"
        session = _make_session(runs=[run_b])
        _patch_regenerate_deps(agent, monkeypatch, session)

        captured: list = []

        def capture_continue(agent_arg, run_response=None, **kw):
            captured.append(run_response)
            return run_response

        monkeypatch.setattr(_run, "_continue_run", capture_continue)

        _run.regenerate_dispatch(agent, session_id="sess-1", preserve_original=True, stream=False)

        # Immediate predecessor is run-B, not the grand-predecessor run-A
        assert captured[0].regenerated_from == "run-B"

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

    def test_regenerate_raises_on_assistant_only_messages(self, monkeypatch: pytest.MonkeyPatch):
        """If stripping leaves no messages (assistant-only run), raise a clear error."""
        agent = Agent(name="test")
        assistant_only_run = _make_run(
            messages=[
                Message(role="assistant", content="hi"),
                Message(role="assistant", content="there"),
            ]
        )
        session = _make_session(runs=[assistant_only_run])
        _patch_regenerate_deps(agent, monkeypatch, session)

        with pytest.raises(ValueError, match="no user messages"):
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
        _patch_regenerate_deps(agent, monkeypatch, session)

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

    def test_async_regenerate_passes_pre_session_with_old_run_removed(self, monkeypatch: pytest.MonkeyPatch):
        """aregenerate_dispatch must NOT save before _acontinue_run; instead it hands the
        mutated session in via pre_session so a model crash leaves the DB untouched."""
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])

        monkeypatch.setattr(_init, "set_default_model", lambda a: None)
        monkeypatch.setattr(_storage, "update_metadata", lambda a, session=None: None)
        monkeypatch.setattr(
            _storage, "load_session_state", lambda a, session=None, session_state=None: session_state or {}
        )

        async def mock_aread(a, session_id=None, user_id=None):
            return session

        monkeypatch.setattr(_storage, "aread_or_create_session", mock_aread)
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

        # Track that asave_session is NOT called by the prep code path
        save_call_count = 0

        async def tracking_save(agent_arg, session=None):
            nonlocal save_call_count
            save_call_count += 1

        monkeypatch.setattr(_session, "asave_session", tracking_save)

        captured_kwargs: list = []
        result_run = RunOutput(run_id="new-run", session_id="sess-1")
        result_run.content = "regenerated"
        result_run.status = RunStatus.completed

        async def mock_acontinue_run(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return result_run

        monkeypatch.setattr(_run, "_acontinue_run", mock_acontinue_run)

        result = _run.aregenerate_dispatch(agent, session_id="sess-1", preserve_original=False, stream=False)
        asyncio.new_event_loop().run_until_complete(result)  # type: ignore[arg-type]

        # Critical safety property: no save before model
        assert save_call_count == 0
        # _acontinue_run was handed the mutated in-memory session. Its presence is the
        # single signal that the regenerate-mode contract applies (skip DB re-read,
        # skip duplicate dep resolution, skip persist on error).
        assert len(captured_kwargs) == 1
        prepared = captured_kwargs[0].get("pre_session")
        assert prepared is session
        assert len(prepared.runs) == 0  # old run popped in-memory

    def test_async_regenerate_stream_passes_pre_session_with_old_run_removed(self, monkeypatch: pytest.MonkeyPatch):
        """aregenerate_dispatch (stream=True) must hand the mutated session via
        pre_session and skip the early DB save, so a crash mid-stream leaves
        the original run intact in the DB."""
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])

        monkeypatch.setattr(_init, "set_default_model", lambda a: None)
        monkeypatch.setattr(_storage, "update_metadata", lambda a, session=None: None)
        monkeypatch.setattr(
            _storage, "load_session_state", lambda a, session=None, session_state=None: session_state or {}
        )

        async def mock_aread(a, session_id=None, user_id=None):
            return session

        monkeypatch.setattr(_storage, "aread_or_create_session", mock_aread)
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

        save_call_count = 0

        async def tracking_save(agent_arg, session=None):
            nonlocal save_call_count
            save_call_count += 1

        monkeypatch.setattr(_session, "asave_session", tracking_save)

        captured_kwargs: list = []

        async def mock_acontinue_run_stream(*args, **kwargs):
            captured_kwargs.append(kwargs)
            yield RunOutput(run_id="new-run", session_id="sess-1")

        monkeypatch.setattr(_run, "_acontinue_run_stream", mock_acontinue_run_stream)

        async_iter = _run.aregenerate_dispatch(agent, session_id="sess-1", preserve_original=False, stream=True)

        async def consume():
            results = []
            async for item in async_iter:  # type: ignore[union-attr]
                results.append(item)
            return results

        asyncio.new_event_loop().run_until_complete(consume())

        assert save_call_count == 0
        assert len(captured_kwargs) == 1
        prepared = captured_kwargs[0].get("pre_session")
        assert prepared is session
        assert len(prepared.runs) == 0

    def test_async_regenerate_preserve_original_marks_status_in_pre_session(self, monkeypatch: pytest.MonkeyPatch):
        """aregenerate_dispatch with preserve_original=True marks the old run as regenerated
        in the in-memory session and hands it to _acontinue_run via pre_session."""
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])

        monkeypatch.setattr(_init, "set_default_model", lambda a: None)
        monkeypatch.setattr(_storage, "update_metadata", lambda a, session=None: None)
        monkeypatch.setattr(
            _storage, "load_session_state", lambda a, session=None, session_state=None: session_state or {}
        )

        async def mock_aread(a, session_id=None, user_id=None):
            return session

        monkeypatch.setattr(_storage, "aread_or_create_session", mock_aread)
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

        save_call_count = 0

        async def tracking_save(agent_arg, session=None):
            nonlocal save_call_count
            save_call_count += 1

        monkeypatch.setattr(_session, "asave_session", tracking_save)

        captured_kwargs: list = []
        result_run = RunOutput(run_id="new-run", session_id="sess-1")
        result_run.content = "regenerated"
        result_run.status = RunStatus.completed

        async def mock_acontinue_run(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return result_run

        monkeypatch.setattr(_run, "_acontinue_run", mock_acontinue_run)

        result = _run.aregenerate_dispatch(agent, session_id="sess-1", preserve_original=True, stream=False)
        asyncio.new_event_loop().run_until_complete(result)  # type: ignore[arg-type]

        # No early save happens any more
        assert save_call_count == 0
        # The prepared session has the old run marked as regenerated
        assert len(captured_kwargs) == 1
        prepared = captured_kwargs[0].get("pre_session")
        assert prepared is session
        assert len(prepared.runs) == 1
        assert prepared.runs[0].status == RunStatus.regenerated


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
        # branched_from should be recorded in session_data
        assert saved_session.session_data["branched_from"] == "original"

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

    def test_branch_records_branched_from_on_each_run(self, monkeypatch: pytest.MonkeyPatch):
        """Every branched run must carry branched_from pointing at the source session."""
        agent = Agent(name="test")
        run1 = _make_run(run_id="r1", messages=[Message(role="user", content="hi")])
        run2 = _make_run(run_id="r2", messages=[Message(role="user", content="hello")])
        session = _make_session(runs=[run1, run2], session_id="original")
        mock_save = _patch_branch_deps(agent, monkeypatch, session)

        _run.branch_session_dispatch(agent, source_session_id="original")

        saved_session = mock_save.call_args[1].get("session") or mock_save.call_args[0][1]
        for run in saved_session.runs:
            assert run.branched_from == "original"

    def test_branch_source_runs_not_mutated(self, monkeypatch: pytest.MonkeyPatch):
        """The source session's runs must not gain a branched_from field from the branch op."""
        agent = Agent(name="test")
        run1 = _make_run(run_id="r1", messages=[Message(role="user", content="hi")])
        assert run1.branched_from is None
        session = _make_session(runs=[run1], session_id="original")
        _patch_branch_deps(agent, monkeypatch, session)

        _run.branch_session_dispatch(agent, source_session_id="original")

        # Source run must remain untouched
        assert run1.branched_from is None
        assert run1.run_id == "r1"
        assert run1.session_id == "sess-1"

    def test_nested_branch_preserves_original_branched_from(self, monkeypatch: pytest.MonkeyPatch):
        """When branching a session whose runs already carry branched_from, preserve it."""
        agent = Agent(name="test")
        run1 = _make_run(run_id="r1", messages=[Message(role="user", content="hi")])
        run1.branched_from = "the-original"  # already branched once
        session = _make_session(runs=[run1], session_id="intermediate")
        mock_save = _patch_branch_deps(agent, monkeypatch, session)

        _run.branch_session_dispatch(agent, source_session_id="intermediate")

        saved_session = mock_save.call_args[1].get("session") or mock_save.call_args[0][1]
        # Nested branch must preserve the original branched_from, not overwrite it
        assert saved_session.runs[0].branched_from == "the-original"
        # But session-level branched_from points at the immediate parent
        assert saved_session.session_data["branched_from"] == "intermediate"

    def test_branch_branched_from_survives_to_dict_roundtrip(self, monkeypatch: pytest.MonkeyPatch):
        """branched_from must serialize via to_dict/from_dict."""
        run = _make_run(run_id="r1", messages=[Message(role="user", content="hi")])
        run.branched_from = "source-sess"

        d = run.to_dict()
        assert d.get("branched_from") == "source-sess"

        restored = RunOutput.from_dict(d)
        assert restored.branched_from == "source-sess"


# ---------------------------------------------------------------------------
# pre_session forwarding tests
# ---------------------------------------------------------------------------


class TestRegeneratePreSessionForwarding:
    def test_sync_regenerate_forwards_pre_session_to_continue_run(self, monkeypatch: pytest.MonkeyPatch):
        """Sync regenerate must pass pre_session=session to _continue_run."""
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])
        mock_continue = _patch_regenerate_deps(agent, monkeypatch, session)

        _run.regenerate_dispatch(agent, session_id="sess-1", stream=False)

        kwargs = mock_continue.call_args.kwargs
        assert kwargs.get("pre_session") is session

    def test_sync_regenerate_stream_forwards_pre_session_to_continue_run_stream(self, monkeypatch: pytest.MonkeyPatch):
        """Sync streaming regenerate must pass pre_session=session to _continue_run_stream."""
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

        # Switch resolved options to streaming and capture the streaming continue call.
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
        captured_kwargs: list = []

        def mock_continue_stream(*args, **kwargs):
            captured_kwargs.append(kwargs)
            yield RunOutput(run_id="new-run", session_id="sess-1")

        monkeypatch.setattr(_run, "_continue_run_stream", mock_continue_stream)

        list(_run.regenerate_dispatch(agent, session_id="sess-1", stream=True))  # type: ignore[arg-type]

        assert len(captured_kwargs) == 1
        assert captured_kwargs[0].get("pre_session") is session

    def test_async_regenerate_forwards_pre_session_to_acontinue_run(self, monkeypatch: pytest.MonkeyPatch):
        """Async regenerate must pass pre_session=session to _acontinue_run."""
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])

        monkeypatch.setattr(_init, "set_default_model", lambda a: None)
        monkeypatch.setattr(_storage, "update_metadata", lambda a, session=None: None)
        monkeypatch.setattr(
            _storage, "load_session_state", lambda a, session=None, session_state=None: session_state or {}
        )

        async def mock_aread(agent_arg, session_id=None, user_id=None):
            return session

        monkeypatch.setattr(_storage, "aread_or_create_session", mock_aread)
        monkeypatch.setattr(_run, "aresolve_run_dependencies", lambda a, run_context: None)
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

        captured_kwargs: list = []
        result_run = RunOutput(run_id="new-run", session_id="sess-1")
        result_run.content = "regenerated"
        result_run.status = RunStatus.completed

        async def mock_acontinue_run(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return result_run

        monkeypatch.setattr(_run, "_acontinue_run", mock_acontinue_run)

        result = _run.aregenerate_dispatch(agent, session_id="sess-1", preserve_original=False, stream=False)
        asyncio.new_event_loop().run_until_complete(result)  # type: ignore[arg-type]

        assert len(captured_kwargs) == 1
        prepared = captured_kwargs[0].get("pre_session")
        assert prepared is session
        assert len(prepared.runs) == 0  # popped in-memory

    def test_async_regenerate_stream_forwards_pre_session_to_acontinue_run_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Async streaming regenerate must pass pre_session=session to _acontinue_run_stream."""
        agent = Agent(name="test")
        old_run = _make_run(
            messages=[
                Message(role="user", content="hi"),
                Message(role="assistant", content="hello"),
            ],
            input="hi",
        )
        session = _make_session(runs=[old_run])

        monkeypatch.setattr(_init, "set_default_model", lambda a: None)
        monkeypatch.setattr(_storage, "update_metadata", lambda a, session=None: None)
        monkeypatch.setattr(
            _storage, "load_session_state", lambda a, session=None, session_state=None: session_state or {}
        )

        async def mock_aread(agent_arg, session_id=None, user_id=None):
            return session

        monkeypatch.setattr(_storage, "aread_or_create_session", mock_aread)
        monkeypatch.setattr(_run, "aresolve_run_dependencies", lambda a, run_context: None)
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

        captured_kwargs: list = []

        async def mock_acontinue_run_stream(*args, **kwargs):
            captured_kwargs.append(kwargs)
            yield RunOutput(run_id="new-run", session_id="sess-1")

        monkeypatch.setattr(_run, "_acontinue_run_stream", mock_acontinue_run_stream)

        async_iter = _run.aregenerate_dispatch(agent, session_id="sess-1", preserve_original=False, stream=True)

        async def consume():
            async for _ in async_iter:  # type: ignore[union-attr]
                pass

        asyncio.new_event_loop().run_until_complete(consume())

        assert len(captured_kwargs) == 1
        prepared = captured_kwargs[0].get("pre_session")
        assert prepared is session
        assert len(prepared.runs) == 0


class TestAcontinueRunRetryReusesPreSession:
    def test_acontinue_run_skips_db_reread_on_retry_when_pre_session_set(self, monkeypatch: pytest.MonkeyPatch):
        """On retry, _acontinue_run must reuse pre_session instead of re-reading from DB."""
        from agno.run import RunContext

        agent = Agent(name="test")
        agent.retries = 1
        agent.delay_between_retries = 0
        agent.exponential_backoff = False
        mock_model = MagicMock()
        mock_model.id = "test-model"
        mock_model.provider = "test"
        agent.model = mock_model

        prepared = _make_session(runs=[])  # popped already by prep

        aread_calls = {"n": 0}

        async def mock_aread(agent_arg, session_id=None, user_id=None):
            aread_calls["n"] += 1
            return _make_session(runs=[_make_run(run_id="db-run")])

        monkeypatch.setattr(_storage, "aread_or_create_session", mock_aread)
        monkeypatch.setattr(_storage, "update_metadata", lambda a, session=None: None)
        monkeypatch.setattr(
            _storage, "load_session_state", lambda a, session=None, session_state=None: session_state or {}
        )

        # Stub everything past the read so the loop body throws on the first attempt
        # and succeeds on the second. We only care that aread is never called.
        attempts = {"n": 0}

        async def fake_call_model(*a, **k):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("transient")
            # On second attempt return early — model_response object isn't critical;
            # we'll short-circuit further by patching downstream helpers to no-ops.
            return MagicMock()

        # Patch out internals so _acontinue_run progresses without doing real work.
        monkeypatch.setattr(_run, "acall_model_with_fallback", fake_call_model, raising=False)
        monkeypatch.setattr(_run, "araise_if_cancelled", lambda *a, **k: asyncio.sleep(0), raising=False)

        # Run _acontinue_run with pre_session=prepared. The first attempt raises,
        # the second succeeds — and aread_or_create_session must be called zero times.
        run_response = RunOutput(run_id="new-run", session_id="sess-1")
        run_context = RunContext(run_id="new-run", session_id="sess-1", user_id=None, session_state={})

        # Drive the retry loop directly; we don't need the full success path,
        # only that no DB read happens for either attempt.
        try:
            asyncio.new_event_loop().run_until_complete(
                _run._acontinue_run(
                    agent,
                    run_response=run_response,
                    run_context=run_context,
                    session_id="sess-1",
                    pre_session=prepared,
                )
            )
        except Exception:
            # The stubs are intentionally minimal — we let _acontinue_run bail out
            # however it likes, as long as it never reads from DB.
            pass

        assert aread_calls["n"] == 0, (
            f"_acontinue_run re-read DB {aread_calls['n']} times across retries; "
            "pre_session must be sticky across all attempts."
        )
