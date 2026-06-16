"""Unit tests for the unified ``/continue`` dispatch (phase 3 of run-checkpointing).

Scope covers the ADR-003 / ADR-004 reframing of ``continue_run_dispatch``:
- Drop the PAUSED-only 409 gate. Any persisted run can be advanced via /continue
  given a sensible body.
- A run with NO unresolved HITL requirements + empty body resumes from its
  current persisted state (mid-flight resume, ERROR retry, time-travel).
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
from agno.utils.message import safe_truncation_index
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
    are unresolved — supports mid-flight resume, ERROR retry, time-travel."""

    def test_resume_interrupted_run_with_empty_body(self, monkeypatch: pytest.MonkeyPatch):
        """A mid-flight run (persisted as RUNNING by checkpoint, no unresolved
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
            "_continue_run should be invoked for an mid-flight run with empty body"
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

    def test_resume_completed_run_with_empty_body_auto_forks(self, monkeypatch: pytest.MonkeyPatch):
        """A COMPLETED run continued with empty body must auto-fork: a new
        ``run_id`` is created so the source COMPLETED row is preserved with
        its original metrics. Reusing the same run_id would corrupt the
        "1 run = 1 model loop" invariant.
        """
        completed_run = RunOutput(
            run_id="run-done",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[],
            requirements=None,
            messages=[Message(role="user", content="hi"), Message(role="assistant", content="hello")],
        )
        agent = _make_agent(monkeypatch, runs=[completed_run])

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["run_id"] = run_response.run_id
            captured["forked_from_run_id"] = run_response.forked_from_run_id
            captured["forked_from_message_index"] = run_response.forked_from_message_index
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-done",
            session_id="session-1",
            stream=False,
        )

        # New run_id (auto-fork)
        assert captured["run_id"] != "run-done"
        # Lineage recorded
        assert captured["forked_from_run_id"] == "run-done"
        # Forked at end-of-messages (no truncation since no checkpoint specified)
        assert captured["forked_from_message_index"] == 2
        # Source run preserved — its status is still COMPLETED, run_id unchanged
        assert completed_run.status == RunStatus.completed
        assert completed_run.run_id == "run-done"

    def test_resume_run_with_completed_tools_no_requirements(self, monkeypatch: pytest.MonkeyPatch):
        """A run that completed several tool batches but has no pending HITL
        (no requirements) resumes with empty body — common mid-flight case."""
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
        """Common case: user has a mid-flight RUNNING run and wants to add new context
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
# message_index — time-travel truncation
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


def _assert_no_orphaned_tool_calls(messages) -> None:
    """Every tool_call owned by a surviving assistant must have its result
    message also present — otherwise providers reject the transcript."""
    result_ids = {m.tool_call_id for m in (messages or []) if getattr(m, "tool_call_id", None)}
    for m in messages or []:
        for tc in getattr(m, "tool_calls", None) or []:
            tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
            if tc_id:
                assert tc_id in result_ids, f"orphaned tool_call {tc_id} (no matching result message)"


