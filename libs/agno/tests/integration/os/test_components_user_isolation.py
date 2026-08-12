"""Integration tests for per-user component isolation.

Validates that:
- Regular users only see their own components, agents, teams, and workflows
- Admin users (agent_os:admin scope) see all components
- Users cannot read, update, or delete another user's component by ID
- Users cannot run another user's DB-backed agent / team / workflow
- Users cannot reference another user's component as a team member or
  workflow step, at any nesting depth
- Routes that resolve a component before checking the session do not leak its existence

Component persistence is implemented by the SQLite and Postgres adapters; these
tests run against the SqliteDb-backed ``shared_db``.
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.os import AgentOS
from agno.os.config import AuthorizationConfig

JWT_SECRET = "test-secret-for-isolation"
TEST_OS_ID = "test-isolation-os"


def create_token(user_id: str, scopes: list[str] | None = None) -> str:
    """Create a JWT token for the given user.

    Default scopes cover the component endpoints (read / write / delete) plus the
    routes that resolve them. Pass ``scopes=[...]`` explicitly to test narrower-scope behaviour.
    """
    payload = {
        "sub": user_id,
        "aud": TEST_OS_ID,
        "scopes": scopes
        or [
            "components:read",
            "components:write",
            "components:delete",
            "agents:read",
            "agents:run",
            "teams:read",
            "teams:run",
            "workflows:read",
            "workflows:run",
        ],
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def create_admin_token(user_id: str = "admin-user") -> str:
    """Create a JWT token with admin scope."""
    return create_token(user_id, scopes=["agent_os:admin"])


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_component(client, token: str, name: str, component_type: str, config: dict):
    """Create a published component over the API as the token's owner."""
    return client.post(
        "/components",
        json={"name": name, "component_type": component_type, "config": config, "stage": "published"},
        headers=auth_header(token),
    )


# The gate tests 404 before a model is reached, so only the owner-can-run tests need a real one.
RUNNABLE_MODEL = {"name": "OpenAIResponses", "id": "gpt-5.5", "provider": "OpenAI"}


@pytest.fixture
def client(shared_db):
    """Isolation-enabled client backed by ``shared_db``.

    No code-defined components are registered, so every component the routes return is DB-backed.
    """
    agent_os = AgentOS(
        id=TEST_OS_ID,
        db=shared_db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            user_isolation=True,
        ),
    )
    return TestClient(agent_os.get_app())


