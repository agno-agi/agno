"""Integration tests for the ManagedRoleStore HTTP management API.

Exercises the admin-only governance surface end to end: CRUD over roles and
assignments through HTTP, the admin gate (401/403), and the payoff — a role
granted via the API takes effect on the target user's next request.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("casbin")

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz.role_router import get_roles_router  # noqa: E402
from agno.os.authz.role_store import ManagedRoleStore  # noqa: E402
from agno.os.config import AuthorizationConfig  # noqa: E402

SECRET = "managed-roles-api-test-secret-at-least-256-bits-long-xx"
OS_ID = "managed-roles-api-test-os"


def _token(sub: str) -> str:
    return jwt.encode(
        {"sub": sub, "aud": OS_ID, "scopes": [], "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET, algorithm="HS256",
    )


def _auth(sub: str) -> dict:
    return {"Authorization": f"Bearer {_token(sub)}"}


@pytest.fixture
def client_and_store():
    store = ManagedRoleStore()  # in-memory
    store.set_role_scopes("viewer", ["agents:*:read"])
    store.set_role_scopes("admin", ["agent_os:admin"])
    store.assign("alice", "admin")
    store.assign("bob", "viewer")

    agent = Agent(id="research-agent", name="Research Agent", db=InMemoryDb())
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=store.provider,
        ),
    )
    app = agent_os.get_app()
    app.include_router(get_roles_router(store))
    return TestClient(app), store


def test_unauthenticated_is_401(client_and_store):
    client, _ = client_and_store
    assert client.get("/authz/roles").status_code == 401


def test_non_admin_is_403(client_and_store):
    client, _ = client_and_store
    # bob is a viewer, not an admin
    assert client.get("/authz/roles", headers=_auth("bob")).status_code == 403
    assert client.post(
        "/authz/users/carol/roles", headers=_auth("bob"), json={"role": "viewer"}
    ).status_code == 403


def test_admin_can_list_and_read_roles(client_and_store):
    client, _ = client_and_store
    r = client.get("/authz/roles", headers=_auth("alice"))
    assert r.status_code == 200
    body = r.json()  # paginated {data, meta}
    assert {role["slug"] for role in body["data"]} == {"viewer", "admin"}
    assert body["meta"]["total_count"] == 2

    r = client.get("/authz/roles/viewer", headers=_auth("alice"))
    assert r.status_code == 200
    role = r.json()
    assert role["slug"] == "viewer" and role["name"] == "viewer"
    # scopes are parsed objects now: {raw, namespace, sub_namespace, permission, value}
    assert role["scopes"] == [
        {
            "id": None,
            "raw": "agents:read",
            "namespace": "agents",
            "sub_namespace": None,
            "permission": "read",
            "value": "allow",
        }
    ]


def test_admin_crud_role(client_and_store):
    client, store = client_and_store
    # create a new role
    r = client.put(
        "/authz/roles/editor",
        headers=_auth("alice"),
        json={"scopes": ["agents:*:read", "agents:research-agent:run"]},
    )
    assert r.status_code == 200
    assert store.get_role_scopes("editor") == sorted(["agents:read", "agents:research-agent:run"])

    # delete it
    r = client.delete("/authz/roles/editor", headers=_auth("alice"))
    assert r.status_code == 200
    assert "editor" not in store.list_roles()


def test_admin_assign_and_revoke(client_and_store):
    client, store = client_and_store
    r = client.post("/authz/users/carol/roles", headers=_auth("alice"), json={"role": "viewer"})
    assert r.status_code == 200
    assert r.json()["roles"] == ["viewer"]
    assert store.roles_of("carol") == ["viewer"]

    r = client.delete("/authz/users/carol/roles/viewer", headers=_auth("alice"))
    assert r.status_code == 200
    assert store.roles_of("carol") == []


def test_granting_via_api_takes_effect_on_next_request(client_and_store):
    client, _ = client_and_store
    # bob is a viewer: cannot run the agent
    assert client.post(
        "/agents/research-agent/runs", headers=_auth("bob"), data={"message": "hi"}
    ).status_code == 403

    # admin defines a runner role and grants it to bob via the HTTP API
    assert client.put(
        "/authz/roles/runner", headers=_auth("alice"), json={"scopes": ["agents:*:run"]}
    ).status_code == 200
    assert client.post(
        "/authz/users/bob/roles", headers=_auth("alice"), json={"role": "runner"}
    ).status_code == 200

    # bob can now run — same token, no re-mint
    assert client.post(
        "/agents/research-agent/runs", headers=_auth("bob"), data={"message": "hi"}
    ).status_code != 403

    # admin revokes it; bob is blocked again
    assert client.delete("/authz/users/bob/roles/runner", headers=_auth("alice")).status_code == 200
    assert client.post(
        "/agents/research-agent/runs", headers=_auth("bob"), data={"message": "hi"}
    ).status_code == 403


def test_scope_catalog_endpoint(client_and_store):
    client, _ = client_and_store
    r = client.get("/authz/scopes", headers=_auth("alice"))
    assert r.status_code == 200
    body = r.json()  # flat list of {raw, namespace, sub_namespace?, permission}
    assert isinstance(body, list)
    by_raw = {s["raw"]: s for s in body}
    assert by_raw["agents:run"] == {"raw": "agents:run", "namespace": "agents", "permission": "run"}
    assert "agent_os:admin" in by_raw  # the super-scope is included
    # exclude_none: sub_namespace omitted when absent
    assert "sub_namespace" not in by_raw["agents:read"]
    # non-admin is blocked
    assert client.get("/authz/scopes", headers=_auth("bob")).status_code == 403


def test_admin_via_token_claim_can_manage():
    """When roles come from the token (external IdP), an admin role on the token grants management."""
    store = ManagedRoleStore(roles_claim="roles")
    store.set_role_scopes("admin", ["agent_os:admin"])
    store.set_role_scopes("viewer", ["agents:*:read"])

    agent = Agent(id="research-agent", name="Research Agent", db=InMemoryDb())
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=store.provider,
        ),
    )
    app = agent_os.get_app()
    app.include_router(get_roles_router(store))
    client = TestClient(app)

    def idp_token(sub, roles):
        return jwt.encode(
            {"sub": sub, "aud": OS_ID, "scopes": [], "roles": roles,
             "exp": datetime.now(UTC) + timedelta(hours=1)},
            SECRET, algorithm="HS256",
        )

    admin_h = {"Authorization": f"Bearer {idp_token('idp-admin', ['admin'])}"}
    viewer_h = {"Authorization": f"Bearer {idp_token('idp-viewer', ['viewer'])}"}

    assert client.get("/authz/roles", headers=admin_h).status_code == 200
    assert client.get("/authz/roles", headers=viewer_h).status_code == 403
