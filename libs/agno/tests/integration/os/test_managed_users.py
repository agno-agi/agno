"""The credential-less user directory (no-IdP tier).

Covers the store itself (in-memory + SQLite), the admin HTTP surface
(``/authz/users`` with roles merged in), and the enforcement value-add: a
disabled user is denied at the gate even with a valid token, and just-in-time
provisioning creates a directory row from token claims.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.os.authz.audit import AuditEvent, AuditSink  # noqa: E402
from agno.os.authz.user_store import ManagedUserStore  # noqa: E402

SECRET = "managed-users-secret-at-least-256-bits-long-padding-xxxxxx"
OS_ID = "managed-users-os"


class _CapturingSink(AuditSink):
    def __init__(self):
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def _token(sub: str, **claims) -> str:
    payload = {"sub": sub, "aud": OS_ID, "scopes": claims.pop("scopes", []), "exp": datetime.now(UTC) + timedelta(hours=1)}
    payload.update(claims)
    return jwt.encode(payload, SECRET, algorithm="HS256")


def _auth(sub: str, **claims) -> dict:
    return {"Authorization": f"Bearer {_token(sub, **claims)}"}


# ----------------------------------------------------------------- store unit
@pytest.mark.parametrize("db_url", [None, "sqlite"])
def test_store_crud_and_disable(tmp_path, db_url):
    url = None if db_url is None else f"sqlite:///{tmp_path / 'users.db'}"
    store = ManagedUserStore(db_url=url)

    # create
    u = store.upsert("u1", email="u1@co", name="One")
    assert u["id"] == "u1" and u["email"] == "u1@co" and u["disabled"] is False
    assert store.get("u1")["name"] == "One"

    # partial update keeps untouched fields
    store.upsert("u1", name="Uno")
    after = store.get("u1")
    assert after["name"] == "Uno" and after["email"] == "u1@co"

    # list newest-first
    store.upsert("u2", email="u2@co")
    ids = [u["id"] for u in store.list()]
    assert set(ids) == {"u1", "u2"}

    # disable / enable + is_disabled fast path
    assert store.is_disabled("u1") is False
    store.set_disabled("u1", True)
    assert store.is_disabled("u1") is True
    assert [u["id"] for u in store.list(include_disabled=False)] == ["u2"]
    store.set_disabled("u1", False)
    assert store.is_disabled("u1") is False

    # unknown subject is not disabled (app may mint tokens for unseen users)
    assert store.is_disabled("ghost") is False

    # remove
    assert store.remove("u2") is True
    assert store.get("u2") is None
    assert store.remove("u2") is False


def test_store_emits_audit_with_actor_and_diff():
    sink = _CapturingSink()
    store = ManagedUserStore(audit=sink)

    store.upsert("u1", email="u1@co", actor="admin")
    store.upsert("u1", name="One", actor="admin")  # update
    store.set_disabled("u1", True, actor="admin")
    store.set_disabled("u1", True, actor="admin")  # no-op, no event
    store.set_disabled("u1", False, actor="admin")
    store.remove("u1", actor="admin")

    actions = [(e.action, e.target, e.actor) for e in sink.events]
    assert actions == [
        ("user.created", "u1", "admin"),
        ("user.updated", "u1", "admin"),
        ("user.disabled", "u1", "admin"),
        ("user.enabled", "u1", "admin"),
        ("user.removed", "u1", "admin"),
    ]


def test_provision_from_claims_is_idempotent():
    store = ManagedUserStore()
    created = store.provision_from_claims("u1", {"email": "u1@co", "name": "One"})
    assert created["email"] == "u1@co" and created["name"] == "One"
    # second call is a no-op, returns existing (doesn't overwrite)
    again = store.provision_from_claims("u1", {"email": "changed@co"})
    assert again["email"] == "u1@co"


# ----------------------------------------------------- HTTP API + enforcement
pytest.importorskip("casbin")  # the API/enforcement tests need the role store/provider

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz.role_router import get_roles_router  # noqa: E402
from agno.os.authz.role_store import ManagedRoleStore  # noqa: E402
from agno.os.config import AuthorizationConfig  # noqa: E402


def _os(role_store, user_store, **cfg):
    agent = Agent(id="research-agent", name="Research Agent", db=InMemoryDb())
    return AgentOS(
        id=OS_ID,
        agents=[agent],
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=role_store.provider,
            user_store=user_store,
            **cfg,
        ),
    )


def test_users_api_crud_and_role_merge():
    roles = ManagedRoleStore()
    roles.set_role_scopes("admin", ["agent_os:admin"])
    roles.set_role_scopes("viewer", ["agents:*:read"])
    roles.assign("alice", "admin")
    users = ManagedUserStore()

    app = _os(roles, users).get_app()
    app.include_router(get_roles_router(roles, user_store=users))
    client = TestClient(app)

    # create a user
    r = client.post("/authz/users", headers=_auth("alice"), json={"id": "bob", "email": "bob@co"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "bob" and r.json()["roles"] == []

    # give bob a role; the user view merges it in
    roles.assign("bob", "viewer")
    got = client.get("/authz/users/bob", headers=_auth("alice")).json()
    assert got["email"] == "bob@co" and got["roles"] == ["viewer"]

    # list includes bob with roles
    listed = client.get("/authz/users", headers=_auth("alice")).json()["users"]
    assert any(u["id"] == "bob" and u["roles"] == ["viewer"] for u in listed)

    # update + delete
    client.patch("/authz/users/bob", headers=_auth("alice"), json={"name": "Bob"})
    assert client.get("/authz/users/bob", headers=_auth("alice")).json()["name"] == "Bob"
    assert client.delete("/authz/users/bob", headers=_auth("alice")).json()["deleted"] is True
    assert client.get("/authz/users/bob", headers=_auth("alice")).status_code == 404


def test_users_api_is_admin_only():
    roles = ManagedRoleStore()
    roles.set_role_scopes("admin", ["agent_os:admin"])
    roles.set_role_scopes("viewer", ["agents:*:read"])
    roles.assign("alice", "admin")
    roles.assign("bob", "viewer")
    users = ManagedUserStore()

    app = _os(roles, users).get_app()
    app.include_router(get_roles_router(roles, user_store=users))
    client = TestClient(app)

    assert client.get("/authz/users", headers=_auth("bob")).status_code == 403  # non-admin
    assert client.get("/authz/users").status_code == 401  # anonymous


def test_disabled_user_is_denied_even_with_valid_token():
    roles = ManagedRoleStore()
    roles.set_role_scopes("viewer", ["agents:*:read"])
    roles.assign("bob", "viewer")
    users = ManagedUserStore()
    users.upsert("bob", email="bob@co")

    client = TestClient(_os(roles, users).get_app())

    # bob (viewer) can read while active
    assert client.get("/agents/research-agent", headers=_auth("bob")).status_code == 200

    # disable bob -> denied on the next request despite the still-valid token + role
    users.set_disabled("bob", True)
    blocked = client.get("/agents/research-agent", headers=_auth("bob"))
    assert blocked.status_code == 403
    assert "disabled" in blocked.json()["detail"].lower()

    # re-enable -> allowed again
    users.set_disabled("bob", False)
    assert client.get("/agents/research-agent", headers=_auth("bob")).status_code == 200


def test_auto_provision_from_claims_at_the_gate():
    roles = ManagedRoleStore()
    roles.set_role_scopes("viewer", ["agents:*:read"])
    roles.assign("carol", "viewer")
    users = ManagedUserStore()

    client = TestClient(_os(roles, users, auto_provision_users=True).get_app())

    assert users.get("carol") is None
    # carol's first request provisions her from the token claims
    r = client.get("/agents/research-agent", headers=_auth("carol", email="carol@co", name="Carol"))
    assert r.status_code == 200
    provisioned = users.get("carol")
    assert provisioned is not None and provisioned["email"] == "carol@co" and provisioned["name"] == "Carol"
