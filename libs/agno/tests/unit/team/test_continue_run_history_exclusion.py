"""Unit tests for the message list built when continuing a paused Team run.

Team-side counterpart to agent/tests/unit/agent/test_continue_run_history_exclusion.py.
Same root cause as #10086: a run continuing in the background is persisted RUNNING
(for visibility) before its own messages are rebuilt for the model call --
``TeamSession.get_messages`` only excluded PAUSED/CANCELLED/ERROR/REGENERATED runs from
history, so by the time history is rebuilt the run being continued no longer matches
that exclusion and re-enters its own history as a phantom duplicate of the turn already
supplied via the caller's own input.

These tests assert on the built message list itself, not on a provider error or a
terminal run status, and are parametrized over every persisted status of the continued
run so that any writer that changes status mid-request trips them.
"""

import pytest

from agno.models.message import Message
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team._run import _build_continue_run_messages
from agno.team.team import Team

CONTINUED_RUN_ID = "team-run-continued"
CONTINUED_TOOL_CALL_ID = "tc-continued"
PRIOR_RUN_ID = "team-run-prior"
PRIOR_TOOL_CALL_ID = "tc-prior"


def _tool_call_run(run_id: str, tool_call_id: str, status: RunStatus) -> TeamRunOutput:
    """A team run whose assistant turn issued one tool call that got a tool result."""
    return TeamRunOutput(
        run_id=run_id,
        status=status,
        parent_run_id=None,
        messages=[
            Message(role="system", content="You are a helpful team."),
            Message(role="user", content="do the external-execution thing"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {"name": "external_tool", "arguments": "{}"},
                    }
                ],
            ),
            Message(role="tool", content="ok", tool_call_id=tool_call_id),
        ],
    )


def _assistant_turns_with_tool_call(messages, tool_call_id: str):
    return [
        m
        for m in messages
        if m.role == "assistant" and m.tool_calls and any(tc.get("id") == tool_call_id for tc in m.tool_calls)
    ]


def _build_messages(continued_status: RunStatus):
    team = Team(members=[], add_history_to_context=True)
    prior_run = _tool_call_run(PRIOR_RUN_ID, PRIOR_TOOL_CALL_ID, RunStatus.completed)
    continued_run = _tool_call_run(CONTINUED_RUN_ID, CONTINUED_TOOL_CALL_ID, continued_status)
    session = TeamSession(session_id="session-1", team_id=team.id, runs=[prior_run, continued_run])

    # The continue path passes the continued run's own messages as ``input``.
    run_messages = _build_continue_run_messages(
        team,
        input=list(continued_run.messages or []),
        session=session,
        add_history_to_context=True,
        current_run_id=CONTINUED_RUN_ID,
    )
    return run_messages.messages


@pytest.mark.parametrize("continued_status", list(RunStatus), ids=[s.value for s in RunStatus])
def test_continued_run_appears_exactly_once_regardless_of_persisted_status(continued_status: RunStatus):
    messages = _build_messages(continued_status)

    turns = _assistant_turns_with_tool_call(messages, CONTINUED_TOOL_CALL_ID)
    assert len(turns) == 1, [m.role for m in messages]


@pytest.mark.parametrize("continued_status", list(RunStatus), ids=[s.value for s in RunStatus])
def test_prior_run_history_is_kept_when_continuing(continued_status: RunStatus):
    messages = _build_messages(continued_status)

    turns = _assistant_turns_with_tool_call(messages, PRIOR_TOOL_CALL_ID)
    assert len(turns) == 1, [m.role for m in messages]


@pytest.mark.parametrize("excluded_status", list(RunStatus), ids=[s.value for s in RunStatus])
def test_get_messages_exclude_run_ids_drops_run_by_identity(excluded_status: RunStatus):
    prior_run = _tool_call_run(PRIOR_RUN_ID, PRIOR_TOOL_CALL_ID, RunStatus.completed)
    excluded_run = _tool_call_run(CONTINUED_RUN_ID, CONTINUED_TOOL_CALL_ID, excluded_status)
    session = TeamSession(session_id="session-1", runs=[prior_run, excluded_run])

    # Pass an empty skip_statuses so only the identity filter can remove the run.
    messages = session.get_messages(skip_statuses=[], exclude_run_ids=[CONTINUED_RUN_ID])

    assert _assistant_turns_with_tool_call(messages, CONTINUED_TOOL_CALL_ID) == []
    assert len(_assistant_turns_with_tool_call(messages, PRIOR_TOOL_CALL_ID)) == 1
