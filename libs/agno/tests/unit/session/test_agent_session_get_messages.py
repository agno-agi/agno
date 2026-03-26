"""Unit tests for AgentSession.get_messages() to verify PAUSED runs are included in history.

Regression test for: https://github.com/agno-agi/agno/issues/7161
"""

from dataclasses import dataclass, field
from typing import List, Optional

import pytest

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


def _make_run(
    run_id: str,
    status: RunStatus,
    messages: Optional[List[Message]] = None,
    parent_run_id: Optional[str] = None,
) -> RunOutput:
    """Helper to create a minimal RunOutput for testing."""
    run = RunOutput(run_id=run_id, session_id="test-session")
    run.status = status
    run.messages = messages or []
    run.parent_run_id = parent_run_id
    return run


def _make_message(role: str, content: str) -> Message:
    return Message(role=role, content=content)


class TestGetMessagesDefaultSkipStatuses:
    """Tests for the default skip_statuses behaviour in AgentSession.get_messages()."""

    def test_paused_run_messages_included_by_default(self):
        """PAUSED runs must be included in history by default (fix for #7161).

        When add_history_to_context=True the agent calls get_messages() without
        explicit skip_statuses. Previously RunStatus.paused was in the default
        exclusion list, so all messages from paused sessions were silently dropped.
        """
        paused_run = _make_run(
            run_id="run-paused",
            status=RunStatus.paused,
            messages=[
                _make_message("user", "Hello, what is the weather?"),
                _make_message("assistant", "I'll check that for you."),
            ],
        )
        session = AgentSession(session_id="s1", runs=[paused_run])

        messages = session.get_messages()

        roles_and_content = [(m.role, m.content) for m in messages]
        assert ("user", "Hello, what is the weather?") in roles_and_content
        assert ("assistant", "I'll check that for you.") in roles_and_content

    def test_cancelled_run_messages_excluded_by_default(self):
        """CANCELLED runs must still be excluded from history by default."""
        cancelled_run = _make_run(
            run_id="run-cancelled",
            status=RunStatus.cancelled,
            messages=[_make_message("user", "This was cancelled")],
        )
        session = AgentSession(session_id="s2", runs=[cancelled_run])

        messages = session.get_messages()

        assert messages == []

    def test_error_run_messages_excluded_by_default(self):
        """ERROR runs must still be excluded from history by default."""
        error_run = _make_run(
            run_id="run-error",
            status=RunStatus.error,
            messages=[_make_message("user", "This errored")],
        )
        session = AgentSession(session_id="s3", runs=[error_run])

        messages = session.get_messages()

        assert messages == []

    def test_completed_run_messages_included_by_default(self):
        """Completed (running/success) runs must be included."""
        completed_run = _make_run(
            run_id="run-ok",
            status=RunStatus.running,
            messages=[_make_message("user", "Normal message")],
        )
        session = AgentSession(session_id="s4", runs=[completed_run])

        messages = session.get_messages()

        assert any(m.content == "Normal message" for m in messages)

    def test_mixed_runs_paused_included_others_excluded(self):
        """In a session with mixed statuses only PAUSED and completed runs contribute."""
        paused_run = _make_run(
            run_id="run-paused",
            status=RunStatus.paused,
            messages=[_make_message("user", "Paused user msg")],
        )
        cancelled_run = _make_run(
            run_id="run-cancelled",
            status=RunStatus.cancelled,
            messages=[_make_message("user", "Cancelled user msg")],
        )
        error_run = _make_run(
            run_id="run-error",
            status=RunStatus.error,
            messages=[_make_message("user", "Error user msg")],
        )
        ok_run = _make_run(
            run_id="run-ok",
            status=RunStatus.running,
            messages=[_make_message("user", "Ok user msg")],
        )
        session = AgentSession(session_id="s5", runs=[paused_run, cancelled_run, error_run, ok_run])

        messages = session.get_messages()
        contents = [m.content for m in messages]

        assert "Paused user msg" in contents, "PAUSED run messages should be in history"
        assert "Ok user msg" in contents, "Completed run messages should be in history"
        assert "Cancelled user msg" not in contents, "CANCELLED run messages should not be in history"
        assert "Error user msg" not in contents, "ERROR run messages should not be in history"

    def test_explicit_skip_statuses_overrides_default(self):
        """Caller can still explicitly exclude PAUSED runs by passing skip_statuses."""
        paused_run = _make_run(
            run_id="run-paused",
            status=RunStatus.paused,
            messages=[_make_message("user", "Should be excluded explicitly")],
        )
        session = AgentSession(session_id="s6", runs=[paused_run])

        # Caller explicitly opts out of paused runs
        messages = session.get_messages(skip_statuses=[RunStatus.paused, RunStatus.cancelled, RunStatus.error])

        assert messages == []

    def test_agui_resume_workflow_preserves_context(self):
        """Simulate AG-UI external-execution workflow: agent pauses → resumes.

        The resumed turn must see the full conversation history from the
        paused run, not an empty context.
        """
        # First turn — agent starts and pauses waiting for an external tool result
        paused_run = _make_run(
            run_id="run-turn-1",
            status=RunStatus.paused,
            messages=[
                _make_message("user", "Book a flight to Paris"),
                _make_message("assistant", "I need to check availability first."),
            ],
        )
        session = AgentSession(session_id="agui-session", runs=[paused_run])

        # On resume the agent fetches history — must include the paused run's messages
        history_messages = session.get_messages()

        content_set = {m.content for m in history_messages}
        assert "Book a flight to Paris" in content_set
        assert "I need to check availability first." in content_set
