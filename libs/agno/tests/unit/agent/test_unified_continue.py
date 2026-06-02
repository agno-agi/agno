"""Unit tests for the unified ``/continue`` dispatch (phase 3 of run-checkpointing).

Scope covers the ADR-003 / ADR-004 reframing of ``continue_run_dispatch``:
- Drop the PAUSED-only 409 gate. Any persisted run can be advanced via /continue
  given a sensible body.
- A run with NO unresolved HITL requirements + empty body resumes from its
  current persisted state (INTERRUPTED resume, ERROR retry, time-travel).
- A run WITH unresolved requirements + empty body still requires
  ``requirements`` (or a resolved admin approval) — HITL contract unchanged.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import pytest

# Set test API key to avoid env-var lookup errors when constructing OpenAI models.
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.agent import _init, _response, _run, _storage, _tools
from agno.agent._run import _fork_run, _truncate_run_to_checkpoint
from agno.agent.agent import Agent
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.session import AgentSession

# ---------------------------------------------------------------------------
# Helpers (mirror the pattern from test_run_regressions.py)
# ---------------------------------------------------------------------------


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
    monkeypatch.setattr(_tools, "determine_tools_for_model", lambda *a, **kw: [])
    monkeypatch.setattr(
        _storage,
        "read_or_create_session",
        lambda agent, session_id=None, user_id=None: AgentSession(session_id=session_id, user_id=user_id, runs=runs),
    )


def _make_agent(monkeypatch: pytest.MonkeyPatch, runs: Optional[list[Any]] = None) -> Agent:
    agent = Agent(name="test-agent")
    _patch_sync_dispatch_dependencies(agent, monkeypatch, runs=runs)
    monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)
    return agent


# ---------------------------------------------------------------------------
# Unified /continue — empty body is OK when there are no unresolved requirements
# ---------------------------------------------------------------------------


class TestEmptyBodyResume:
    """Pre-ADR-003, /continue required tools or requirements in the body for
    any run with persisted tools. Now empty body is fine when no requirements
    are unresolved — supports INTERRUPTED resume, ERROR retry, time-travel."""

    def test_resume_interrupted_run_with_empty_body(self, monkeypatch: pytest.MonkeyPatch):
        """An INTERRUPTED run (persisted as RUNNING by checkpoint, no unresolved
        requirements) can be /continue'd with no tools / requirements / input."""
        # A run that was mid-flight: had some tool executions, no HITL pending.
        completed_tool = ToolExecution(tool_call_id="tc-1", tool_name="searcher", tool_args={}, result="ok")
        interrupted_run = RunOutput(
            run_id="run-int",
            session_id="session-1",
            status=RunStatus.running,  # persisted by checkpoint_run mid-execution
            tools=[completed_tool],
            requirements=None,  # no HITL requirements
            messages=[],
            last_checkpoint_at_message_index=4,
        )
        agent = _make_agent(monkeypatch, runs=[interrupted_run])

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["run_response"] = run_response
            captured["reached_continue_run"] = True
            run_response.status = RunStatus.completed
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        # Empty body — no updated_tools, no requirements
        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-int",
            session_id="session-1",
            stream=False,
        )

        assert captured.get("reached_continue_run") is True, (
            "_continue_run should be invoked for an INTERRUPTED-style run with empty body"
        )
        # The loaded run state passes through unchanged
        assert captured["run_response"].tools == [completed_tool]

    def test_resume_error_run_with_empty_body(self, monkeypatch: pytest.MonkeyPatch):
        """An ERROR run with no unresolved requirements can be retried with empty body."""
        errored_run = RunOutput(
            run_id="run-err",
            session_id="session-1",
            status=RunStatus.error,
            tools=[],
            requirements=None,
            messages=[],
        )
        agent = _make_agent(monkeypatch, runs=[errored_run])

        called = {"continue_run": False}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            called["continue_run"] = True
            run_response.status = RunStatus.completed
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-err",
            session_id="session-1",
            stream=False,
        )

        assert called["continue_run"] is True

    def test_resume_completed_run_with_empty_body(self, monkeypatch: pytest.MonkeyPatch):
        """A COMPLETED run with no unresolved requirements can be advanced
        with empty body (degenerate but valid — caller may want to retry)."""
        completed_run = RunOutput(
            run_id="run-done",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[],
            requirements=None,
            messages=[],
        )
        agent = _make_agent(monkeypatch, runs=[completed_run])

        called = {"continue_run": False}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            called["continue_run"] = True
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-done",
            session_id="session-1",
            stream=False,
        )

        assert called["continue_run"] is True

    def test_resume_run_with_completed_tools_no_requirements(self, monkeypatch: pytest.MonkeyPatch):
        """A run that completed several tool batches but has no pending HITL
        (no requirements) resumes with empty body — common INTERRUPTED case."""
        run_with_tools = RunOutput(
            run_id="run-tools",
            session_id="session-1",
            status=RunStatus.running,
            tools=[
                ToolExecution(tool_call_id="t1", tool_name="x", tool_args={}, result="r1"),
                ToolExecution(tool_call_id="t2", tool_name="y", tool_args={}, result="r2"),
            ],
            requirements=None,
            messages=[],
        )
        agent = _make_agent(monkeypatch, runs=[run_with_tools])

        called = {"continue_run": False}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            called["continue_run"] = True
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        # Empty body
        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-tools",
            session_id="session-1",
            stream=False,
        )

        assert called["continue_run"] is True


