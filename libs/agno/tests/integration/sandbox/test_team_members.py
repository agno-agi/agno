"""Sandboxed harness agents as team members, on real Docker and Postgres with the fixture runtime.

The leader runs on a scripted model that delegates by tool call. Each sandboxed member runs its
turns on its own session, derived from the team's, so its computer binding and checkpoints are
its own; the team stores the member runs in the team session.
"""

import os
import subprocess
from uuid import uuid4

import pytest
from sqlalchemy import text

from agno.db.base import SessionType
from agno.db.postgres import PostgresDb
from agno.run.base import RunStatus
from agno.sandbox.checkpoint import CheckpointArchive, FileCheckpointStore
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.fixture import FixtureAgent
from agno.team.team import Team
from tests.unit.team.test_external_agent_members import _delegate, _ScriptedModel

URL, IMAGE = os.environ.get("AGNO_TEST_SANDBOX_DB_URL"), os.environ.get("AGNO_TEST_RUNTIME_IMAGE")
SUBNET = os.environ.get("AGNO_TEST_SANDBOX_SUBNET", "172.30.0.0/22")
pytestmark = pytest.mark.skipif(not URL or not IMAGE, reason="Enable real Postgres and runtime image")


@pytest.fixture
def setup(tmp_path):
    suffix = uuid4().hex[:12]
    db = PostgresDb(
        db_url=URL,
        session_table="tm_sessions_" + suffix,
        runs_table="tm_runs_" + suffix,
        sandbox_table="tm_bindings_" + suffix,
    )
    namespace = "team-members-" + suffix

    def member(member_id: str) -> FixtureAgent:
        sandbox = DockerSandbox(
            IMAGE,
            namespace=namespace,
            memory_mb=512,
            workspace_mb=32,
            subnet=SUBNET,
            env={"AGNO_SANDBOX_TEST_RUNTIME": "1"},
            checkpoints=FileCheckpointStore(tmp_path / "checkpoints"),
        )
        return FixtureAgent(id=member_id, name=member_id.title(), db=db, sandbox=sandbox)

    yield db, member, tmp_path
    containers = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=io.agno.sandbox.namespace=" + namespace],
        capture_output=True,
        text=True,
    ).stdout.split()
    if containers:
        subprocess.run(["docker", "rm", "-f", *containers], capture_output=True)
    with db.db_engine.begin() as connection:
        for table in ("tm_bindings_", "tm_runs_", "tm_sessions_"):
            connection.execute(text(f'DROP TABLE IF EXISTS "{db.db_schema}"."{table}{suffix}" CASCADE'))
    db.db_engine.dispose()


def test_a_sandboxed_member_runs_team_turns_on_its_own_computer_and_session(setup):
    db, member_of, tmp_path = setup
    engineer = member_of("engineer")
    team = Team(
        id="team",
        name="Team",
        members=[engineer],
        model=_ScriptedModel(
            [
                _delegate("engineer", "first draft", "c1"),
                ("content", "done"),
                _delegate("engineer", "second draft", "c2"),
                ("content", "done"),
            ]
        ),
        db=db,
    )
    first = team.run("go", session_id="s1")
    second = team.run("again", session_id="s1")

    runs = [first.member_responses[0], second.member_responses[0]]
    assert [run.status for run in runs] == [RunStatus.completed, RunStatus.completed]
    assert all(run.session_id == "s1" and run.metadata["sandbox"]["checkpoint"] for run in runs)

    # The second turn's checkpoint holds both turns: the member's computer and session carried on.
    with engineer.open_run_checkpoint(runs[1].run_id) as archive:
        CheckpointArchive().restore(archive, tmp_path / "restored")
    effects = (tmp_path / "restored" / "workspace" / "fixture-effects.txt").read_text().split()
    sandbox_runs = [run.metadata["sandbox"]["run_id"] for run in runs]
    assert effects == sandbox_runs == [f"{run.run_id}.sandbox" for run in runs]

    # The team stores the member results in its session under the ids it assigned; the sandbox keeps
    # its own run records, binding and checkpoints in the member's session. Neither row moves.
    team_session = db.get_session(session_id="s1", session_type=SessionType.TEAM)
    assert {run.run_id for run in runs} <= {run.run_id for run in team_session.runs}
    member_session = db.get_session(session_id="s1:engineer", session_type=SessionType.AGENT)
    assert set(sandbox_runs) <= {run.run_id for run in member_session.runs}