class TestTruncatePairSafety:
    """The boundary must never split an assistant tool_call from its result."""

    def _build_single_call_run(self) -> RunOutput:
        """4 messages: user, assistant(calls tc1), tool(tc1), assistant(final)."""
        return RunOutput(
            run_id="run-ps",
            session_id="s",
            tools=[ToolExecution(tool_call_id="tc1", tool_name="x", tool_args={}, result="r1")],
            messages=[
                Message(role="user", content="q"),
                Message(role="assistant", content=None, tool_calls=[{"id": "tc1"}]),
                Message(role="tool", content="r1", tool_call_id="tc1"),
                Message(role="assistant", content="final answer"),
            ],
        )

    def _build_multi_call_run(self) -> RunOutput:
        """5 messages: user, assistant(calls tc1+tc2), tool(tc1), tool(tc2), assistant(final)."""
        return RunOutput(
            run_id="run-mc",
            session_id="s",
            tools=[
                ToolExecution(tool_call_id="tc1", tool_name="x", tool_args={}, result="r1"),
                ToolExecution(tool_call_id="tc2", tool_name="y", tool_args={}, result="r2"),
            ],
            messages=[
                Message(role="user", content="q"),
                Message(role="assistant", content=None, tool_calls=[{"id": "tc1"}, {"id": "tc2"}]),
                Message(role="tool", content="r1", tool_call_id="tc1"),
                Message(role="tool", content="r2", tool_call_id="tc2"),
                Message(role="assistant", content="final answer"),
            ],
        )

    def test_cut_between_assistant_and_result_snaps_down(self):
        """Index 2 lands after assistant(tool_calls) but before its result —
        snaps down to 1, dropping the incomplete exchange."""
        run = self._build_single_call_run()
        _truncate_run_to_checkpoint(run, 2)
        assert [m.role for m in (run.messages or [])] == ["user"]
        assert run.last_checkpoint_at_message_index == 1
        _assert_no_orphaned_tool_calls(run.messages)

    def test_cut_inside_result_batch_snaps_down(self):
        """Index 3 keeps tool(tc1) but drops tool(tc2), orphaning tc2 — snaps to 1."""
        run = self._build_multi_call_run()
        _truncate_run_to_checkpoint(run, 3)
        assert [m.role for m in (run.messages or [])] == ["user"]
        assert run.last_checkpoint_at_message_index == 1
        _assert_no_orphaned_tool_calls(run.messages)

    def test_complete_exchange_boundary_is_not_snapped(self):
        """Index 4 keeps the full assistant+both-results batch — pair-safe, no snap."""
        run = self._build_multi_call_run()
        _truncate_run_to_checkpoint(run, 4)
        assert len(run.messages or []) == 4
        assert run.last_checkpoint_at_message_index == 4
        _assert_no_orphaned_tool_calls(run.messages)

    def test_fork_at_mid_batch_index_is_pair_safe(self):
        """Forking at an orphaning index produces a valid transcript and records
        the snapped boundary in fork metadata."""
        run = self._build_single_call_run()
        forked = _fork_run(run, 2)
        assert [m.role for m in (forked.messages or [])] == ["user"]
        assert forked.forked_from_message_index == 1
        _assert_no_orphaned_tool_calls(forked.messages)
        # Original untouched.
        assert len(run.messages or []) == 4

    def test_safe_index_helper_snaps_and_is_idempotent(self):
        run = self._build_multi_call_run()
        msgs = run.messages
        # mid-batch -> first offending assistant
        assert safe_truncation_index(msgs, 2) == 1
        assert safe_truncation_index(msgs, 3) == 1
        # complete-exchange and end boundaries are untouched
        assert safe_truncation_index(msgs, 4) == 4
        assert safe_truncation_index(msgs, 5) == 5
        assert safe_truncation_index(msgs, 1) == 1
        assert safe_truncation_index(msgs, 0) == 0
        # idempotent: snapping an already-safe result is a fixed point
        assert safe_truncation_index(msgs, safe_truncation_index(msgs, 3)) == 1


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
        forked = _fork_run(original, 3)
        assert forked.forked_from_run_id == "origin-run"
        assert forked.forked_from_message_index == 3

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
        # Index 3 keeps the complete tool exchange (assistant tool_call + result),
        # a pair-safe boundary. tc1 is still referenced, so it survives.
        forked = _fork_run(original, 3)
        assert forked.messages is not None
        assert len(forked.messages) == 3
        assert forked.tools is not None
        assert [t.tool_call_id for t in forked.tools] == ["tc1"]
        _assert_no_orphaned_tool_calls(forked.messages)

    def test_fork_truncate_drops_unreferenced_tools(self):
        """Truncating to a point BEFORE any tool_calls drops the tool entirely."""
        original = self._build_run()
        forked = _fork_run(original, 1)  # only user q1 survives
        assert forked.messages is not None
        assert len(forked.messages) == 1
        assert forked.tools == [], "No tool_call_ids referenced in surviving messages"


# ---------------------------------------------------------------------------
# Dispatch wiring for message_index and fork
# ---------------------------------------------------------------------------


