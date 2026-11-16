"""Sandboxed harness agents as workflow steps, on real Docker and Postgres with the fixture runtime.

Set AGNO_TEST_SANDBOX_DB_URL and AGNO_TEST_RUNTIME_IMAGE to run these.
"""

import pytest

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


def test_a_sandboxed_steps_session_links_back_to_its_workflow(setup):  # noqa: F811
    db, agent_of, _ = setup
    engineer = agent_of("engineer")
    Workflow(id="wf", name="WF", steps=[Step(name="engineer", agent=engineer)], db=db).run("go", session_id="w1")

    step_session = db.get_session(session_id="w1:engineer", session_type=SessionType.AGENT)
    assert step_session.metadata == {"workflow_id": "wf"}


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_a_cancel_that_lands_before_the_sandbox_link_still_stops_the_step(setup, stream):  # noqa: F811
    """The workflow cancelled the step's run before the step linked it to its sandbox run."""
    from agno.run.cancel import acancel_run

    db, agent_of, _ = setup
    engineer = agent_of("engineer")
    await acancel_run("step-run-1")

    options = dict(session_id="w1", run_id="step-run-1", _workflow_id="wf")
    if stream:
        items = [item async for item in engineer.arun("go", stream=True, yield_run_output=True, **options)]
        output = items[-1]
        assert getattr(items[-2], "event", None) == "RunCancelled"
    else:
        output = await engineer.arun("go", **options)

    assert output.status == RunStatus.cancelled and output.run_id == "step-run-1"
    step_session = db.get_session(session_id="w1:engineer", session_type=SessionType.AGENT)
    assert step_session is None or not [run for run in step_session.runs if run.status == RunStatus.completed]


def test_agentos_gives_sandboxed_agents_in_a_workflow_postgres_when_their_owners_use_another_database(setup):  # noqa: F811
    from agno.db.sqlite import SqliteDb
    from agno.os import AgentOS
    from agno.team.team import Team
    from tests.unit.team.test_external_agent_members import _ScriptedModel

    db, agent_of, tmp_path = setup
    step_agent, team_member = agent_of("engineer"), agent_of("reviewer")
    step_agent.db = team_member.db = None
    inner = Team(
        id="inner",
        name="Inner",
        members=[team_member],
        model=_ScriptedModel([]),
        db=SqliteDb(db_file=str(tmp_path / "team.db")),
    )
    workflow = Workflow(
        id="wf",
        name="WF",
        steps=[Step(name="build", agent=step_agent), Step(name="review", team=inner)],
        db=SqliteDb(db_file=str(tmp_path / "workflow.db")),
    )

    AgentOS(id="os", db=db, workflows=[workflow], telemetry=False).get_app()

    assert step_agent.db is db and team_member.db is db


def test_agentos_prepares_sandboxed_agents_in_a_nested_router_choice(setup):  # noqa: F811
    from agno.os import AgentOS
    from agno.workflow import Router

    db, agent_of, _ = setup
    first, second = agent_of("engineer"), agent_of("reviewer")
    first.db = second.db = None
    workflow = Workflow(
        id="wf",
        name="WF",
        steps=[Router(name="route", selector=lambda step_input: [], choices=[Step(name="a", agent=first), [second]])],
    )

    AgentOS(id="os", db=db, workflows=[workflow], telemetry=False).get_app()

    assert first.db is db and second.db is db