# ---------------------------------------------------------------------------
# HITL contract preserved
# ---------------------------------------------------------------------------


class TestHitlContractPreserved:
    """Runs WITH unresolved requirements still require tools/requirements/approval —
    the unified dispatch did not weaken HITL safety."""

    def test_unresolved_requirements_without_body_raises(self, monkeypatch: pytest.MonkeyPatch):
        """A PAUSED run with an unresolved requirement + empty body + no admin
        approval still raises — caller MUST provide tools/requirements or a
        resolved approval. (Same contract as before; just rephrased error.)"""
        pending_tool = ToolExecution(
            tool_call_id="tc-pending",
            tool_name="needs_input",
            tool_args={},
            requires_user_input=True,
        )
        pending_requirement = RunRequirement(tool_execution=pending_tool)  # is_resolved() → False
        paused_run = RunOutput(
            run_id="run-pause",
            session_id="session-1",
            status=RunStatus.paused,
            tools=[pending_tool],
            requirements=[pending_requirement],
            messages=[],
        )
        agent = _make_agent(monkeypatch, runs=[paused_run])

        # Patch the admin-approval check to simulate "no resolved approval"
        from agno.run import approval as approval_mod

        def raising_approval(db, run_id, run_response):
            raise RuntimeError("no resolved approval")

        monkeypatch.setattr(approval_mod, "check_and_apply_approval_resolution", raising_approval)

        with pytest.raises(ValueError, match="unresolved HITL requirements"):
            _run.continue_run_dispatch(
                agent=agent,
                run_id="run-pause",
                session_id="session-1",
                stream=False,
            )

    def test_resolved_admin_approval_allows_resume(self, monkeypatch: pytest.MonkeyPatch):
        """A PAUSED run with an unresolved requirement, but a resolved admin
        approval in the DB, resumes successfully with empty body — the approval
        check applies resolution and the loop proceeds."""
        pending_tool = ToolExecution(
            tool_call_id="tc-pending",
            tool_name="admin_action",
            tool_args={},
            requires_confirmation=True,
        )
        pending_requirement = RunRequirement(tool_execution=pending_tool)
        paused_run = RunOutput(
            run_id="run-approved",
            session_id="session-1",
            status=RunStatus.paused,
            tools=[pending_tool],
            requirements=[pending_requirement],
            messages=[],
        )
        agent = _make_agent(monkeypatch, runs=[paused_run])

        # Patch the approval check to "succeed" (no-op) — admin approval was resolved.
        from agno.run import approval as approval_mod

        approval_calls = {"called": False}

        def successful_approval(db, run_id, run_response):
            approval_calls["called"] = True
            # Real implementation would mutate run_response.tools to apply the resolution.

        monkeypatch.setattr(approval_mod, "check_and_apply_approval_resolution", successful_approval)

        called = {"continue_run": False}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            called["continue_run"] = True
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-approved",
            session_id="session-1",
            stream=False,
        )

        assert approval_calls["called"] is True
        assert called["continue_run"] is True

    def test_resolved_requirement_with_no_body_still_resumes(self, monkeypatch: pytest.MonkeyPatch):
        """A run where all requirements are already resolved (rare but valid)
        should resume with empty body — no need to re-fetch admin approval."""
        resolved_tool = ToolExecution(
            tool_call_id="tc-done",
            tool_name="done_action",
            tool_args={},
            result="completed",  # has result → is_resolved() = True
        )
        resolved_requirement = RunRequirement(tool_execution=resolved_tool)
        # Sanity check — confirm our test assumption that this requirement is resolved
        assert resolved_requirement.is_resolved() is True

        run = RunOutput(
            run_id="run-resolved",
            session_id="session-1",
            status=RunStatus.paused,
            tools=[resolved_tool],
            requirements=[resolved_requirement],
            messages=[],
        )
        agent = _make_agent(monkeypatch, runs=[run])

        # Approval check should NOT be invoked — no unresolved requirements
        from agno.run import approval as approval_mod

        approval_calls = {"called": False}

        def tracking_approval(db, run_id, run_response):
            approval_calls["called"] = True

        monkeypatch.setattr(approval_mod, "check_and_apply_approval_resolution", tracking_approval)

        called = {"continue_run": False}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            called["continue_run"] = True
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-resolved",
            session_id="session-1",
            stream=False,
        )

        # Approval check was skipped (no unresolved reqs → no need to ask)
        assert approval_calls["called"] is False
        assert called["continue_run"] is True

    def test_explicit_requirements_in_body_still_works(self, monkeypatch: pytest.MonkeyPatch):
        """Existing HITL flow: caller provides ``requirements`` → dispatch
        applies them and resumes. Same behavior as pre-ADR-003."""
        pending_tool = ToolExecution(
            tool_call_id="tc-pending",
            tool_name="needs_input",
            tool_args={},
            requires_user_input=True,
        )
        pending_requirement = RunRequirement(tool_execution=pending_tool)
        paused_run = RunOutput(
            run_id="run-pause",
            session_id="session-1",
            status=RunStatus.paused,
            tools=[pending_tool],
            requirements=[pending_requirement],
            messages=[],
        )
        agent = _make_agent(monkeypatch, runs=[paused_run])

        # Caller fills in the requirement with a result
        resolved_tool = ToolExecution(
            tool_call_id="tc-pending",
            tool_name="needs_input",
            tool_args={},
            requires_user_input=True,
            result="user supplied value",
        )
        resolved_requirement = RunRequirement(tool_execution=resolved_tool)

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["requirements"] = run_response.requirements
            captured["tools"] = run_response.tools
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-pause",
            session_id="session-1",
            requirements=[resolved_requirement],
            stream=False,
        )

        # The resolved requirement was applied
        assert captured["requirements"][0] is resolved_requirement
        assert captured["tools"][0].result == "user supplied value"