class TestDispatchTruncate:
    """End-to-end: continue_run_dispatch applies message_index to the loaded run."""

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
            continue_from=1,
            stream=False,
        )

        assert len(captured["messages"]) == 1
        assert captured["tools"] == [], "Tools dropped — no references in surviving messages"
        assert captured["checkpoint_idx"] == 1

    def test_dispatch_truncate_composes_with_input(self, monkeypatch: pytest.MonkeyPatch):
        """continue_from=K AND input="..." -> truncate then append."""
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
            continue_from=2,
            input="new follow-up",
            stream=False,
        )

        msgs = captured["messages"]
        # 2 from truncate + 1 appended user message
        assert len(msgs) == 3
        assert msgs[-1].role == "user"
        assert msgs[-1].content == "new follow-up"

    def test_continue_from_end_literal_keeps_all_messages_and_forks_completed(self, monkeypatch: pytest.MonkeyPatch):
        """continue_from='end' keeps the full transcript and auto-forks completed runs."""
        keep = Message(role="user", content="original")
        drop = Message(role="assistant", content="answer")
        existing_run = RunOutput(
            run_id="run-1",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[],
            messages=[keep, drop],
        )
        agent = _make_agent(monkeypatch, runs=[existing_run])

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["messages"] = list(run_response.messages or [])
            captured["forked_from_run_id"] = run_response.forked_from_run_id
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-1",
            session_id="session-1",
            continue_from="end",
            stream=False,
        )

        assert [m.id for m in captured["messages"]] == [keep.id, drop.id]
        assert captured["forked_from_run_id"] == "run-1"

    def test_continue_from_unknown_string_raises(self, monkeypatch: pytest.MonkeyPatch):
        existing_run = RunOutput(
            run_id="run-1",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[],
            messages=[Message(role="user", content="original")],
        )
        agent = _make_agent(monkeypatch, runs=[existing_run])

        with pytest.raises(ValueError, match="integer message index"):
            _run.continue_run_dispatch(
                agent=agent,
                run_id="run-1",
                session_id="session-1",
                continue_from="msg-not-supported",  # type: ignore[arg-type]
                stream=False,
            )

    def test_continue_from_last_user_literal(self, monkeypatch: pytest.MonkeyPatch):
        existing_run = RunOutput(
            run_id="run-1",
            session_id="session-1",
            status=RunStatus.completed,
            tools=[],
            messages=[
                Message(role="user", content="q1"),
                Message(role="assistant", content="a1"),
                Message(role="user", content="q2"),
                Message(role="assistant", content="a2"),
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
            continue_from="last_user",
            stream=False,
        )

        assert [m.content for m in captured["messages"]] == ["q1", "a1", "q2"]


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
            continue_from=1,
            stream=False,
        )

        rr = captured["run_response"]
        assert rr.run_id != "origin-run", "Forked run has a new ID"
        assert rr.forked_from_run_id == "origin-run"
        assert rr.forked_from_message_index == 1
        assert rr.session_id == "session-1", "Fork stays in the same session"
        assert len(rr.messages or []) == 1, "Truncated to index 1"

    def test_fork_without_explicit_continue_from_defaults_to_full_length(self, monkeypatch: pytest.MonkeyPatch):
        """fork=True without continue_from clones at the current end -> no
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
            continue_from=1,
            stream=False,
        )

        # Original is unchanged
        assert original.run_id == "origin-run"
        assert len(original.messages or []) == 3
        assert original.forked_from_run_id is None


# ---------------------------------------------------------------------------
# Bug-fix tests: fork resets metrics, not deep-copy of parent's
# ---------------------------------------------------------------------------


class TestForkMetricsReset:
    """A forked run is a NEW run — it should report its own work, not inherit the
    parent's accumulated metrics or birthtime."""

    def test_fork_resets_metrics_to_fresh(self):
        from agno.models.metrics import RunMetrics

        parent_metrics = RunMetrics()
        parent_metrics.input_tokens = 100
        parent_metrics.output_tokens = 50
        parent_metrics.total_tokens = 150
        original = RunOutput(
            run_id="origin",
            session_id="s",
            metrics=parent_metrics,
            messages=[Message(role="user", content="q")],
        )

        forked = _fork_run(original, message_index=1)

        assert forked.metrics is not original.metrics, "Fresh metrics object expected"
        assert forked.metrics.input_tokens == 0
        assert forked.metrics.output_tokens == 0
        assert forked.metrics.total_tokens == 0
        # Parent must remain unchanged
        assert original.metrics.input_tokens == 100

    def test_fork_resets_created_at(self):
        import time

        old_t = int(time.time()) - 1000  # 1000s ago
        original = RunOutput(
            run_id="origin",
            session_id="s",
            created_at=old_t,
            messages=[Message(role="user", content="q")],
        )

        forked = _fork_run(original, message_index=1)

        assert forked.created_at > old_t, "Fork should have a fresh created_at"
        assert original.created_at == old_t, "Parent's created_at must not be touched"


# ---------------------------------------------------------------------------
# Bug-fix tests: regenerate sugar normalizes to canonical params
# ---------------------------------------------------------------------------