def test_a_sandboxed_member_still_runs_on_its_own_after_a_team_run(setup):
    db, member_of, _ = setup
    engineer = member_of("engineer")
    team = Team(
        id="team",
        name="Team",
        members=[engineer],
        model=_ScriptedModel([_delegate("engineer", "draft", "c1"), ("content", "done")]),
        db=db,
    )
    team.run("go", session_id="s1")

    # The same instance, as AgentOS serves it, runs a standalone turn in the session it was given.
    solo = engineer.run("on my own", session_id="solo")

    assert solo.status == RunStatus.completed and solo.session_id == "solo"
    session = db.get_session(session_id="solo", session_type=SessionType.AGENT)
    assert session is not None and solo.run_id in {run.run_id for run in session.runs}
    assert db.get_session(session_id="solo:engineer", session_type=SessionType.AGENT) is None


def test_two_sandboxed_members_of_one_team_each_get_their_own_computer(setup):
    db, member_of, _ = setup
    engineer, reviewer = member_of("engineer"), member_of("reviewer")
    team = Team(
        id="team",
        name="Team",
        members=[engineer, reviewer],
        model=_ScriptedModel(
            [_delegate("engineer", "write", "c1"), _delegate("reviewer", "review", "c2"), ("content", "done")]
        ),
        db=db,
    )
    output = team.run("go", session_id="s1")
    assert sorted((run.agent_id, run.status) for run in output.member_responses) == [
        ("engineer", RunStatus.completed),
        ("reviewer", RunStatus.completed),
    ]
    generations = {run.agent_id: run.metadata["sandbox"]["generation"] for run in output.member_responses}
    assert db.get_session(session_id="s1:engineer", session_type=SessionType.AGENT) is not None
    assert db.get_session(session_id="s1:reviewer", session_type=SessionType.AGENT) is not None
    assert len(generations) == 2


@pytest.mark.asyncio
async def test_a_streamed_team_run_carries_a_sandboxed_members_events(setup):
    db, member_of, _ = setup
    engineer = member_of("engineer")
    team = Team(
        id="team",
        name="Team",
        members=[engineer],
        model=_ScriptedModel([_delegate("engineer", "stream it", "c1"), ("content", "done")]),
        db=db,
    )
    events = [event async for event in team.arun("go", session_id="s1", stream=True, stream_events=True)]
    member_events = [event for event in events if getattr(event, "agent_id", None) == "engineer"]
    assert member_events and all(event.session_id == "s1" for event in member_events)
    assert getattr(events[-1], "event", None) == "TeamRunCompleted"


@pytest.mark.asyncio
async def test_cancelling_the_team_run_cancels_the_sandboxed_member_and_frees_its_session(setup):
    import asyncio

    db, member_of, _ = setup
    engineer = member_of("engineer")
    engineer.delay = 8
    team = Team(
        id="team",
        name="Team",
        members=[engineer],
        model=_ScriptedModel([_delegate("engineer", "slow work", "c1"), ("content", "done")]),
        db=db,
    )
    task = asyncio.create_task(team.arun("go", session_id="s1", run_id="team-run-1"))
    await asyncio.sleep(4)
    await team.acancel_run("team-run-1")
    first = await asyncio.wait_for(task, timeout=120)
    assert first.status == RunStatus.cancelled
    # The cancel reached the sandbox: its own record of the turn, in the member's session, ended
    # cancelled well before the 8 second turn could have finished.
    member_session = db.get_session(session_id="s1:engineer", session_type=SessionType.AGENT)
    [sandbox_run] = member_session.runs
    assert sandbox_run.run_id.endswith(".sandbox") and sandbox_run.status == RunStatus.cancelled

    # The member's sandbox session is released: the next team turn runs on it. A fresh leader
    # script, since the cancelled turn stopped the first one part-way.
    engineer.delay = 0
    team.model = _ScriptedModel([_delegate("engineer", "quick", "c2"), ("content", "done")])
    second = await team.arun("again", session_id="s1")
    assert second.member_responses and second.member_responses[-1].status == RunStatus.completed