# ---------------------------------------------------------------------------
# Async parity
# ---------------------------------------------------------------------------


def _patch_async_dispatch_dependencies(
    agent: Agent,
    monkeypatch: pytest.MonkeyPatch,
    runs: Optional[list[Any]] = None,
) -> None:
    """Mirror of _patch_sync_dispatch_dependencies for the async dispatch path."""
    from agno.agent import _storage as storage_mod

    async def fake_aread_or_create_session(agent, session_id=None, user_id=None):
        return AgentSession(session_id=session_id, user_id=user_id, runs=runs)

    monkeypatch.setattr(_init, "has_async_db", lambda agent: False)
    monkeypatch.setattr(storage_mod, "aread_or_create_session", fake_aread_or_create_session)
    monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
    monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
    monkeypatch.setattr(_storage, "load_session_state", lambda agent, session=None, session_state=None: session_state)
    monkeypatch.setattr(_response, "get_response_format", lambda agent, run_context=None: None)


class TestAsyncEmptyBodyResume:
    """Same coverage as TestEmptyBodyResume but through acontinue_run_dispatch."""

    @pytest.mark.asyncio
    async def test_async_resume_interrupted_run_with_empty_body(self, monkeypatch: pytest.MonkeyPatch):
        completed_tool = ToolExecution(tool_call_id="tc-1", tool_name="searcher", tool_args={}, result="ok")
        interrupted_run = RunOutput(
            run_id="run-int",
            session_id="session-1",
            status=RunStatus.running,
            tools=[completed_tool],
            requirements=None,
            messages=[],
        )

        agent = Agent(name="test-agent")
        _patch_async_dispatch_dependencies(agent, monkeypatch, runs=[interrupted_run])
        monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)

        # Patch _acontinue_run to capture the call
        captured: dict = {"reached": False}

        async def fake_acontinue_run(agent, session_id, run_context, run_response=None, **kw):
            captured["reached"] = True
            captured["run_response"] = run_response
            if run_response is None:
                # _acontinue_run resolves run_response from session if not provided;
                # our test passes run_id only, so it'd hit this branch in reality.
                pass
            return run_response

        monkeypatch.setattr(_run, "_acontinue_run", fake_acontinue_run)

        await _run.acontinue_run_dispatch(
            agent=agent,
            run_id="run-int",
            session_id="session-1",
            stream=False,
        )

        assert captured["reached"] is True

    @pytest.mark.asyncio
    async def test_async_unresolved_requirements_without_body_surfaces_error(self, monkeypatch: pytest.MonkeyPatch):
        """HITL contract preserved on the async path. ``_acontinue_run`` now has an
        ``except ValueError: raise`` block (added by the cancel-run-persistence
        change in main) that lets validation errors propagate to the caller —
        matching sync behavior."""
        pending_tool = ToolExecution(
            tool_call_id="tc-pending",
            tool_name="needs_input",
            tool_args={},
            requires_user_input=True,
        )
        pending_requirement = RunRequirement(tool_execution=pending_tool)
        paused_run = RunOutput(
            run_id="run-pause",
            session_id="session-1",
            status=RunStatus.paused,
            tools=[pending_tool],
            requirements=[pending_requirement],
            messages=[],
        )

        agent = Agent(name="test-agent", retries=0)  # no retries so the failure is immediate
        _patch_async_dispatch_dependencies(agent, monkeypatch, runs=[paused_run])
        monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)

        from agno.run import approval as approval_mod

        async def raising_approval(db, run_id, run_response):
            raise RuntimeError("no resolved approval")

        monkeypatch.setattr(approval_mod, "acheck_and_apply_approval_resolution", raising_approval)

        with pytest.raises(ValueError, match="unresolved HITL requirements"):
            await _run.acontinue_run_dispatch(
                agent=agent,
                run_id="run-pause",
                session_id="session-1",
                stream=False,
            )