class TestRegenerateSugar:
    """``regenerate=True``, ``replace_original=True``, and ``additional_instructions``
    are sugar params that normalize to the canonical ``fork`` / ``message_index``
    / ``input`` triple inside the dispatch."""

    def _build_run_with_assistant_tail(self) -> RunOutput:
        return RunOutput(
            run_id="run-A",
            session_id="s",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="What is 2+2?"),
                Message(role="assistant", content="4"),
            ],
        )

    def test_regenerate_truncates_after_last_user_message(self, monkeypatch: pytest.MonkeyPatch):
        run = self._build_run_with_assistant_tail()
        agent = _make_agent(monkeypatch, runs=[run])
        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["messages"] = list(run_response.messages or [])
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-A",
            session_id="s",
            regenerate=True,
            stream=False,
        )

        # The trailing assistant turn is dropped; only the user message survives.
        assert len(captured["messages"]) == 1
        assert captured["messages"][0].role == "user"

    def test_regenerate_preserves_intermediate_tool_exchange(self, monkeypatch: pytest.MonkeyPatch):
        """Regenerate drops only trailing no-tool-call
        assistant messages — intermediate tool exchanges survive so the model
        regenerates a fresh summary of the same tool results without re-invoking
        the tools."""
        run = RunOutput(
            run_id="run-tool",
            session_id="s",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="What is 2+2?"),
                Message(role="assistant", content=None, tool_calls=[{"id": "tc1"}]),
                Message(role="tool", content="4", tool_call_id="tc1"),
                Message(role="assistant", content="The answer is 4."),
            ],
        )
        agent = _make_agent(monkeypatch, runs=[run])
        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["messages"] = list(run_response.messages or [])
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-tool",
            session_id="s",
            regenerate=True,
            stream=False,
        )

        # Trailing plain assistant turn dropped; intermediate tool-calling
        # assistant + tool result survive.
        roles = [m.role for m in captured["messages"]]
        assert roles == ["user", "assistant", "tool"]

    def test_continue_from_last_user_drops_intermediate_tool_exchange(self, monkeypatch: pytest.MonkeyPatch):
        """continue_from='last_user' is distinct from regenerate: it drops the
        whole post-user tail, including intermediate tool exchanges."""
        run = RunOutput(
            run_id="run-tool",
            session_id="s",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="What is 2+2?"),
                Message(role="assistant", content=None, tool_calls=[{"id": "tc1"}]),
                Message(role="tool", content="4", tool_call_id="tc1"),
                Message(role="assistant", content="The answer is 4."),
            ],
        )
        agent = _make_agent(monkeypatch, runs=[run])
        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["messages"] = list(run_response.messages or [])
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-tool",
            session_id="s",
            continue_from="last_user",
            stream=False,
        )

        # Only the user message survives — the tool exchange is dropped.
        assert [m.role for m in captured["messages"]] == ["user"]

    def test_regenerate_with_additional_instructions_appends_user_msg(self, monkeypatch: pytest.MonkeyPatch):
        run = self._build_run_with_assistant_tail()
        agent = _make_agent(monkeypatch, runs=[run])
        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["messages"] = list(run_response.messages or [])
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-A",
            session_id="s",
            regenerate=True,
            additional_instructions="Be more detailed",
            stream=False,
        )

        # Original user message + the additional_instructions appended as user.
        assert len(captured["messages"]) == 2
        assert captured["messages"][0].content == "What is 2+2?"
        assert captured["messages"][1].content == "Be more detailed"
        assert captured["messages"][1].role == "user"

    def test_regenerate_records_regenerated_from_lineage(self, monkeypatch: pytest.MonkeyPatch):
        run = self._build_run_with_assistant_tail()
        agent = _make_agent(monkeypatch, runs=[run])
        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["run_response"] = run_response
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-A",
            session_id="s",
            regenerate=True,
            stream=False,
        )

        assert captured["run_response"].regenerated_from == "run-A"

    def test_replace_original_marks_old_run_regenerated(self, monkeypatch: pytest.MonkeyPatch):
        run = self._build_run_with_assistant_tail()
        agent = _make_agent(monkeypatch, runs=[run])

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-A",
            session_id="s",
            regenerate=True,
            replace_original=True,
            stream=False,
        )

        # Old run got status flipped (history-builders will skip it).
        assert run.status == RunStatus.regenerated

    def test_replace_original_creates_fork_with_new_run_id(self, monkeypatch: pytest.MonkeyPatch):
        run = self._build_run_with_assistant_tail()
        agent = _make_agent(monkeypatch, runs=[run])
        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["run_id"] = run_response.run_id
            captured["forked_from"] = run_response.forked_from_run_id
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-A",
            session_id="s",
            regenerate=True,
            replace_original=True,
            stream=False,
        )

        # Sugar resolves replace_original=True → fork=True under the hood.
        assert captured["run_id"] != "run-A"
        assert captured["forked_from"] == "run-A"

    def test_regenerate_always_forks(self, monkeypatch: pytest.MonkeyPatch):
        """``regenerate=True`` ALWAYS creates a new run_id (1-run-1-loop
        invariant). ``replace_original`` is a separate concern about
        whether the source is hidden from history, not whether to fork.
        """
        run = self._build_run_with_assistant_tail()
        agent = _make_agent(monkeypatch, runs=[run])
        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["run_id"] = run_response.run_id
            captured["forked_from"] = run_response.forked_from_run_id
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-A",
            session_id="s",
            regenerate=True,
            stream=False,
        )

        # New run_id with lineage recorded — the source row is retained.
        assert captured["run_id"] != "run-A"
        assert captured["forked_from"] == "run-A"
        # Source row is retained (original run_id) but, by default
        # (replace_original defaults to True), marked REGENERATED so the new
        # run replaces it in history.
        assert run.run_id == "run-A"
        assert run.status == RunStatus.regenerated

    def test_regenerate_replace_original_false_keeps_source_visible(self, monkeypatch: pytest.MonkeyPatch):
        """``replace_original=False`` leaves the source COMPLETED and visible so
        both attempts show up in history."""
        run = self._build_run_with_assistant_tail()
        agent = _make_agent(monkeypatch, runs=[run])

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-A",
            session_id="s",
            regenerate=True,
            replace_original=False,
            stream=False,
        )

        # Source stays COMPLETED — not hidden from history.
        assert run.status == RunStatus.completed

    def test_regenerate_allows_default_end_boundary(self, monkeypatch: pytest.MonkeyPatch):
        run = self._build_run_with_assistant_tail()
        agent = _make_agent(monkeypatch, runs=[run])

        captured: dict = {}

        def fake_continue_run(agent, run_response, run_messages, run_context, session, tools, **kw):
            captured["messages"] = list(run_response.messages or [])
            return run_response

        monkeypatch.setattr(_run, "_continue_run", fake_continue_run)

        _run.continue_run_dispatch(
            agent=agent,
            run_id="run-A",
            session_id="s",
            regenerate=True,
            continue_from="end",
            stream=False,
        )

        assert [m.role for m in captured["messages"]] == ["user"]

    def test_regenerate_conflicts_with_explicit_fork(self, monkeypatch: pytest.MonkeyPatch):
        run = self._build_run_with_assistant_tail()
        agent = _make_agent(monkeypatch, runs=[run])

        with pytest.raises(ValueError, match="replace_original"):
            _run.continue_run_dispatch(
                agent=agent,
                run_id="run-A",
                session_id="s",
                regenerate=True,
                fork=True,
                stream=False,
            )

    def test_additional_instructions_with_input_conflicts(self, monkeypatch: pytest.MonkeyPatch):
        run = self._build_run_with_assistant_tail()
        agent = _make_agent(monkeypatch, runs=[run])

        with pytest.raises(ValueError, match="not both"):
            _run.continue_run_dispatch(
                agent=agent,
                run_id="run-A",
                session_id="s",
                regenerate=True,
                additional_instructions="A",
                input="B",
                stream=False,
            )

    def test_replace_original_without_regenerate_raises(self, monkeypatch: pytest.MonkeyPatch):
        run = self._build_run_with_assistant_tail()
        agent = _make_agent(monkeypatch, runs=[run])

        with pytest.raises(ValueError, match="`regenerate=True`"):
            _run.continue_run_dispatch(
                agent=agent,
                run_id="run-A",
                session_id="s",
                replace_original=True,
                stream=False,
            )

    def test_regenerate_raises_on_run_with_only_assistant_messages(self, monkeypatch: pytest.MonkeyPatch):
        """All messages are no-tool-call assistant turns → nothing to keep
        once they're stripped → raise."""
        run = RunOutput(
            run_id="run-A",
            session_id="s",
            messages=[Message(role="assistant", content="hi")],
        )
        agent = _make_agent(monkeypatch, runs=[run])

        with pytest.raises(ValueError, match="no non-assistant messages"):
            _run.continue_run_dispatch(
                agent=agent,
                run_id="run-A",
                session_id="s",
                regenerate=True,
                stream=False,
            )


