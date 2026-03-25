"""Tests for AgentSession.get_messages() skip_statuses behavior."""

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


def _make_run(run_id: str, status: RunStatus, messages: list[Message]) -> RunOutput:
    """Helper to create a RunOutput with the given status and messages."""
    run = RunOutput(run_id=run_id, agent_id="test-agent", parent_run_id=None)
    run.status = status
    run.messages = messages
    return run


def test_paused_runs_included_in_history():
    """PAUSED runs should NOT be skipped by default in get_messages().

    Regression test for https://github.com/agno-agi/agno/issues/7161:
    When using add_history_to_context=True with external execution tools,
    PAUSED runs contain valid conversation context that must be preserved
    when the session is resumed.
    """
    paused_messages = [
        Message(role="user", content="What is the weather?"),
        Message(role="assistant", content="Let me check the weather for you."),
    ]
    completed_messages = [
        Message(role="user", content="Thanks!"),
        Message(role="assistant", content="You're welcome!"),
    ]

    session = AgentSession(
        session_id="test-session",
        runs=[
            _make_run("run-1", RunStatus.paused, paused_messages),
            _make_run("run-2", RunStatus.completed, completed_messages),
        ],
    )

    messages = session.get_messages()

    # All messages from both PAUSED and COMPLETED runs should be present
    contents = [m.content for m in messages]
    assert "What is the weather?" in contents
    assert "Let me check the weather for you." in contents
    assert "Thanks!" in contents
    assert "You're welcome!" in contents
    assert len(messages) == 4


def test_cancelled_and_error_runs_still_skipped():
    """CANCELLED and ERROR runs should still be skipped by default."""
    session = AgentSession(
        session_id="test-session",
        runs=[
            _make_run(
                "run-cancelled",
                RunStatus.cancelled,
                [Message(role="user", content="cancelled msg")],
            ),
            _make_run(
                "run-error",
                RunStatus.error,
                [Message(role="user", content="error msg")],
            ),
            _make_run(
                "run-ok",
                RunStatus.completed,
                [Message(role="user", content="good msg")],
            ),
        ],
    )

    messages = session.get_messages()

    contents = [m.content for m in messages]
    assert "cancelled msg" not in contents
    assert "error msg" not in contents
    assert "good msg" in contents
    assert len(messages) == 1


def test_explicit_skip_paused_still_works():
    """Callers can still explicitly skip PAUSED runs if desired."""
    session = AgentSession(
        session_id="test-session",
        runs=[
            _make_run(
                "run-paused",
                RunStatus.paused,
                [Message(role="user", content="paused msg")],
            ),
            _make_run(
                "run-ok",
                RunStatus.completed,
                [Message(role="user", content="good msg")],
            ),
        ],
    )

    messages = session.get_messages(skip_statuses=[RunStatus.paused, RunStatus.cancelled, RunStatus.error])

    contents = [m.content for m in messages]
    assert "paused msg" not in contents
    assert "good msg" in contents
    assert len(messages) == 1
