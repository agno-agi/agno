"""The agents /continue door accepts every run state (unified continue).

The continue dispatch handles run state itself - COMPLETED forks as a
follow-up, RUNNING/ERROR resume, unresolved HITL raises its own precise
error - so the router carries no paused-only gate. A stale router gate
here once 409'd persisted COMPLETED runs with "run is already continued"
(false: nothing was continued) before the request reached the dispatch
that supports it, breaking cookbook/04_run_lifecycle/checkpoints.py.

These tests pin the gate's absence at the endpoint level. The seeded agent
has no model, so the continuation fails deeper in the machinery - the
assertion is strictly "the router does not 409 on run state". Teams are
equally ungated (their dispatch has the same machinery); workflows keep
their refusal because the workflow core requires PAUSED - both pinned
below so neither door drifts.
"""

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

SESSION_ID = "s-cont"


@pytest.fixture()
def harness(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "t.db"))
    agent = Agent(id="qa-agent", name="QA Agent", db=db)
    app = AgentOS(agents=[agent], telemetry=False).get_app()
    client = TestClient(app, raise_server_exceptions=False)
    return SimpleNamespace(db=db, client=client)


def seed_run(db: SqliteDb, run_id: str, status: str) -> None:
    sessions_table = db._get_table(table_type="sessions", create_table_if_not_found=True)
    runs_table = db._get_table(table_type="runs", create_table_if_not_found=True)
    with db.Session() as sess, sess.begin():
        existing = sess.execute(sessions_table.select().where(sessions_table.c.session_id == SESSION_ID)).fetchone()
        if existing is None:
            sess.execute(
                sessions_table.insert().values(
                    session_id=SESSION_ID, session_type="agent", agent_id="qa-agent", created_at=int(time.time())
                )
            )
        sess.execute(
            runs_table.insert().values(
                run_id=run_id,
                session_id=SESSION_ID,
                run_type="agent",
                agent_id="qa-agent",
                status=status,
                run_index=0,
                run_data=json.dumps(
                    {
                        "run_id": run_id,
                        "session_id": SESSION_ID,
                        "agent_id": "qa-agent",
                        "status": status,
                        "content": "the finished answer",
                        "messages": [],
                    }
                ),
                created_at=int(time.time()),
            )
        )


def continue_run(harness, run_id: str, **extra):
    data = {"session_id": SESSION_ID, "stream": "false", "background": "false", **extra}
    return harness.client.post(f"/agents/qa-agent/runs/{run_id}/continue", data=data)


class TestAgentsContinueHasNoStatusGate:
    def test_completed_run_is_not_409ed(self, harness):
        """The checkpoints-cookbook repro: plain continue of a persisted
        COMPLETED run must reach the dispatch (which forks it as a
        follow-up), never the stale 'run is already continued' 409."""
        seed_run(harness.db, "r-done", "COMPLETED")
        resp = continue_run(harness, "r-done")
        assert resp.status_code != 409, f"stale paused-only gate fired: {resp.json()}"

    def test_fork_of_completed_run_is_not_409ed(self, harness):
        seed_run(harness.db, "r-done-fork", "COMPLETED")
        resp = continue_run(harness, "r-done-fork", fork="true")
        assert resp.status_code != 409, resp.json()

    def test_regenerate_of_completed_run_is_not_409ed(self, harness):
        seed_run(harness.db, "r-done-regen", "COMPLETED")
        resp = continue_run(harness, "r-done-regen", regenerate="true")
        assert resp.status_code != 409, resp.json()

    @pytest.mark.parametrize("status", ["RUNNING", "ERROR", "CANCELLED", "PENDING"])
    def test_no_run_state_produces_the_stale_409(self, harness, status):
        """Every state the old gate mapped to a 409 detail now reaches the
        dispatch, which applies its own (honest) semantics per state."""
        run_id = f"r-{status.lower()}"
        seed_run(harness.db, run_id, status)
        resp = continue_run(harness, run_id)
        if resp.status_code == 409:
            detail = resp.json().get("detail", "")
            assert "already" not in detail and "not paused" not in detail, (
                f"the deleted router gate's message resurfaced for {status}: {detail}"
            )