# ---------------------------------------------------------------------------
# Bug-fix tests: fork_session deep-copies + rewrites lineage
# ---------------------------------------------------------------------------


class TestForkSession:
    """``Agent.fork_session()`` deep-copies all runs into a fresh session with
    new run_ids and the lineage pointers set correctly."""

    def _make_forking_agent(self, monkeypatch: pytest.MonkeyPatch, source: AgentSession) -> Agent:
        agent = Agent(name="b")
        monkeypatch.setattr(_init, "has_async_db", lambda agent: False)
        monkeypatch.setattr(
            _storage,
            "read_or_create_session",
            lambda agent, session_id=None, user_id=None: source,
        )
        saved: list = []
        from agno.agent import _session

        monkeypatch.setattr(_session, "save_session", lambda agent, session: saved.append(session))
        monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)
        agent._saved = saved  # type: ignore[attr-defined]
        return agent

    def test_fork_session_creates_new_session_with_fresh_ids(self, monkeypatch: pytest.MonkeyPatch):
        original_run = RunOutput(
            run_id="r-orig",
            session_id="s-orig",
            messages=[Message(role="user", content="hi")],
        )
        source = AgentSession(session_id="s-orig", user_id="u1", runs=[original_run])
        agent = self._make_forking_agent(monkeypatch, source)

        new_sid = agent.fork_session(source_session_id="s-orig", user_id="u1")

        assert new_sid != "s-orig"
        assert len(agent._saved) == 1  # type: ignore[attr-defined]
        saved = agent._saved[0]  # type: ignore[attr-defined]
        assert saved.session_id == new_sid
        assert len(saved.runs) == 1
        assert saved.runs[0].run_id != "r-orig"
        assert saved.runs[0].session_id == new_sid
        assert saved.runs[0].forked_from_session_id == "s-orig"

    def test_fork_session_does_not_mutate_source(self, monkeypatch: pytest.MonkeyPatch):
        original_run = RunOutput(
            run_id="r-orig",
            session_id="s-orig",
            messages=[Message(role="user", content="hi")],
        )
        source = AgentSession(session_id="s-orig", user_id="u1", runs=[original_run])
        agent = self._make_forking_agent(monkeypatch, source)

        agent.fork_session(source_session_id="s-orig", user_id="u1")

        # Source session and its run are untouched.
        assert source.session_id == "s-orig"
        assert source.runs[0].run_id == "r-orig"
        assert source.runs[0].session_id == "s-orig"
        assert source.runs[0].forked_from_session_id is None

    def test_fork_session_raises_on_empty_session(self, monkeypatch: pytest.MonkeyPatch):
        source = AgentSession(session_id="s-orig", user_id="u1", runs=[])
        agent = self._make_forking_agent(monkeypatch, source)

        with pytest.raises(ValueError, match="no runs"):
            agent.fork_session(source_session_id="s-orig", user_id="u1")

    def test_fork_session_preserves_forked_from_session_id_on_nested_fork(self, monkeypatch: pytest.MonkeyPatch):
        # A run that was already forked once keeps its original source pointer.
        nested_run = RunOutput(
            run_id="r-nested",
            session_id="s-mid",
            forked_from_session_id="s-root",  # root-level lineage already recorded
            messages=[Message(role="user", content="hi")],
        )
        source = AgentSession(session_id="s-mid", user_id="u1", runs=[nested_run])
        agent = self._make_forking_agent(monkeypatch, source)

        agent.fork_session(source_session_id="s-mid", user_id="u1")

        saved = agent._saved[0]  # type: ignore[attr-defined]
        # Run-level forked_from_session_id preserved (points at root).
        assert saved.runs[0].forked_from_session_id == "s-root"
        # Session-level forked_from_session_id points at immediate parent.
        assert saved.session_data["forked_from_session_id"] == "s-mid"