class TestInputAppend:
    """The ``input`` body field appends a new user-message to the run before resume.
    Supports the COMPLETED-plus-new-message variant and adds context to any resume."""

    def test_input_appends_user_message(self, monkeypatch: pytest.MonkeyPatch):
        """``input="follow up question"`` appends a user-role message to
        run_response.messages before _continue_run sees it."""
        completed_run = RunOutput(
            run_id="run-done",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[],
            requirements=None,
            messages=[
                Message(role="user", content="original question"),
                Message(role="assistant", content="original answer"),
            ],
        )
        agent = _make_agent(monkeypatch, runs=[completed_run])

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["run_response_messages"] = list(run_response.messages or [])
            captured["run_messages"] = run_messages.messages
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-done",
            session_id="session-1",
            input="follow up question",
            stream=False,
        )

        # The appended message is on run_response.messages
        appended = captured["run_response_messages"]
        assert len(appended) == 3, "Original 2 messages + 1 appended user message"
        assert appended[-1].role == "user"
        assert appended[-1].content == "follow up question"

    def test_input_none_leaves_messages_unchanged(self, monkeypatch: pytest.MonkeyPatch):
        """Default ``input=None`` does not modify the run's messages."""
        completed_run = RunOutput(
            run_id="run-done",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[],
            requirements=None,
            messages=[Message(role="user", content="original")],
        )
        agent = _make_agent(monkeypatch, runs=[completed_run])

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["count"] = len(run_response.messages or [])
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-done",
            session_id="session-1",
            input=None,
            stream=False,
        )

        assert captured["count"] == 1, "No append when input is None"

    def test_input_empty_string_leaves_messages_unchanged(self, monkeypatch: pytest.MonkeyPatch):
        """An empty string is treated like None — no append. Matches HTML form
        semantics where unset fields come through as ''."""
        completed_run = RunOutput(
            run_id="run-done",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[],
            requirements=None,
            messages=[Message(role="user", content="original")],
        )
        agent = _make_agent(monkeypatch, runs=[completed_run])

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["count"] = len(run_response.messages or [])
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-done",
            session_id="session-1",
            input="",
            stream=False,
        )

        assert captured["count"] == 1

    def test_input_works_alongside_resume_from_interrupted(self, monkeypatch: pytest.MonkeyPatch):
        """Common case: user has an INTERRUPTED run and wants to add new context
        on resume. Both 'resume on empty body' and 'append input' compose."""
        interrupted_run = RunOutput(
            run_id="run-int",
            session_id="session-1",
            status=RunStatus.running,
            tools=[ToolExecution(tool_call_id="t1", tool_name="x", tool_args={}, result="r1")],
            requirements=None,
            messages=[
                Message(role="user", content="please research foo"),
                Message(role="assistant", content="searching..."),
                Message(role="tool", content="r1", tool_call_id="t1"),
            ],
        )
        agent = _make_agent(monkeypatch, runs=[interrupted_run])

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["messages"] = list(run_response.messages or [])
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-int",
            session_id="session-1",
            input="also include bar",
            stream=False,
        )

        msgs = captured["messages"]
        assert len(msgs) == 4
        assert msgs[-1].role == "user"
        assert msgs[-1].content == "also include bar"


