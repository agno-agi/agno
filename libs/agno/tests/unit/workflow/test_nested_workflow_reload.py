"""A nested workflow without a name must survive a session reload."""

from agno.db.sqlite import SqliteDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.workflow import Step, Workflow
from agno.workflow.types import StepInput, StepOutput


def echo(step_input: StepInput) -> StepOutput:
    return StepOutput(content=str(step_input.input))


def test_step_executor_runs_round_trip_by_type():
    run = WorkflowRunOutput(
        run_id="parent",
        workflow_id="parent",
        step_executor_runs=[
            RunOutput(run_id="agent-run", agent_id="agent", workflow_id="parent", parent_run_id="parent"),
            TeamRunOutput(run_id="team-run", team_id="team", parent_run_id="parent"),
            WorkflowRunOutput(run_id="child-run", workflow_id="child", parent_run_id="parent", input="draft"),
        ],
    )

    restored = WorkflowRunOutput.from_dict(run.to_dict())

    assert [type(executor_run) for executor_run in restored.step_executor_runs or []] == [
        RunOutput,
        TeamRunOutput,
        WorkflowRunOutput,
    ]


def test_unnamed_nested_workflow_session_reloads(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "sessions.db"))
    child = Workflow(id="child", db=db, telemetry=False, steps=[Step(name="Draft", executor=echo)])
    parent = Workflow(id="parent", db=db, telemetry=False, steps=[Step(name="Child", workflow=child)])

    parent.run(input="first", session_id="session")
    second = parent.run(input="second", session_id="session")

    assert second.status == RunStatus.completed
    session = parent.get_session(session_id="session")
    assert session is not None
    nested_runs = [
        executor_run for workflow_run in session.runs or [] for executor_run in workflow_run.step_executor_runs or []
    ]
    assert nested_runs and all(isinstance(executor_run, WorkflowRunOutput) for executor_run in nested_runs)