# ---------------------------------------------------------------------------
# Bug-fix tests: tool dedupe in update_run_response (checkpoint="tool-batch")
# ---------------------------------------------------------------------------


class TestToolDedupeOnUpdate:
    """When ``checkpoint="tool-batch"`` writes tools mid-run, the terminal
    ``update_run_response`` must not duplicate them by appending the same
    cumulative list again."""

    def test_update_run_response_replaces_by_tool_call_id(self):
        from agno.models.response import ModelResponse
        from agno.run.agent import RunOutput

        # Existing tool (already written by checkpoint callback)
        existing = ToolExecution(tool_call_id="tc-1", tool_name="search", result="result-1")
        run_response = RunOutput(run_id="r", tools=[existing])

        # Model response contains the same tool (cumulative across the loop)
        same_tool_updated = ToolExecution(tool_call_id="tc-1", tool_name="search", result="result-1-updated")
        new_tool = ToolExecution(tool_call_id="tc-2", tool_name="fetch", result="result-2")
        model_response = ModelResponse(tool_executions=[same_tool_updated, new_tool])

        from agno.agent._response import update_run_response

        update_run_response(
            agent=Agent(name="x"),
            model_response=model_response,
            run_response=run_response,
            run_messages=type("RM", (), {"messages": []})(),
            run_context=None,
        )

        # No duplicates by tool_call_id.
        ids = [t.tool_call_id for t in run_response.tools or []]
        assert sorted(ids) == ["tc-1", "tc-2"]
        # Existing entry was replaced with the newer instance.
        tc1 = next(t for t in run_response.tools if t.tool_call_id == "tc-1")
        assert tc1.result == "result-1-updated"


# ---------------------------------------------------------------------------
# Streaming parity: every body-flag variant must work with stream=True too.
#
# These tests are the bug-fix regression net for the original #8092 issue
# where fork=True + stream=True silently dropped the modifier. They exercise
# the full async streaming dispatch (acontinue_run_dispatch → _acontinue_run_stream)
# and assert that the run_response handed to _acontinue_run_stream's downstream
# consumers carries the correct fork/truncate/regenerate state.
# ---------------------------------------------------------------------------


