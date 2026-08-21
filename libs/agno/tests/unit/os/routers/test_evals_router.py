from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.schemas.evals import EvalType
from agno.db.sqlite.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.routers.evals.schemas import EvalSchema
from agno.team import Team


def _eval_result(*, agent_id: str | None = None, team_id: str | None = None) -> EvalSchema:
    return EvalSchema(
        id="eval-run",
        agent_id=agent_id,
        team_id=team_id,
        eval_type=EvalType.ACCURACY,
        eval_data={"passed": True},
    )


def test_run_eval_resolves_database_agent(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "components.db"))
    agent = Agent(id="database-agent", name="Database Agent", telemetry=False)
    agent.save(db=db)
    client = TestClient(AgentOS(db=db, agents=[], telemetry=False).get_app())

    with patch(
        "agno.os.routers.evals.evals.run_accuracy_eval",
        new=AsyncMock(return_value=_eval_result(agent_id=agent.id)),
    ) as run_accuracy_eval:
        response = client.post(
            "/eval-runs",
            json={
                "agent_id": agent.id,
                "eval_type": "accuracy",
                "input": "hello",
                "expected_output": "hello",
            },
        )

    assert response.status_code == 200
    assert run_accuracy_eval.await_args.kwargs["agent"].id == agent.id


def test_run_eval_resolves_database_team(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "components.db"))
    member = Agent(id="database-team-member", name="Database Team Member", telemetry=False)
    team = Team(id="database-team", name="Database Team", members=[member], telemetry=False)
    team.save(db=db)
    client = TestClient(AgentOS(db=db, teams=[], telemetry=False).get_app())

    with patch(
        "agno.os.routers.evals.evals.run_accuracy_eval",
        new=AsyncMock(return_value=_eval_result(team_id=team.id)),
    ) as run_accuracy_eval:
        response = client.post(
            "/eval-runs",
            json={
                "team_id": team.id,
                "eval_type": "accuracy",
                "input": "hello",
                "expected_output": "hello",
            },
        )

    assert response.status_code == 200
    assert run_accuracy_eval.await_args.kwargs["team"].id == team.id
