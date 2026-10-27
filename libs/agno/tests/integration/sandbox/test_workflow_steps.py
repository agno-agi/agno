"""Sandboxed harness agents as workflow steps, on real Docker and Postgres with the fixture runtime.

Set AGNO_TEST_SANDBOX_DB_URL and AGNO_TEST_RUNTIME_IMAGE to run these.
"""

from agno.db.base import SessionType
from agno.run.base import RunStatus
from agno.workflow import Step, Workflow
from tests.integration.sandbox.test_team_members import pytestmark, setup  # noqa: F401


def test_a_sandboxed_step_keeps_its_computer_across_workflow_runs(setup):  # noqa: F811
    db, agent_of, _ = setup
    engineer = agent_of("engineer")
    workflow = Workflow(id="wf", name="WF", steps=[Step(name="engineer", agent=engineer)], db=db)

    first = workflow.run("first draft", session_id="w1")
    second = workflow.run("second draft", session_id="w1")

    runs = [first.step_executor_runs[0], second.step_executor_runs[0]]
    assert [run.status for run in runs] == [RunStatus.completed, RunStatus.completed]
    assert all(run.session_id == "w1" and run.metadata["sandbox"]["checkpoint"] for run in runs)

    # The workflow keeps its own session; the sandbox keeps its runs and binding in the step's session.
    workflow_session = db.get_session(session_id="w1", session_type=SessionType.WORKFLOW)
    assert [run.run_id for run in workflow_session.runs] == [first.run_id, second.run_id]
    step_session = db.get_session(session_id="w1:engineer", session_type=SessionType.AGENT)
    sandbox_runs = {run.metadata["sandbox"]["run_id"] for run in runs}
    assert sandbox_runs <= {run.run_id for run in step_session.runs}


def test_a_sandboxed_step_still_runs_on_its_own_after_a_workflow_run(setup):  # noqa: F811
    db, agent_of, _ = setup
    engineer = agent_of("engineer")
    Workflow(id="wf", name="WF", steps=[engineer], db=db).run("go", session_id="w1")

    solo = engineer.run("on my own", session_id="solo")

    assert solo.status == RunStatus.completed and solo.session_id == "solo"
    session = db.get_session(session_id="solo", session_type=SessionType.AGENT)
    assert session is not None and solo.run_id in {run.run_id for run in session.runs}
    assert db.get_session(session_id="solo:engineer", session_type=SessionType.AGENT) is None


def test_agentos_gives_a_sandboxed_agent_inside_a_workflow_the_nearest_database(setup):  # noqa: F811
    from agno.os import AgentOS
    from agno.team.team import Team
    from tests.unit.team.test_external_agent_members import _ScriptedModel

    db, agent_of, _ = setup
    step_agent, team_member = agent_of("engineer"), agent_of("reviewer")
    step_agent.db = team_member.db = None
    inner = Team(id="inner", name="Inner", members=[team_member], model=_ScriptedModel([]))
    workflow = Workflow(
        id="wf", name="WF", steps=[Step(name="build", agent=step_agent), Step(name="review", team=inner)], db=db
    )

    AgentOS(id="os", workflows=[workflow], telemetry=False).get_app()

    assert step_agent.db is db and team_member.db is db