class TestStreamingParity:
    """Verify every /continue variant lands correctly on the streaming path."""

    def _build_run(self) -> RunOutput:
        return RunOutput(
            run_id="run-S",
            session_id="sess-S",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Q1"),
                Message(role="assistant", content="A1"),
                Message(role="user", content="Q2"),
                Message(role="assistant", content="A2"),
            ],
        )

    def _patch_stream_dispatch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        captured: dict,
        runs: list,
    ) -> Agent:
        """Wire async dispatch dependencies and capture what reaches _acontinue_run_stream."""

        async def fake_aread_or_create_session(agent, session_id=None, user_id=None):
            return AgentSession(session_id=session_id, user_id=user_id, runs=runs)

        monkeypatch.setattr(_init, "has_async_db", lambda agent: False)
        monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
        monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
        monkeypatch.setattr(
            _storage, "load_session_state", lambda agent, session=None, session_state=None: session_state
        )
        monkeypatch.setattr(_response, "get_response_format", lambda agent, run_context=None: None)
        monkeypatch.setattr(_tools, "determine_tools_for_model", lambda *a, **kw: [])
        monkeypatch.setattr(_run, "aresolve_run_dependencies", lambda agent, run_context: None)

        agent = Agent(name="stream-test")
        monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)

        # Patch the streaming inner function to capture state *after* dispatch
        # has applied all modifiers/sugar normalization. This is the slot that
        # silently dropped fork before the fix.
        async def fake_acontinue_run_stream(agent, session_id, run_context, run_response=None, **kw):
            # The dispatch may rely on lazy loading via run_id; replicate the
            # session lookup that the real _acontinue_run_stream does so our
            # capture reflects post-modifier state.
            if run_response is None:
                rid = kw.get("run_id")
                # We patched aread_or_create_session above to return our runs
                session = await fake_aread_or_create_session(agent, session_id=session_id)
                run_response = next((r for r in (session.runs or []) if r.run_id == rid), None)
                # Manually apply modifiers since we're bypassing the real fn body
                from agno.agent._run import (
                    _apply_continue_modifiers,
                    _normalize_regenerate_params,
                    _resolve_continue_from,
                )

                continue_index = _resolve_continue_from(
                    run_response,
                    continue_from=kw.get("continue_from", "end"),
                    regenerate=kw.get("regenerate", False),
                )

                f, fc, inp = _normalize_regenerate_params(
                    run_response,
                    regenerate=kw.get("regenerate", False),
                    replace_original=kw.get("replace_original", None),
                    additional_instructions=kw.get("additional_instructions"),
                    fork=kw.get("fork", False),
                    continue_index=continue_index,
                    input=kw.get("input"),
                )
                if not f and run_response.status == RunStatus.completed:
                    f = True
                run_response = _apply_continue_modifiers(run_response, f, fc)
                if inp:
                    from agno.agent._run import _maybe_append_input_message

                    _maybe_append_input_message(run_response, inp, agent)

            captured["run_response"] = run_response
            captured["kw"] = kw
            yield run_response

        monkeypatch.setattr(_run, "_acontinue_run_stream", fake_acontinue_run_stream)
        return agent

    @pytest.mark.asyncio
    async def test_stream_fork_creates_new_run_id(self, monkeypatch: pytest.MonkeyPatch):
        """The original #8092 blocker: fork=True + stream=True must NOT be a silent no-op."""
        captured: dict = {}
        agent = self._patch_stream_dispatch(monkeypatch, captured, runs=[self._build_run()])

        result = agent.acontinue_run(
            run_id="run-S",
            session_id="sess-S",
            continue_from=2,
            fork=True,
            stream=True,
        )
        async for _ in result:
            pass

        rr = captured["run_response"]
        assert rr.run_id != "run-S", "Fork must assign a new run_id on the streaming path"
        assert rr.forked_from_run_id == "run-S"
        assert rr.forked_from_message_index == 2
        # Truncated to 2 messages (was 4)
        assert len(rr.messages or []) == 2

    @pytest.mark.asyncio
    async def test_stream_continue_from_index_truncates(self, monkeypatch: pytest.MonkeyPatch):
        """Time-travel via stream=True must actually truncate."""
        captured: dict = {}
        agent = self._patch_stream_dispatch(monkeypatch, captured, runs=[self._build_run()])

        result = agent.acontinue_run(
            run_id="run-S",
            session_id="sess-S",
            continue_from=1,
            stream=True,
        )
        async for _ in result:
            pass

        rr = captured["run_response"]
        # Completed runs auto-fork, even when the rewind happens through stream=True.
        assert rr.run_id != "run-S"
        assert rr.forked_from_run_id == "run-S"
        assert len(rr.messages or []) == 1

    @pytest.mark.asyncio
    async def test_stream_regenerate_drops_last_assistant(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict = {}
        agent = self._patch_stream_dispatch(monkeypatch, captured, runs=[self._build_run()])

        result = agent.acontinue_run(
            run_id="run-S",
            session_id="sess-S",
            regenerate=True,
            stream=True,
        )
        async for _ in result:
            pass

        rr = captured["run_response"]
        # The last user message is at index 2 → truncate to 3 (keep through Q2).
        assert len(rr.messages or []) == 3
        assert rr.messages[-1].role == "user"
        assert rr.messages[-1].content == "Q2"

    @pytest.mark.asyncio
    async def test_stream_regenerate_with_replace_original_forks(self, monkeypatch: pytest.MonkeyPatch):
        """replace_original=True on the streaming path must create a fork, not a rewrite."""
        captured: dict = {}
        agent = self._patch_stream_dispatch(monkeypatch, captured, runs=[self._build_run()])

        result = agent.acontinue_run(
            run_id="run-S",
            session_id="sess-S",
            regenerate=True,
            replace_original=True,
            stream=True,
        )
        async for _ in result:
            pass

        rr = captured["run_response"]
        assert rr.run_id != "run-S"  # forked
        assert rr.forked_from_run_id == "run-S"

    @pytest.mark.asyncio
    async def test_stream_regenerate_with_additional_instructions_appends(self, monkeypatch: pytest.MonkeyPatch):
        """additional_instructions on the streaming path must land as an appended user message."""
        captured: dict = {}
        agent = self._patch_stream_dispatch(monkeypatch, captured, runs=[self._build_run()])

        result = agent.acontinue_run(
            run_id="run-S",
            session_id="sess-S",
            regenerate=True,
            additional_instructions="be brief",
            stream=True,
        )
        async for _ in result:
            pass

        rr = captured["run_response"]
        # After truncation to last user msg (3 messages) + appended instruction = 4.
        assert len(rr.messages or []) == 4
        assert rr.messages[-1].role == "user"
        assert rr.messages[-1].content == "be brief"

    @pytest.mark.asyncio
    async def test_stream_input_appends_user_message(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict = {}
        agent = self._patch_stream_dispatch(monkeypatch, captured, runs=[self._build_run()])

        result = agent.acontinue_run(
            run_id="run-S",
            session_id="sess-S",
            input="follow-up question",
            stream=True,
        )
        async for _ in result:
            pass

        rr = captured["run_response"]
        # All 4 original messages + the appended input.
        assert len(rr.messages or []) == 5
        assert rr.messages[-1].content == "follow-up question"


class TestStreamingRealBody:
    """One end-to-end test that drives the *real* _acontinue_run_stream body
    (not a fake replacement) to confirm the modifiers fire on the real path.

    Patches everything past the modifier-application step to a no-op, then
    inspects run_response after the real function returns.
    """

    @pytest.mark.asyncio
    async def test_real_stream_body_applies_fork(self, monkeypatch: pytest.MonkeyPatch):
        from agno.agent import _messages

        run = RunOutput(
            run_id="run-real",
            session_id="sess-real",
            status=RunStatus.completed,
            messages=[
                Message(role="user", content="Q1"),
                Message(role="assistant", content="A1"),
            ],
        )

        # Use a list so the closure can mutate / read it
        observed: dict = {}

        async def fake_aread_or_create(agent, session_id=None, user_id=None):
            return AgentSession(session_id=session_id, runs=[run])

        # Patch the model-loop stream handler — that's the boundary where the
        # real function body has already applied modifiers. We capture
        # run_response here and exit.
        async def fake_ahandle_stream(agent, *args, run_response=None, run_messages=None, run_context=None, **kw):
            observed["run_response"] = run_response
            return
            yield  # make this an async generator

        monkeypatch.setattr(_init, "has_async_db", lambda agent: False)
        monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create)
        monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
        monkeypatch.setattr(
            _storage, "load_session_state", lambda agent, session=None, session_state=None: session_state or {}
        )
        monkeypatch.setattr(_response, "get_response_format", lambda agent, run_context=None: None)
        monkeypatch.setattr(_tools, "determine_tools_for_model", lambda *a, **kw: [])
        monkeypatch.setattr(_run, "aresolve_run_dependencies", lambda agent, run_context: None)
        monkeypatch.setattr(
            _messages,
            "get_continue_run_messages",
            lambda *a, **kw: type("RM", (), {"messages": []})(),
        )

        import agno.agent._response as response_mod
        from agno.agent._response import ahandle_model_response_stream as _orig  # noqa: F401

        monkeypatch.setattr(response_mod, "ahandle_model_response_stream", fake_ahandle_stream)

        agent = Agent(name="real-stream")
        monkeypatch.setattr(agent, "initialize_agent", lambda debug_mode=None: None)

        # Patch agent.aget_tools so it doesn't traverse the live tool registry
        async def fake_aget_tools(**kwargs):
            return []

        monkeypatch.setattr(agent, "aget_tools", fake_aget_tools)

        async for _ in agent.acontinue_run(
            run_id="run-real",
            session_id="sess-real",
            fork=True,
            continue_from=1,
            stream=True,
        ):
            pass

        # If modifiers fired correctly inside the real function body, the
        # run_response that reached the model-loop handler should be a fork.
        assert "run_response" in observed, "ahandle_model_response_stream was never reached"
        rr = observed["run_response"]
        assert rr.run_id != "run-real", "fork=True did not apply on the real streaming path"
        assert rr.forked_from_run_id == "run-real"
        assert rr.forked_from_message_index == 1
        assert len(rr.messages or []) == 1