@pytest.mark.asyncio
async def test_a_streamed_sandboxed_member_leaves_the_sandboxs_own_events_untouched(setup, monkeypatch):
    """The team's stream reports the member's events under the team's ids, on copies: the sandbox
    keeps its own event objects, which it records for its run after yielding them."""
    from agno.run.agent import RunOutput
    from agno.sandbox import _harness

    db, member_of, _ = setup
    engineer = member_of("engineer")
    engineer.store_events = True
    yielded = []
    astream = _harness.astream

    async def recording(*args, **kwargs):
        async for item in astream(*args, **kwargs):
            yielded.append(item)
            yield item

    monkeypatch.setattr(_harness, "astream", recording)
    team = Team(
        id="team",
        name="Team",
        members=[engineer],
        model=_ScriptedModel([_delegate("engineer", "stream it", "c1"), ("content", "done")]),
        db=db,
    )
    events = [event async for event in team.arun("go", session_id="s1", stream=True, stream_events=True)]

    member_events = [event for event in events if getattr(event, "agent_id", None) == "engineer"]
    assert member_events and all(event.session_id == "s1" for event in member_events)
    sandbox_events = [item for item in yielded if not isinstance(item, (str, RunOutput))]
    assert sandbox_events
    assert {(event.run_id.endswith(".sandbox"), event.session_id) for event in sandbox_events} == {
        (True, "s1:engineer")
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_a_cancel_that_lands_before_the_sandbox_link_still_stops_the_member(setup, stream):
    """The team cancelled the member's run before the member linked it to its sandbox run."""
    from agno.run.cancel import acancel_run

    db, member_of, tmp_path = setup
    engineer = member_of("engineer")
    await acancel_run("member-run-1")

    options = dict(session_id="s1", run_id="member-run-1", _team_id="team")
    if stream:
        items = [item async for item in engineer.arun("go", stream=True, yield_run_output=True, **options)]
        output = items[-1]
        assert getattr(items[-2], "event", None) == "RunCancelled"
    else:
        output = await engineer.arun("go", **options)

    assert output.status == RunStatus.cancelled and output.run_id == "member-run-1"
    member_session = db.get_session(session_id="s1:engineer", session_type=SessionType.AGENT)
    assert member_session is None or not [run for run in member_session.runs if run.status == RunStatus.completed]


def test_team_metadata_that_is_not_json_reaches_a_sandboxed_member_or_becomes_its_error(setup):
    from datetime import datetime

    db, member_of, _ = setup
    engineer = member_of("engineer")
    team = Team(
        id="team",
        name="Team",
        members=[engineer],
        model=_ScriptedModel(
            [
                _delegate("engineer", "first", "c1"),
                ("content", "done"),
                _delegate("engineer", "second", "c2"),
                ("content", "done"),
            ]
        ),
        db=db,
    )

    # A datetime is converted to text, as the rest of Agno stores it.
    first = team.run("go", session_id="s1", metadata={"started": datetime(2026, 10, 27, 9, 0)})
    assert [run.status for run in first.member_responses] == [RunStatus.completed]

    # A value JSON cannot hold becomes the member's recorded error instead of an exception in the leader's tool.
    second = team.run("again", session_id="s1", metadata={"ratio": float("nan")})
    assert second.status == RunStatus.completed
    [failed] = second.member_responses
    assert failed.status == RunStatus.error and failed.content


def test_agentos_gives_a_nested_sandboxed_member_the_enclosing_teams_database(setup):
    from agno.os import AgentOS

    db, member_of, _ = setup
    engineer = member_of("engineer")
    engineer.db = None
    inner = Team(id="inner", name="Inner", members=[engineer], model=_ScriptedModel([]))
    outer = Team(id="outer", name="Outer", members=[inner], model=_ScriptedModel([]), db=db)

    AgentOS(id="os", teams=[outer], telemetry=False).get_app()

    assert engineer.db is db


def test_a_sandboxed_members_session_links_back_to_its_team(setup):
    db, member_of, _ = setup
    engineer = member_of("engineer")
    team = Team(
        id="team",
        name="Team",
        members=[engineer],
        model=_ScriptedModel([_delegate("engineer", "work", "c1"), ("content", "done")]),
        db=db,
    )
    team.run("go", session_id="s1")

    member_session = db.get_session(session_id="s1:engineer", session_type=SessionType.AGENT)
    assert (member_session.metadata or {}).get("team_id") == "team"


def test_agentos_gives_a_sandboxed_member_postgres_when_its_team_uses_another_database(setup):
    from agno.db.sqlite import SqliteDb
    from agno.os import AgentOS

    db, member_of, tmp_path = setup
    engineer = member_of("engineer")
    engineer.db = None
    team = Team(
        id="team",
        name="Team",
        members=[engineer],
        model=_ScriptedModel([]),
        db=SqliteDb(db_file=str(tmp_path / "team.db")),
    )

    AgentOS(id="os", db=db, teams=[team], telemetry=False).get_app()

    assert engineer.db is db


def test_agentos_prepares_a_sandboxed_member_of_a_team_used_as_a_workflow_step(setup):
    from agno.os import AgentOS
    from agno.workflow import Step, Workflow

    db, member_of, _ = setup
    engineer = member_of("engineer")
    engineer.db = None
    team = Team(
        id="team",
        name="Team",
        members=[engineer],
        model=_ScriptedModel([_delegate("engineer", "build it", "c1"), ("content", "done")]),
    )
    workflow = Workflow(id="wf", name="WF", steps=[Step(name="build", team=team)])

    AgentOS(id="os", db=db, workflows=[workflow], telemetry=False).get_app()
    assert engineer.db is db

    # The member's first delegated turn runs on its computer instead of failing for want of Postgres.
    output = workflow.run("go", session_id="w1")
    [team_run] = output.step_executor_runs
    assert [run.status for run in team_run.member_responses] == [RunStatus.completed]
