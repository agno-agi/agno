"""Approving a paused run must work for every participant in a Slack thread.

A thread is one session shared by everyone in it, and the session row is owned by
whoever spoke first. Scoping the resume's session read to a second participant's
user id finds no session row, so ``continue_run`` runs against a freshly created
empty session and raises ``No runs found for run ID`` -- silently, from the
approver's point of view: the card flips to "Approved" and the thread gets nothing.

``continue_run`` already recovers the owner from the paused run itself
(``_resolve_continue_owner``), so the interface must leave the scope unset rather
than pre-empt it with a value that describes the run and not the session.
"""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.os.interfaces.slack.hitl import HITLHandler  # noqa: E402
from agno.os.interfaces.slack.interactions import SubmitContext  # noqa: E402


def _submit_context() -> SubmitContext:
    return SubmitContext(
        run_id="run-owned-by-the-second-participant",
        channel="C0THREAD",
        msg_ts="1788500000.100200",
        thread_ts="1788500000.100100",
        awaiting_ts=None,
        user_id="U-SECOND",
        team_id="T0",
        state_values={},
    )


@pytest.mark.asyncio
async def test_resume_does_not_scope_the_session_to_one_participant():
    """The session read must not be narrowed to the run's owner."""
    entity = MagicMock()
    entity.acontinue_run = MagicMock(return_value=AsyncMock())

    handler = HITLHandler.__new__(HITLHandler)
    handler.entity = entity
    handler.entity_name = "pr-agent"
    handler.entity_type = "agent"

    stream = AsyncMock()
    try:
        await handler.stream_resumed_run(
            _submit_context(), stream, [], session_id="pr-agent:C0THREAD:1788500000.100100"
        )
    except Exception:
        # The streaming half is mocked; only the call arguments matter here.
        pass

    assert entity.acontinue_run.called, "the resume must reach continue_run"
    kwargs = entity.acontinue_run.call_args.kwargs
    assert kwargs["session_id"] == "pr-agent:C0THREAD:1788500000.100100"
    assert kwargs["user_id"] is None, (
        "the session read must not be scoped to the run's owner: a thread's session row "
        "belongs to whoever spoke first, so any other participant's approval would find "
        "no session and resume against an empty one"
    )
