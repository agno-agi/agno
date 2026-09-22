"""A workflow session's runs are its own top-level runs.

The runs table keys every run by session_id, and a step's agent/team run shares the
workflow's session id, so the read hands those back too. Deserializing one as a
WorkflowRunOutput raises on its metrics (no "steps") or, when it has none, mints a
phantom workflow run carrying the member's content.
"""

from agno.run.base import RunStatus
from agno.run.workflow import WorkflowRunOutput
from agno.session.workflow import WorkflowSession

WORKFLOW_RUN = {
    "run_id": "wf-1",
    "workflow_id": "wf",
    "workflow_name": "WfHitl",
    "session_id": "s1",
    "status": "PAUSED",
    "metrics": {"steps": {}, "duration": 1.0},
}
MEMBER_AGENT_RUN = {
    "run_id": "ag-1",
    "agent_id": "deployer",
    "agent_name": "Deployer",
    "session_id": "s1",
    "status": "PAUSED",
    "content": "deployed",
    "metrics": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
}
MEMBER_TEAM_RUN = {
    "run_id": "tm-1",
    "team_id": "squad",
    "team_name": "Squad",
    "session_id": "s1",
    "status": "COMPLETED",
}


def _session(runs):
    return WorkflowSession.from_dict({"session_id": "s1", "workflow_id": "wf", "runs": runs})


class TestWorkflowSessionRuns:
    def test_member_agent_run_is_not_a_session_run(self):
        session = _session([WORKFLOW_RUN, MEMBER_AGENT_RUN])
        assert [r.run_id for r in session.runs] == ["wf-1"]

    def test_member_team_run_is_not_a_session_run(self):
        session = _session([WORKFLOW_RUN, MEMBER_TEAM_RUN])
        assert [r.run_id for r in session.runs] == ["wf-1"]

    def test_a_member_run_without_metrics_does_not_become_a_phantom_workflow_run(self):
        # This one never raised -- it minted a workflow run carrying the member's content.
        no_metrics = {k: v for k, v in MEMBER_AGENT_RUN.items() if k != "metrics"}
        session = _session([WORKFLOW_RUN, no_metrics])
        assert [r.run_id for r in session.runs] == ["wf-1"]
        assert all(r.workflow_id == "wf" for r in session.runs)

    def test_the_workflows_own_runs_are_all_kept(self):
        second = {**WORKFLOW_RUN, "run_id": "wf-2", "status": "COMPLETED"}
        session = _session([WORKFLOW_RUN, second])
        assert [r.run_id for r in session.runs] == ["wf-1", "wf-2"]

    def test_a_paused_run_is_still_a_session_run(self):
        session = _session([WORKFLOW_RUN])
        assert [r.status for r in session.runs] == ["PAUSED"]


class TestMemberRunIdentifiedByNameAlone:
    """A member run persisted without its id still identifies itself by name."""

    def test_agent_run_with_only_a_name_is_not_a_session_run(self):
        by_name = {"run_id": "ag-2", "agent_name": "Deployer", "session_id": "s1", "content": "x"}
        session = _session([WORKFLOW_RUN, by_name])
        assert [r.run_id for r in session.runs] == ["wf-1"]

    def test_team_run_with_only_a_name_is_not_a_session_run(self):
        by_name = {"run_id": "tm-2", "team_name": "Squad", "session_id": "s1"}
        session = _session([WORKFLOW_RUN, by_name])
        assert [r.run_id for r in session.runs] == ["wf-1"]


def test_workflow_history_includes_unverified_runs():
    """History is an include-list: completed and unverified runs both carry a real
    transcript; error/cancelled runs stay excluded. num_runs slices the filtered list,
    so an unverified run occupies a slot."""
    session = WorkflowSession(
        session_id="session-1",
        runs=[
            WorkflowRunOutput(input="q1", content="a1", status=RunStatus.completed),
            WorkflowRunOutput(input="q2", content="a2", status=RunStatus.unverified),
            WorkflowRunOutput(input="q3", content="a3", status=RunStatus.error),
            WorkflowRunOutput(input="q4", content="a4", status=RunStatus.cancelled),
        ],
    )
    assert session.get_workflow_history() == [("q1", "a1"), ("q2", "a2")]
    assert session.get_workflow_history(num_runs=1) == [("q2", "a2")]