class TestTeamsContinueStaysUngated:
    """Teams got the unified-continue CORE (auto-fork on COMPLETED, mirror
    of the agent dispatch) and their router never had a status gate - pin
    that nobody 'fixes' teams by adding the gate agents just lost."""

    @pytest.fixture()
    def team_harness(self, tmp_path):
        from agno.team import Team

        db = SqliteDb(db_file=str(tmp_path / "t.db"))
        team = Team(id="qa-team", name="QA Team", members=[], db=db)
        app = AgentOS(teams=[team], telemetry=False).get_app()
        return SimpleNamespace(db=db, client=TestClient(app, raise_server_exceptions=False))

    def test_completed_team_run_continue_is_not_409ed(self, team_harness):
        sessions_table = team_harness.db._get_table(table_type="sessions", create_table_if_not_found=True)
        runs_table = team_harness.db._get_table(table_type="runs", create_table_if_not_found=True)
        with team_harness.db.Session() as sess, sess.begin():
            sess.execute(
                sessions_table.insert().values(session_id="s-team", session_type="team", created_at=int(time.time()))
            )
            sess.execute(
                runs_table.insert().values(
                    run_id="r-team-done",
                    session_id="s-team",
                    run_type="team",
                    team_id="qa-team",
                    status="COMPLETED",
                    run_index=0,
                    run_data=json.dumps(
                        {"run_id": "r-team-done", "session_id": "s-team", "team_id": "qa-team", "status": "COMPLETED"}
                    ),
                    created_at=int(time.time()),
                )
            )
        resp = team_harness.client.post(
            "/teams/qa-team/runs/r-team-done/continue",
            data={"session_id": "s-team", "stream": "false", "background": "false"},
        )
        assert resp.status_code != 409, f"teams continue must stay ungated (unified core): {resp.json()}"


class TestWorkflowDoorKeepsPausedGate:
    """The workflow core hard-requires PAUSED to continue; the router's 409
    is the clean front for that precondition and must stay until the core
    itself learns other states."""

    @pytest.fixture()
    def full_harness(self, tmp_path):
        from agno.team import Team
        from agno.workflow import Workflow

        db = SqliteDb(db_file=str(tmp_path / "t.db"))
        agent = Agent(id="qa-agent", name="QA Agent", db=db)
        team = Team(id="qa-team", name="QA Team", members=[], db=db)
        workflow = Workflow(id="qa-wf", name="QA Workflow", db=db, steps=[])
        app = AgentOS(agents=[agent], teams=[team], workflows=[workflow], telemetry=False).get_app()
        return SimpleNamespace(db=db, client=TestClient(app, raise_server_exceptions=False))

    def test_workflow_completed_continue_still_refused(self, full_harness):
        sessions_table = full_harness.db._get_table(table_type="sessions", create_table_if_not_found=True)
        runs_table = full_harness.db._get_table(table_type="runs", create_table_if_not_found=True)
        with full_harness.db.Session() as sess, sess.begin():
            sess.execute(
                sessions_table.insert().values(session_id="s-wf", session_type="workflow", created_at=int(time.time()))
            )
            sess.execute(
                runs_table.insert().values(
                    run_id="r-wf-done",
                    session_id="s-wf",
                    run_type="workflow",
                    workflow_id="qa-wf",
                    status="COMPLETED",
                    run_index=0,
                    run_data=json.dumps(
                        {"run_id": "r-wf-done", "session_id": "s-wf", "workflow_id": "qa-wf", "status": "COMPLETED"}
                    ),
                    created_at=int(time.time()),
                )
            )
        resp = full_harness.client.post(
            "/workflows/qa-wf/runs/r-wf-done/continue",
            data={"session_id": "s-wf", "stream": "false", "background": "false"},
        )
        assert resp.status_code in (400, 409), f"workflow paused-only door must keep main parity: {resp.status_code}"