# ---------------------------------------------------------------------------
# from_checkpoint — time-travel truncation
# ---------------------------------------------------------------------------


class TestTruncateHelper:
    """Direct coverage of _truncate_run_to_checkpoint."""

    def _build_run_with_tools(self) -> RunOutput:
        """5 messages: user, assistant(calls tc1), tool(tc1), assistant(calls tc2), tool(tc2)."""
        return RunOutput(
            run_id="run-1",
            session_id="session-1",
            tools=[
                ToolExecution(tool_call_id="tc1", tool_name="x", tool_args={}, result="r1"),
                ToolExecution(tool_call_id="tc2", tool_name="y", tool_args={}, result="r2"),
            ],
            messages=[
                Message(role="user", content="q1"),
                Message(role="assistant", content=None, tool_calls=[{"id": "tc1"}]),
                Message(role="tool", content="r1", tool_call_id="tc1"),
                Message(role="assistant", content=None, tool_calls=[{"id": "tc2"}]),
                Message(role="tool", content="r2", tool_call_id="tc2"),
            ],
        )

    def test_truncate_drops_trailing_messages(self):
        run = self._build_run_with_tools()
        _truncate_run_to_checkpoint(run, 3)
        assert run.messages is not None
        assert len(run.messages) == 3
        assert run.messages[-1].content == "r1"

    def test_truncate_drops_tools_for_removed_messages(self):
        """Truncating to index 3 keeps tc1 (referenced in surviving messages) and
        drops tc2 (its tool message and assistant tool_calls entry are both gone)."""
        run = self._build_run_with_tools()
        _truncate_run_to_checkpoint(run, 3)
        assert run.tools is not None
        assert [t.tool_call_id for t in run.tools] == ["tc1"]

    def test_truncate_updates_checkpoint_marker(self):
        run = self._build_run_with_tools()
        _truncate_run_to_checkpoint(run, 3)
        assert run.last_checkpoint_at_message_index == 3

    def test_truncate_beyond_length_is_noop(self):
        run = self._build_run_with_tools()
        original_len = len(run.messages or [])
        _truncate_run_to_checkpoint(run, 100)
        assert len(run.messages or []) == original_len
        assert [t.tool_call_id for t in (run.tools or [])] == ["tc1", "tc2"]

    def test_truncate_negative_is_noop(self):
        run = self._build_run_with_tools()
        original_len = len(run.messages or [])
        _truncate_run_to_checkpoint(run, -1)
        assert len(run.messages or []) == original_len

    def test_truncate_zero_clears_messages(self):
        run = self._build_run_with_tools()
        _truncate_run_to_checkpoint(run, 0)
        assert run.messages == []
        assert run.tools == [], "All tools dropped when no messages survive"
        assert run.last_checkpoint_at_message_index == 0

    def test_truncate_filters_requirements(self):
        pending_tool = ToolExecution(tool_call_id="tc-late", tool_name="z", tool_args={})
        run = RunOutput(
            run_id="r1",
            session_id="s1",
            tools=[pending_tool],
            requirements=[RunRequirement(tool_execution=pending_tool)],
            messages=[
                Message(role="user", content="q"),
                Message(role="assistant", content=None, tool_calls=[{"id": "tc-late"}]),
                Message(role="tool", content="r", tool_call_id="tc-late"),
            ],
        )
        # Truncate before the tool was even called
        _truncate_run_to_checkpoint(run, 1)
        assert run.tools == []
        assert run.requirements == [], "Requirement dropped because its tool no longer survives"


