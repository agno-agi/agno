"""Regression tests for ``WorkflowSession.get_messages`` on team runs (#8658).

Two bugs covered here:

1. ``get_messages_from_team_runs`` only assigned ``session_runs`` inside
   ``if skip_member_messages:``, so calling ``get_messages(..., team_id=...,
   skip_member_messages=False)`` hit ``UnboundLocalError`` on the next reference
   to ``session_runs``.
2. ``skip_member_messages`` was a silent no-op — passing ``True`` or ``False``
   returned identical messages, because the caller in ``get_messages``
   pre-filtered ``step_executor_runs`` by ``team_id`` (so member sub-runs never
   reached the helper), and the Stage 2 filter in the helper then keyed on
   ``team_id == team_id`` — a no-op on already-filtered data.

Fixes:

- ``session_runs = runs`` is initialised upfront in the helper.
- The caller now walks ``TeamRunOutput.member_responses`` when
  ``skip_member_messages=False`` so member sub-runs are included in the list
  passed to the helper.
- The helper no longer filters on ``team_id``/``parent_run_id`` — the caller
  already decides the correct set. (Filtering on ``parent_run_id is None``
  would drop everything, because in a workflow context even the top-level
  team executor has a ``parent_run_id`` pointing at the enclosing workflow
  run.)
"""

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session.workflow import WorkflowSession


def _build_session_with_team_run() -> WorkflowSession:
    """Session with a workflow run whose step executor is a top-level team run.

    Shape mirrors what the runtime produces: the top-level team executor's
    ``parent_run_id`` points at the enclosing workflow run (not None).
    """
    top_team_run = TeamRunOutput(
        run_id="run-top",
        team_id="team-1",
        parent_run_id="wf-run-1",  # real workflows populate this
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


def _build_session_with_team_and_members() -> WorkflowSession:
    """Session with a top-level team run plus two agent member sub-runs.

    Member sub-runs live in ``TeamRunOutput.member_responses`` with
    ``parent_run_id`` pointing at the top-level team run.
    """
    member_a = RunOutput(
        run_id="run-agent-a",
        agent_id="agent-a",
        parent_run_id="run-top",
        messages=[Message(role="assistant", content="member A reply")],
        status=RunStatus.completed,
    )
    member_b = RunOutput(
        run_id="run-agent-b",
        agent_id="agent-b",
        parent_run_id="run-top",
        messages=[Message(role="assistant", content="member B reply")],
        status=RunStatus.completed,
    )
    top_team_run = TeamRunOutput(
        run_id="run-top",
        team_id="team-1",
        parent_run_id="wf-run-1",
        messages=[
            Message(role="user", content="hello team"),
            Message(role="assistant", content="team reply"),
        ],
        member_responses=[member_a, member_b],
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


# ---------------------------------------------------------------------------
# Semantic tests for bug 2: skip_member_messages must actually change output
# ---------------------------------------------------------------------------


def test_skip_member_messages_true_excludes_member_messages():
    """``skip_member_messages=True`` (default) returns only top-level team messages.

    Pre-fix (bug 2), this returned the correct result by accident — the caller
    pre-filtered on ``team_id``, so member sub-runs never entered the pipeline.
    Post-fix the caller still excludes member sub-runs on this path, so
    behavior is unchanged.
    """
    session = _build_session_with_team_and_members()

    messages = session.get_messages(team_id="team-1", skip_member_messages=True)
    contents = [m.content for m in messages]

    assert "hello team" in contents
    assert "team reply" in contents
    assert "member A reply" not in contents
    assert "member B reply" not in contents


def test_skip_member_messages_false_includes_member_messages():
    """``skip_member_messages=False`` returns top-level + member messages.

    Pre-fix (bug 2), this returned the SAME result as ``True`` — the flag was
    silently ignored. Post-fix, the caller walks ``member_responses`` when
    the flag is False, so member agents' messages appear alongside the
    top-level team's messages.
    """
    session = _build_session_with_team_and_members()

    messages = session.get_messages(team_id="team-1", skip_member_messages=False)
    contents = [m.content for m in messages]

    assert "hello team" in contents
    assert "team reply" in contents
    assert "member A reply" in contents
    assert "member B reply" in contents


def test_skip_member_messages_true_and_false_differ():
    """Pins the semantic invariant: True and False must produce different output.

    Pre-fix (bug 2), the two calls returned identical results. This test is
    the direct regression guard for that no-op behavior.
    """
    session = _build_session_with_team_and_members()

    with_members = session.get_messages(team_id="team-1", skip_member_messages=False)
    without_members = session.get_messages(team_id="team-1", skip_member_messages=True)

    assert len(with_members) > len(without_members), (
        f"skip_member_messages=False should surface more messages than True "
        f"(got {len(with_members)} vs {len(without_members)}). "
        f"If equal, the flag is a silent no-op (bug 2 of #8658)."
    )
