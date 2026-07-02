"""Regression tests for ``WorkflowSession.get_messages`` on team runs (#8658).

Pre-fix, ``get_messages_from_team_runs`` only assigned ``session_runs`` inside
``if skip_member_messages:``, so calling ``get_messages(..., team_id=...,
skip_member_messages=False)`` hit ``UnboundLocalError`` on the next reference
to ``session_runs`` (either the ``skip_statuses`` filter, the ``limit is not
None`` collection loop, or the ``last_n_runs`` slice).

The fix initializes ``session_runs = runs`` before the optional filters. The
sibling ``TeamSession`` implementation in ``session/team.py`` already does this.
"""

from agno.models.message import Message
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session.workflow import WorkflowSession


def _build_session_with_team_run() -> WorkflowSession:
    """Session containing a workflow run whose step executor is a completed team run."""
    top_team_run = TeamRunOutput(
        run_id="run-top",
        team_id="team-1",
        parent_run_id=None,
        messages=[
            Message(role="system", content="system prompt"),
            Message(role="user", content="hello team"),
            Message(role="assistant", content="team reply"),
        ],
        status=RunStatus.completed,
    )
    wf_run = WorkflowRunOutput(
        run_id="wf-run-1",
        workflow_id="wf-1",
        session_id="sess-1",
        step_executor_runs=[top_team_run],
    )
    return WorkflowSession(
        session_id="sess-1",
        workflow_id="wf-1",
        runs=[wf_run],
        session_data={},
    )


def test_get_messages_with_skip_member_messages_false_does_not_raise():
    """Repro for #8658: no UnboundLocalError when include-members flag is False."""
    session = _build_session_with_team_run()

    messages = session.get_messages(team_id="team-1", skip_member_messages=False)

    assert isinstance(messages, list)
    contents = [m.content for m in messages]
    assert "hello team" in contents


def test_get_messages_with_skip_member_messages_false_and_skip_statuses():
    """The ``skip_statuses`` filter references ``session_runs`` on the next line.

    Pre-fix, this combination hit the UnboundLocalError even faster than the
    limit/last_n_runs branches, since the ``skip_statuses`` filter runs
    unconditionally when ``skip_statuses`` is truthy.
    """
    session = _build_session_with_team_run()

    messages = session.get_messages(
        team_id="team-1",
        skip_member_messages=False,
        skip_statuses=[RunStatus.error],
    )

    assert isinstance(messages, list)
    contents = [m.content for m in messages]
    assert "hello team" in contents


def test_get_messages_with_skip_member_messages_false_and_limit():
    """The ``limit`` collection loop iterates ``session_runs`` directly.

    Pre-fix, this branch hit UnboundLocalError inside the ``for run_response in
    session_runs`` loop when ``skip_member_messages=False``.
    """
    session = _build_session_with_team_run()

    messages = session.get_messages(
        team_id="team-1",
        skip_member_messages=False,
        limit=2,
    )

    assert isinstance(messages, list)
    assert len(messages) <= 2


def test_get_messages_with_skip_member_messages_true_still_works():
    """Baseline: the ``skip_member_messages=True`` path (which set ``session_runs``
    itself pre-fix) must keep working with the initialization moved earlier."""
    session = _build_session_with_team_run()

    messages = session.get_messages(team_id="team-1", skip_member_messages=True)

    assert isinstance(messages, list)
    contents = [m.content for m in messages]
    assert "hello team" in contents


def test_get_messages_with_last_n_runs_and_skip_member_messages_false():
    """Fourth site that referenced ``session_runs`` pre-fix — the ``last_n_runs``
    slice inside the ``limit is None`` branch."""
    session = _build_session_with_team_run()

    messages = session.get_messages(
        team_id="team-1",
        skip_member_messages=False,
        last_n_runs=1,
    )

    assert isinstance(messages, list)
    contents = [m.content for m in messages]
    assert "hello team" in contents
