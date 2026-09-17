"""Confirms the Team side has the same history-duplication shape as the bug fixed
for Agent in #10088 (session-level fix) / #10086 (issue).

For Agent, ``_build_continue_run_messages`` (agent/_messages.py) accepts a
``current_run_id`` and threads it into ``AgentSession.get_messages(exclude_run_ids=...)``,
so the run currently being continued is excluded from its own history lookup by
identity, regardless of what status it was persisted under mid-continue.

Team has neither half of that fix:

- ``team/_run.py``'s ``_build_continue_run_messages`` takes no ``current_run_id``
  parameter at all (unlike its agent counterpart).
- ``TeamSession.get_messages`` (session/team.py) has no ``exclude_run_ids``
  parameter to accept one even if a caller had it.

So a Team run that gets persisted RUNNING/PENDING (for visibility) before its own
history is rebuilt -- exactly what Agent's ``_acontinue_run_background_stream`` does,
and what Team's own ``_acontinue_run_background_stream`` also does at
``persist_run.status = RunStatus.pending`` -- has no mechanism to be excluded from
its own history lookup. Only the status-based filter applies, and by the time
history is rebuilt the run no longer matches it.

This test does not exercise the full background+stream continue pipeline (that
requires the same heavy end-to-end setup as the Agent integration tests); it proves
the missing building block directly: unlike ``AgentSession.get_messages``,
``TeamSession.get_messages`` has no way to drop a run by identity, so a run
mid-continue (status flipped away from PAUSED) cannot be excluded from its own
history no matter what the caller wants.
"""

import inspect

from agno.models.message import Message
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession

CONTINUED_RUN_ID = "team-run-continued"
CONTINUED_TOOL_CALL_ID = "tc-continued"


def _team_tool_call_run(run_id: str, tool_call_id: str, status: RunStatus) -> TeamRunOutput:
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


def test_team_session_get_messages_has_no_identity_based_exclusion():
    """AgentSession.get_messages grew an ``exclude_run_ids`` parameter as part of
    #10088; TeamSession.get_messages never did. If this starts failing, Team has
    caught up with Agent and the reproduction below (and the missing
    ``current_run_id`` param on team/_run.py's ``_build_continue_run_messages``)
    should be revisited together."""
    params = inspect.signature(TeamSession.get_messages).parameters
    assert "exclude_run_ids" not in params, (
        "TeamSession.get_messages now supports exclude_run_ids -- the Team-side "
        "counterpart to #10088 may already be in place; re-check "
        "team/_run.py's _build_continue_run_messages for a current_run_id param too."
    )


def test_run_flipped_to_running_mid_continue_is_not_excluded_from_its_own_history():
    """Reproduces the root cause of #10086 at the Team layer: a run persisted
    RUNNING (for visibility) while it is being continued no longer matches
    HISTORY_SKIP_STATUSES (paused/cancelled/error/regenerated), and -- unlike
    Agent post-#10088 -- there is no exclude_run_ids fallback to catch it by
    identity. get_messages() pulls it straight back into "history"."""
    continued_run = _team_tool_call_run(CONTINUED_RUN_ID, CONTINUED_TOOL_CALL_ID, RunStatus.running)
    session = TeamSession(session_id="session-1", team_id="team-1", runs=[continued_run])

    # Default skip_statuses (HISTORY_SKIP_STATUSES) is the only filter available --
    # there is no run-id parameter to ask for exclusion by identity instead.
    messages = session.get_messages()

    tool_call_turns = [
        m
        for m in messages
        if m.role == "assistant" and m.tool_calls and any(tc.get("id") == CONTINUED_TOOL_CALL_ID for tc in m.tool_calls)
    ]
    assert len(tool_call_turns) == 1, (
        "the run being continued was NOT filtered out of its own history -- if this "
        "same run's messages are also supplied via the continue call's own `input` "
        "(the normal, correct path), the assistant's tool_calls turn reaches the "
        "model twice, reproducing #10086 at the Team layer"
    )