@pytest.fixture
def alice_agent(client):
    """An agent component owned by ``user-a``."""
    resp = create_component(
        client, create_token("user-a"), "Alice Agent", "agent", {"name": "Alice Agent", "instructions": "private"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["component_id"]


# --- Component isolation ---


class TestComponentIsolation:
    """Verify that component endpoints are scoped to the JWT user_id."""

    def test_user_sees_only_own_components(self, client, alice_agent):
        """User A's components are not visible to User B."""
        create_component(client, create_token("user-b"), "Bob Agent", "agent", {"name": "Bob Agent"})

        resp = client.get("/components", headers=auth_header(create_token("user-b")))
        assert resp.status_code == 200
        component_ids = [c["component_id"] for c in resp.json()["data"]]
        assert alice_agent not in component_ids

    def test_admin_sees_all_components(self, client, alice_agent):
        """Admin should see components from all users."""
        create_component(client, create_token("user-b"), "Bob Agent", "agent", {"name": "Bob Agent"})

        resp = client.get("/components", headers=auth_header(create_admin_token()))
        assert resp.status_code == 200
        assert resp.json()["meta"]["total_count"] == 2

    def test_owner_is_recorded_on_create(self, client, alice_agent):
        resp = client.get(f"/components/{alice_agent}", headers=auth_header(create_token("user-a")))
        assert resp.json()["user_id"] == "user-a"

    def test_user_cannot_get_other_users_component_by_id(self, client, alice_agent):
        """User B should get 404 when accessing User A's component by ID."""
        resp = client.get(f"/components/{alice_agent}", headers=auth_header(create_token("user-b")))
        assert resp.status_code == 404

        # but the owner can read it
        resp = client.get(f"/components/{alice_agent}", headers=auth_header(create_token("user-a")))
        assert resp.status_code == 200

    def test_user_cannot_update_other_users_component(self, client, alice_agent):
        """User B updating User A's component returns 404; the name is unchanged."""
        resp = client.patch(
            f"/components/{alice_agent}", json={"name": "hacked"}, headers=auth_header(create_token("user-b"))
        )
        assert resp.status_code == 404

        resp = client.get(f"/components/{alice_agent}", headers=auth_header(create_token("user-a")))
        assert resp.json()["name"] == "Alice Agent"

    def test_user_cannot_delete_other_users_component(self, client, alice_agent):
        """User B deleting User A's component returns 404; the component survives."""
        resp = client.delete(f"/components/{alice_agent}", headers=auth_header(create_token("user-b")))
        assert resp.status_code == 404

        resp = client.get(f"/components/{alice_agent}", headers=auth_header(create_token("user-a")))
        assert resp.status_code == 200

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/components/{cid}/configs"),
            ("POST", "/components/{cid}/configs"),
            ("PATCH", "/components/{cid}/configs/1"),
            ("GET", "/components/{cid}/configs/current"),
            ("GET", "/components/{cid}/configs/1"),
            ("DELETE", "/components/{cid}/configs/1"),
            ("POST", "/components/{cid}/configs/1/set-current"),
        ],
    )
    def test_user_cannot_reach_other_users_configs(self, client, alice_agent, method, path):
        """Every config sub-route is gated on component ownership."""
        resp = client.request(
            method, path.format(cid=alice_agent), json={"config": {}}, headers=auth_header(create_token("user-b"))
        )
        assert resp.status_code == 404

    def test_component_id_clash_does_not_confirm_other_users_component(self, client, alice_agent):
        """Claiming a taken id must not reveal that another user owns it."""
        resp = client.post(
            "/components",
            json={
                "component_id": alice_agent,
                "name": "squat",
                "component_type": "agent",
                "config": {"name": "squat"},
            },
            headers=auth_header(create_token("user-b")),
        )
        assert resp.status_code == 400
        assert "already exists" not in resp.text

    def test_same_name_for_two_users_does_not_collide(self, client):
        """Two users may create a component with the same name."""
        resp_a = create_component(client, create_token("user-a"), "Shared Name", "agent", {"name": "Shared Name"})
        resp_b = create_component(client, create_token("user-b"), "Shared Name", "agent", {"name": "Shared Name"})

        assert resp_a.status_code == 201
        assert resp_b.status_code == 201
        assert resp_a.json()["component_id"] != resp_b.json()["component_id"]


# --- Component resolution on the run routes ---


class TestComponentResolutionIsolation:
    """Verify that routes resolving DB-backed components are owner-scoped."""

    def test_user_does_not_see_other_users_agents(self, client, alice_agent):
        resp = client.get("/agents", headers=auth_header(create_token("user-b")))
        assert resp.status_code == 200
        assert alice_agent not in [a["id"] for a in resp.json()]

    def test_user_cannot_run_other_users_agent(self, client, alice_agent):
        resp = client.post(
            f"/agents/{alice_agent}/runs",
            data={"message": "hi", "stream": "false"},
            headers=auth_header(create_token("user-b")),
        )
        assert resp.status_code == 404

    def test_user_cannot_get_other_users_agent(self, client, alice_agent):
        resp = client.get(f"/agents/{alice_agent}", headers=auth_header(create_token("user-b")))
        assert resp.status_code == 404

    @pytest.mark.parametrize(
        "path",
        [
            "/agents/{cid}/sessions/some-session/fork",
            "/agents/{cid}/runs/some-run/checkpoints?session_id=some-session",
            "/agents/{cid}/runs/some-run/checkpoints/0?session_id=some-session",
        ],
    )
    def test_agent_routes_do_not_leak_component_existence(self, client, alice_agent, path):
        """Another user's component must answer exactly as a missing one -- otherwise it is an existence oracle."""
        token = create_token("user-b")
        method = "POST" if path.endswith("/fork") else "GET"

        owned = client.request(method, path.format(cid=alice_agent), headers=auth_header(token))
        missing = client.request(method, path.format(cid="no-such-component"), headers=auth_header(token))

        assert owned.status_code == missing.status_code
        assert owned.json() == missing.json()

    @pytest.mark.parametrize(
        "path",
        [
            "/teams/{cid}/sessions/some-session/fork",
            "/teams/{cid}/runs/some-run/checkpoints?session_id=some-session",
            "/teams/{cid}/runs/some-run/checkpoints/0?session_id=some-session",
        ],
    )
    def test_team_routes_do_not_leak_component_existence(self, client, path):
        """Team counterpart of the agent existence-oracle check."""
        resp = create_component(
            client, create_token("user-a"), "Alice Team", "team", {"name": "Alice Team", "members": []}
        )
        alice_team = resp.json()["component_id"]
        token = create_token("user-b")
        method = "POST" if path.endswith("/fork") else "GET"

        owned = client.request(method, path.format(cid=alice_team), headers=auth_header(token))
        missing = client.request(method, path.format(cid="no-such-component"), headers=auth_header(token))

        assert owned.status_code == missing.status_code
        assert owned.json() == missing.json()


