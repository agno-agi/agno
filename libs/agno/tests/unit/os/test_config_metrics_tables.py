"""/config lists one metrics table per database, and a gateway reads it back."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.schema import ConfigResponse
from agno.os.utils import get_db
from agno.remote.base import RemoteDb


def _config(*dbs: SqliteDb) -> dict:
    agents = [Agent(id=f"agent-{i}", db=db, telemetry=False) for i, db in enumerate(dbs)]
    client = TestClient(AgentOS(agents=agents, telemetry=False).get_app())
    response = client.get("/config")
    assert response.status_code == 200
    return response.json()


def _metrics_tables(config: dict) -> dict:
    return {db["db_id"]: db["tables"] for db in config["metrics"]["dbs"]}


def test_metrics_lists_one_table_per_database(tmp_path: Path):
    db = SqliteDb(id="metrics-db", db_file=str(tmp_path / "agno.db"))

    assert _metrics_tables(_config(db)) == {"metrics-db": ["agno_component_metrics"]}


def test_metrics_lists_each_database_under_a_shared_id(tmp_path: Path):
    first = SqliteDb(id="shared", db_file=str(tmp_path / "a.db"), component_metrics_table="team_a_metrics")
    second = SqliteDb(id="shared", db_file=str(tmp_path / "b.db"), component_metrics_table="team_b_metrics")

    assert _metrics_tables(_config(first, second)) == {"shared": ["team_a_metrics", "team_b_metrics"]}


@pytest.mark.asyncio
async def test_gateway_resolves_the_listed_metrics_table(tmp_path: Path):
    db = SqliteDb(id="metrics-db", db_file=str(tmp_path / "agno.db"))
    config = ConfigResponse.model_validate(_config(db))

    remote = RemoteDb.from_config("metrics-db", client=None, config=config)  # type: ignore[arg-type]

    assert remote is not None
    assert remote.component_metrics_table_name == "agno_component_metrics"
    assert await get_db({"metrics-db": [remote]}, "metrics-db", "agno_component_metrics") is remote
