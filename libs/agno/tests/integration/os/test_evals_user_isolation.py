"""Integration tests for per-user eval-run isolation.

Validates that:
- Regular users only see their own eval runs
- Admin users (agent_os:admin scope) see all eval runs
- Users cannot read, delete, or rename another user's eval run by ID

Every Db adapter implements eval isolation; these tests run against the
SqliteDb-backed ``shared_db``.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent.agent import Agent
from agno.db.schemas.evals import EvalRunRecord, EvalType
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig

JWT_SECRET = "test-secret-for-isolation"
TEST_OS_ID = "test-isolation-os"


def create_token(user_id: str, scopes: list[str] | None = None) -> str:
    """Create a JWT token for the given user.

    Default scopes cover the eval endpoints (read / write / delete). Pass
    ``scopes=[...]`` explicitly to test narrower-scope behaviour.
    """
    payload = {
        "sub": user_id,
        "aud": TEST_OS_ID,
        "scopes": scopes or ["evals:read", "evals:write", "evals:delete"],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def create_admin_token(user_id: str = "admin-user") -> str:
    """Create a JWT token with admin scope."""
    return create_token(user_id, scopes=["agent_os:admin"])


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def seed_eval_run(db, run_id: str, user_id: str) -> None:
    """Persist an eval run owned by ``user_id`` directly on the db.

    Eval runs are normally written by the eval framework; we seed at the data
    layer so the read / delete / rename isolation can be exercised without
    invoking a model.
    """
    db.create_eval_run(
        EvalRunRecord(
            run_id=run_id,
            eval_type=EvalType.ACCURACY,
            eval_data={"eval_status": "PASSED"},
            eval_input={},
        )
    )
    db.update_eval_run_user_id(run_id, user_id)


@pytest.fixture
def test_agent(shared_db):
    return Agent(
        name="test-agent",
        id="test-agent",
        db=shared_db,
        instructions="You are a test agent.",
    )


@pytest.fixture
def client(test_agent):
    """Isolation-enabled client backed by ``shared_db``."""
    agent_os = AgentOS(
        id=TEST_OS_ID,
        agents=[test_agent],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            user_isolation=True,
        ),
    )
    return TestClient(agent_os.get_app())


# --- Eval-run isolation ---


class TestEvalRunIsolation:
    """Verify that eval-run endpoints are scoped to the JWT user_id."""

    def test_user_sees_only_own_eval_runs(self, client, shared_db):
        """User A's runs are not visible to User B."""
        seed_eval_run(shared_db, "run-a", "user-a")
        seed_eval_run(shared_db, "run-b", "user-b")

        resp = client.get("/eval-runs", headers=auth_header(create_token("user-b")))
        assert resp.status_code == 200
        run_ids = [r["id"] for r in resp.json()["data"]]
        assert run_ids == ["run-b"]

    def test_admin_sees_all_eval_runs(self, client, shared_db):
        """Admin should see eval runs from all users."""
        seed_eval_run(shared_db, "run-a", "user-a")
        seed_eval_run(shared_db, "run-b", "user-b")

        resp = client.get("/eval-runs", headers=auth_header(create_admin_token()))
        assert resp.status_code == 200
        run_ids = {r["id"] for r in resp.json()["data"]}
        assert run_ids == {"run-a", "run-b"}

    def test_user_cannot_get_other_users_eval_run_by_id(self, client, shared_db):
        """User B should get 404 when accessing User A's eval run by ID."""
        seed_eval_run(shared_db, "run-a", "user-a")

        resp = client.get("/eval-runs/run-a", headers=auth_header(create_token("user-b")))
        assert resp.status_code == 404

        # but the owner can read it
        resp = client.get("/eval-runs/run-a", headers=auth_header(create_token("user-a")))
        assert resp.status_code == 200

    def test_user_cannot_delete_other_users_eval_run(self, client, shared_db):
        """User B deleting User A's run is a no-op; the run survives for admin."""
        seed_eval_run(shared_db, "run-a", "user-a")

        resp = client.request(
            "DELETE",
            "/eval-runs",
            json={"eval_run_ids": ["run-a"]},
            headers=auth_header(create_token("user-b")),
        )
        assert resp.status_code == 204

        # Run still exists for its owner
        resp = client.get("/eval-runs/run-a", headers=auth_header(create_token("user-a")))
        assert resp.status_code == 200

    def test_user_cannot_rename_other_users_eval_run(self, client, shared_db):
        """User B renaming User A's run returns 404; the name is unchanged."""
        seed_eval_run(shared_db, "run-a", "user-a")

        resp = client.patch(
            "/eval-runs/run-a",
            json={"name": "hacked"},
            headers=auth_header(create_token("user-b")),
        )
        assert resp.status_code == 404

        # Owner can rename it
        resp = client.patch(
            "/eval-runs/run-a",
            json={"name": "my eval"},
            headers=auth_header(create_token("user-a")),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "my eval"


class TestOwnerStampingBestEffort:
    """Owner stamping after run creation is best-effort.

    The eval framework persists the run before the OS stamps the owner, so a
    backend that can't stamp (e.g. a custom Db without
    ``update_eval_run_user_id``) must not fail the create request.
    """

    def test_create_succeeds_when_owner_stamp_fails(self, monkeypatch):
        from agno.db.in_memory import InMemoryDb
        from agno.os.routers.evals import evals as evals_module
        from agno.os.routers.evals.schemas import EvalSchema

        class StamplessDb(InMemoryDb):
            def update_eval_run_user_id(self, eval_run_id: str, user_id: str) -> None:
                raise NotImplementedError("custom backend without eval isolation")

        db = StamplessDb()
        agent = Agent(name="test-agent", id="test-agent", db=db, instructions="You are a test agent.")
        agent_os = AgentOS(
            id=TEST_OS_ID,
            agents=[agent],
            authorization=True,
            authorization_config=AuthorizationConfig(
                verification_keys=[JWT_SECRET],
                algorithm="HS256",
                user_isolation=True,
            ),
        )
        client = TestClient(agent_os.get_app())

        # Stub the eval runner so no model is invoked; the run is "persisted".
        async def fake_accuracy_eval(**kwargs) -> EvalSchema:
            return EvalSchema(id="run-stampless", eval_type=EvalType.ACCURACY, eval_data={})

        monkeypatch.setattr(evals_module, "run_accuracy_eval", fake_accuracy_eval)

        resp = client.post(
            "/eval-runs",
            json={
                "agent_id": "test-agent",
                "eval_type": "accuracy",
                "input": "What is 2+2?",
                "expected_output": "4",
            },
            headers=auth_header(create_token("user-a")),
        )

        # Stamping failed, but the eval run is still returned — just unowned.
        assert resp.status_code == 200
        assert resp.json()["id"] == "run-stampless"
        assert resp.json()["user_id"] is None


class TestEvalRunRbacGate:
    """Verify the JWT scope gate on eval endpoints (independent of isolation)."""

    def test_missing_token_is_401(self, client):
        assert client.get("/eval-runs").status_code == 401

    def test_missing_eval_scope_is_403(self, client):
        token = create_token("user-a", scopes=["agents:read"])
        assert client.get("/eval-runs", headers=auth_header(token)).status_code == 403

    def test_read_scope_can_list(self, client):
        token = create_token("user-a", scopes=["evals:read"])
        assert client.get("/eval-runs", headers=auth_header(token)).status_code == 200

    def test_read_scope_cannot_delete(self, client):
        token = create_token("user-a", scopes=["evals:read"])
        resp = client.request("DELETE", "/eval-runs", json={"eval_run_ids": ["x"]}, headers=auth_header(token))
        assert resp.status_code == 403

    def test_read_scope_cannot_rename(self, client):
        token = create_token("user-a", scopes=["evals:read"])
        assert client.patch("/eval-runs/x", json={"name": "n"}, headers=auth_header(token)).status_code == 403

    def test_admin_can_list(self, client):
        assert client.get("/eval-runs", headers=auth_header(create_admin_token())).status_code == 200