# --- Owner can run their own DB-backed components ---


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
class TestOwnerCanRunOwnComponents:
    """The isolation gate must block non-owners without breaking the owner.

    The 404 checks above cannot tell a correct denial from a route that is broken for
    everyone, so these run an owner's own components end-to-end against a real model.
    """

    def test_owner_can_run_own_agent(self, client):
        resp = create_component(
            client,
            create_token("user-a"),
            "Runnable Agent",
            "agent",
            {"name": "Runnable Agent", "model": RUNNABLE_MODEL, "instructions": "Reply with exactly: OK"},
        )
        assert resp.status_code == 201, resp.text
        agent_id = resp.json()["component_id"]

        run = client.post(
            f"/agents/{agent_id}/runs",
            data={"message": "ping", "stream": "false"},
            headers=auth_header(create_token("user-a")),
        )
        assert run.status_code == 200, run.text
        assert run.json()["content"] is not None

    def test_owner_can_run_own_team(self, client):
        member = create_component(
            client,
            create_token("user-a"),
            "Team Member",
            "agent",
            {"name": "Team Member", "model": RUNNABLE_MODEL, "instructions": "Reply with exactly: PONG"},
        )
        member_id = member.json()["component_id"]
        resp = create_component(
            client,
            create_token("user-a"),
            "Runnable Team",
            "team",
            {
                "name": "Runnable Team",
                "model": RUNNABLE_MODEL,
                "mode": "coordinate",
                "members": [{"type": "agent", "agent_id": member_id}],
                "instructions": "Delegate to your member and return its reply.",
            },
        )
        assert resp.status_code == 201, resp.text
        team_id = resp.json()["component_id"]

        # A team whose member fails to rehydrate still returns 200, so assert it resolved.
        detail = client.get(f"/teams/{team_id}", headers=auth_header(create_token("user-a")))
        assert detail.status_code == 200, detail.text
        assert member_id in [m.get("id") for m in detail.json().get("members", [])]

        run = client.post(
            f"/teams/{team_id}/runs",
            data={"message": "say the word", "stream": "false"},
            headers=auth_header(create_token("user-a")),
        )
        assert run.status_code == 200, run.text
        assert run.json()["content"] is not None

    def test_owner_can_run_own_workflow(self, client):
        executor = create_component(
            client,
            create_token("user-a"),
            "Step Executor",
            "agent",
            {"name": "Step Executor", "model": RUNNABLE_MODEL, "instructions": "Reply with exactly: DONE"},
        )
        executor_id = executor.json()["component_id"]
        resp = create_component(
            client,
            create_token("user-a"),
            "Runnable Workflow",
            "workflow",
            {"name": "Runnable Workflow", "steps": [{"type": "Step", "name": "s1", "agent_id": executor_id}]},
        )
        assert resp.status_code == 201, resp.text
        workflow_id = resp.json()["component_id"]

        run = client.post(
            f"/workflows/{workflow_id}/runs",
            data={"message": "go", "stream": "false"},
            headers=auth_header(create_token("user-a")),
        )
        assert run.status_code == 200, run.text
        assert run.json()["content"] is not None