class TestForkHelper:
    """Direct coverage of _fork_run."""

    def _build_run(self) -> RunOutput:
        return RunOutput(
            run_id="origin-run",
            session_id="session-1",
            tools=[ToolExecution(tool_call_id="tc1", tool_name="x", tool_args={}, result="r1")],
            messages=[
                Message(role="user", content="q1"),
                Message(role="assistant", content=None, tool_calls=[{"id": "tc1"}]),
                Message(role="tool", content="r1", tool_call_id="tc1"),
                Message(role="assistant", content="final answer"),
            ],
        )

    def test_fork_assigns_new_run_id(self):
        original = self._build_run()
        forked = _fork_run(original, 4)
        assert forked.run_id != original.run_id
        assert isinstance(forked.run_id, str)
        assert len(forked.run_id) > 0

    def test_fork_sets_fork_metadata(self):
        original = self._build_run()
        forked = _fork_run(original, 2)
        assert forked.forked_from_run_id == "origin-run"
        assert forked.forked_from_message_index == 2

    def test_fork_preserves_session_id(self):
        original = self._build_run()
        forked = _fork_run(original, 2)
        assert forked.session_id == original.session_id

    def test_fork_does_not_mutate_original(self):
        original = self._build_run()
        original_messages = list(original.messages or [])
        original_tools = list(original.tools or [])
        original_run_id = original.run_id

        _fork_run(original, 1)

        assert original.run_id == original_run_id
        assert list(original.messages or []) == original_messages
        assert list(original.tools or []) == original_tools
        assert original.forked_from_run_id is None

    def test_fork_truncates_to_index(self):
        original = self._build_run()
        forked = _fork_run(original, 2)
        assert forked.messages is not None
        assert len(forked.messages) == 2
        # tc1 is referenced by the assistant message at index 1, so it survives
        # truncation to length 2. The tool RESULT at index 2 is gone but the
        # tool_call is still in the assistant's tool_calls list.
        assert forked.tools is not None
        assert [t.tool_call_id for t in forked.tools] == ["tc1"]

    def test_fork_truncate_drops_unreferenced_tools(self):
        """Truncating to a point BEFORE any tool_calls drops the tool entirely."""
        original = self._build_run()
        forked = _fork_run(original, 1)  # only user q1 survives
        assert forked.messages is not None
        assert len(forked.messages) == 1
        assert forked.tools == [], "No tool_call_ids referenced in surviving messages"


# ---------------------------------------------------------------------------
# Dispatch wiring for from_checkpoint and fork
# ---------------------------------------------------------------------------


