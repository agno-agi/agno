"""Tests for the evals REST API router.

The id returned by ``POST /eval-runs`` must be the id the run was persisted under: the
per-execution ``run_id`` carried on the eval result.
Everything downstream keys off that id: ``GET /eval-runs/{id}``, the owner stamp under
user isolation, rename and delete.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.response import ToolExecution
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.run.agent import RunOutput

JWT_SECRET = "test-secret-for-evals-router"
TEST_OS_ID = "test-evals-router-os"


def create_token(user_id: str, scopes: list[str] | None = None) -> str:
    payload = {
        "sub": user_id,
        "aud": TEST_OS_ID,
        "scopes": scopes or ["evals:read", "evals:write", "evals:delete"],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def auth_header(user_id: str) -> dict:
    return {"Authorization": f"Bearer {create_token(user_id)}"}


def _tool_run_output() -> RunOutput:
    """A run that cleanly executed the expected tool, so the reliability eval needs no model."""
    return RunOutput(
        content="50",
        tools=[ToolExecution(tool_call_id="call_multiply", tool_name="multiply", tool_args={"a": 10, "b": 5})],
    )


RELIABILITY_BODY = {
    "eval_type": "reliability",
    "agent_id": "assistant",
    "input": "Use the calculator to multiply 10 by 5.",
    "expected_tool_calls": ["multiply"],
}


@pytest.fixture
def db():
    return InMemoryDb()


@pytest.fixture
def client(db):
    """Isolation-enabled client: the router stamps the caller as the run's owner."""
    agent = Agent(id="assistant", name="Assistant", db=db)
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[agent],
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            user_isolation=True,
        ),
    )
    return TestClient(agent_os.get_app())


def _post_reliability_eval(client):
    with patch.object(Agent, "arun", new=AsyncMock(return_value=_tool_run_output())):
        return client.post("/eval-runs", json=RELIABILITY_BODY, headers=auth_header("alice"))


def test_run_eval_returns_the_persisted_run_id(client, db):
    """The id in the response is the row's run_id, so GET by that id works."""
    resp = _post_reliability_eval(client)
    assert resp.status_code == 200
    run_id = resp.json()["id"]

    rows, _ = db.get_eval_runs(deserialize=False)
    assert [row["run_id"] for row in rows] == [run_id]

    get = client.get(f"/eval-runs/{run_id}", headers=auth_header("alice"))
    assert get.status_code == 200
    assert get.json()["id"] == run_id


def test_run_eval_stamps_the_caller_as_owner(client, db):
    """The owner stamp targets the persisted id, so the run shows up in the caller's own list."""
    resp = _post_reliability_eval(client)
    run_id = resp.json()["id"]

    rows, _ = db.get_eval_runs(deserialize=False)
    assert rows[0]["user_id"] == "alice"
    assert resp.json()["user_id"] == "alice"

    listed = client.get("/eval-runs", headers=auth_header("alice")).json()["data"]
    assert [row["id"] for row in listed] == [run_id]
    # and it is not visible to another user
    assert client.get("/eval-runs", headers=auth_header("bob")).json()["data"] == []


def test_repeated_run_eval_calls_persist_distinct_runs(client, db):
    """Two executions are two rows with two ids, each retrievable and renamable by its own id."""
    first = _post_reliability_eval(client).json()["id"]
    second = _post_reliability_eval(client).json()["id"]
    assert first != second

    rows, total = db.get_eval_runs(deserialize=False)
    assert total == 2
    assert {row["run_id"] for row in rows} == {first, second}

    renamed = client.patch(f"/eval-runs/{second}", json={"name": "second run"}, headers=auth_header("alice"))
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "second run"
    assert client.get(f"/eval-runs/{first}", headers=auth_header("alice")).json()["name"] != "second run"