# --- Referenced-component ownership ---


class TestReferencedComponentOwnership:
    """A scoped caller must not reference another user's component."""

    def test_cannot_use_other_users_agent_as_team_member(self, client, alice_agent):
        resp = create_component(
            client,
            create_token("user-b"),
            "Bob Team",
            "team",
            {"name": "Bob Team", "members": [{"type": "agent", "agent_id": alice_agent}]},
        )
        assert resp.status_code == 404

    def test_cannot_use_other_users_agent_as_workflow_step(self, client, alice_agent):
        resp = create_component(
            client,
            create_token("user-b"),
            "Bob Workflow",
            "workflow",
            {"name": "Bob Workflow", "steps": [{"name": "s1", "agent_id": alice_agent}]},
        )
        assert resp.status_code == 404

    @pytest.mark.parametrize("container", ["Parallel", "Loop", "Condition", "Steps"])
    def test_cannot_hide_reference_inside_a_step_container(self, client, alice_agent, container):
        """The reference walk must reach steps nested in any container type."""
        resp = create_component(
            client,
            create_token("user-b"),
            f"Bob {container}",
            "workflow",
            {
                "name": f"Bob {container}",
                "steps": [{"name": "c", "type": container, "steps": [{"name": "s", "agent_id": alice_agent}]}],
            },
        )
        assert resp.status_code == 404

    def test_cannot_smuggle_reference_via_new_config_version(self, client, alice_agent):
        """The check applies to config updates, not just creation."""
        created = create_component(
            client, create_token("user-b"), "Bob Own", "workflow", {"name": "Bob Own", "steps": []}
        )
        bob_workflow = created.json()["component_id"]

        resp = client.post(
            f"/components/{bob_workflow}/configs",
            json={"config": {"name": "Bob Own", "steps": [{"name": "s", "agent_id": alice_agent}]}},
            headers=auth_header(create_token("user-b")),
        )
        assert resp.status_code == 404

    def test_cannot_smuggle_reference_via_explicit_link(self, client, alice_agent):
        created = create_component(
            client, create_token("user-b"), "Bob Linked", "workflow", {"name": "Bob Linked", "steps": []}
        )
        bob_workflow = created.json()["component_id"]

        resp = client.post(
            f"/components/{bob_workflow}/configs",
            json={
                "config": {"name": "Bob Linked"},
                "links": [
                    {
                        "link_kind": "member",
                        "link_key": "member_0",
                        "child_component_id": alice_agent,
                        "child_version": 1,
                    }
                ],
            },
            headers=auth_header(create_token("user-b")),
        )
        assert resp.status_code == 404

    def test_owner_can_reference_own_component(self, client, alice_agent):
        """The check must not block a legitimate self-reference."""
        resp = create_component(
            client,
            create_token("user-a"),
            "Alice Team",
            "team",
            {"name": "Alice Team", "members": [{"type": "agent", "agent_id": alice_agent}]},
        )
        assert resp.status_code == 201


# --- Isolation disabled ---


class TestIsolationDisabled:
    """With user_isolation off, components stay global."""

    @pytest.fixture
    def open_client(self, shared_db):
        agent_os = AgentOS(
            id=TEST_OS_ID,
            db=shared_db,
            authorization=True,
            authorization_config=AuthorizationConfig(
                verification_keys=[JWT_SECRET],
                algorithm="HS256",
                user_isolation=False,
            ),
        )
        return TestClient(agent_os.get_app())

    def test_components_are_shared_when_isolation_is_off(self, open_client):
        resp = create_component(open_client, create_token("user-a"), "Shared Agent", "agent", {"name": "Shared Agent"})
        assert resp.status_code == 201
        component_id = resp.json()["component_id"]

        resp = open_client.get(f"/components/{component_id}", headers=auth_header(create_token("user-b")))
        assert resp.status_code == 200