class TestDispatchTruncate:
    """End-to-end: continue_run_dispatch applies from_checkpoint to the loaded run."""

    def test_dispatch_truncates_messages(self, monkeypatch: pytest.MonkeyPatch):
        existing_run = RunOutput(
            run_id="run-1",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[ToolExecution(tool_call_id="tc1", tool_name="x", tool_args={}, result="r")],
            messages=[
                Message(role="user", content="q1"),
                Message(role="assistant", content=None, tool_calls=[{"id": "tc1"}]),
                Message(role="tool", content="r", tool_call_id="tc1"),
                Message(role="assistant", content="answer"),
            ],
        )
        agent = _make_agent(monkeypatch, runs=[existing_run])

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["messages"] = list(run_response.messages or [])
            captured["tools"] = list(run_response.tools or [])
            captured["checkpoint_idx"] = run_response.last_checkpoint_at_message_index
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        # Truncate to index 1 — only the user question survives. The assistant's
        # tool_calls and the tool result are both dropped, so tc1 has no references.
        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-1",
            session_id="session-1",
            from_checkpoint=1,
            stream=False,
        )

        assert len(captured["messages"]) == 1
        assert captured["tools"] == [], "Tools dropped — no references in surviving messages"
        assert captured["checkpoint_idx"] == 1

    def test_dispatch_truncate_composes_with_input(self, monkeypatch: pytest.MonkeyPatch):
        """from_checkpoint=K AND input="..." → truncate then append."""
        existing_run = RunOutput(
            run_id="run-1",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[],
            messages=[
                Message(role="user", content="original"),
                Message(role="assistant", content="answer 1"),
                Message(role="user", content="follow-up 1"),
                Message(role="assistant", content="answer 2"),
            ],
        )
        agent = _make_agent(monkeypatch, runs=[existing_run])

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["messages"] = list(run_response.messages or [])
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-1",
            session_id="session-1",
            from_checkpoint=2,
            input="new follow-up",
            stream=False,
        )

        msgs = captured["messages"]
        # 2 from truncate + 1 appended user message
        assert len(msgs) == 3
        assert msgs[-1].role == "user"
        assert msgs[-1].content == "new follow-up"


class TestDispatchFork:
    """End-to-end: continue_run_dispatch with fork=True clones the run."""

    def test_fork_creates_new_run_with_metadata(self, monkeypatch: pytest.MonkeyPatch):
        original = RunOutput(
            run_id="origin-run",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[],
            messages=[
                Message(role="user", content="q1"),
                Message(role="assistant", content="a1"),
            ],
        )
        agent = _make_agent(monkeypatch, runs=[original])

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["run_response"] = run_response
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="origin-run",
            session_id="session-1",
            fork=True,
            from_checkpoint=1,
            stream=False,
        )

        rr = captured["run_response"]
        assert rr.run_id != "origin-run", "Forked run has a new ID"
        assert rr.forked_from_run_id == "origin-run"
        assert rr.forked_from_message_index == 1
        assert rr.session_id == "session-1", "Fork stays in the same session"
        assert len(rr.messages or []) == 1, "Truncated to index 1"

    def test_fork_without_explicit_from_checkpoint_defaults_to_full_length(self, monkeypatch: pytest.MonkeyPatch):
        """fork=True without from_checkpoint clones at the current end → no
        truncation, just a sibling that starts where the original left off."""
        original = RunOutput(
            run_id="origin-run",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[],
            messages=[
                Message(role="user", content="q1"),
                Message(role="assistant", content="a1"),
            ],
        )
        agent = _make_agent(monkeypatch, runs=[original])

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["run_response"] = run_response
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="origin-run",
            session_id="session-1",
            fork=True,
            stream=False,
        )

        rr = captured["run_response"]
        assert rr.run_id != "origin-run"
        assert rr.forked_from_run_id == "origin-run"
        assert rr.forked_from_message_index == 2  # len(messages)
        assert len(rr.messages or []) == 2, "Full messages preserved"

    def test_fork_does_not_mutate_session_run(self, monkeypatch: pytest.MonkeyPatch):
        """Forking via dispatch should NOT mutate the original run sitting in the
        session.runs array — the clone is independent."""
        original = RunOutput(
            run_id="origin-run",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[],
            messages=[
                Message(role="user", content="q1"),
                Message(role="assistant", content="a1"),
                Message(role="user", content="follow"),
            ],
        )
        agent = _make_agent(monkeypatch, runs=[original])

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="origin-run",
            session_id="session-1",
            fork=True,
            from_checkpoint=1,
            stream=False,
        )

        # Original is unchanged
        assert original.run_id == "origin-run"
        assert len(original.messages or []) == 3
        assert original.forked_from_run_id is None
