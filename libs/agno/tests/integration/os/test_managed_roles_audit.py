"""Audit trail for managed-role changes.

Casbin can't attribute who changed a policy (its management API never sees the
actor), so change-audit lives at our layer. These tests verify that role and
assignment mutations emit append-only AuditEvents with the acting principal and
the before/after, both via the store directly and through the admin HTTP API.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("casbin")

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz.audit import AuditEvent, AuditSink, DbAuditSink  # noqa: E402
from agno.os.authz.role_router import get_roles_router  # noqa: E402
from agno.os.authz.role_store import ManagedRoleStore  # noqa: E402
from agno.os.config import AuthorizationConfig  # noqa: E402

SECRET = "managed-roles-audit-secret-at-least-256-bits-long-xxxx"
OS_ID = "managed-roles-audit-os"


class _CapturingSink(AuditSink):
    def __init__(self):
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def _token(sub: str) -> str:
    return jwt.encode(
        {"sub": sub, "aud": OS_ID, "scopes": [], "exp": datetime.now(UTC) + timedelta(hours=1)},
        SECRET, algorithm="HS256",
    )


def _auth(sub: str) -> dict:
    return {"Authorization": f"Bearer {_token(sub)}"}


def test_store_emits_change_events_with_actor_and_diff():
    sink = _CapturingSink()
    store = ManagedRoleStore(audit=sink)

    store.set_role_scopes("member", ["agents:*:read"], actor="alice")
    store.set_role_scopes("member", ["agents:*:read", "agents:*:run"], actor="alice")  # widen
    store.assign("bob", "member", actor="alice")
    store.unassign("bob", "member", actor="alice")
    store.remove_role("member", actor="alice")

    actions = [(e.action, e.target, e.actor) for e in sink.events]
    assert actions == [
        ("role.set_scopes", "member", "alice"),
        ("role.set_scopes", "member", "alice"),
        ("user.assigned", "bob", "alice"),
        ("user.unassigned", "bob", "alice"),
        ("role.removed", "member", "alice"),
    ]
    # before/after captured on the widen
    widen = sink.events[1]
    assert widen.before == ["agents:read"]
    assert set(widen.after) == {"agents:read", "agents:run"}
    # assignment diff
    assign = sink.events[2]
    assert assign.before == [] and assign.after == ["member"]
    # every event is timestamped
    assert all(e.timestamp > 0 for e in sink.events)


def test_no_sink_means_no_overhead_and_no_events():
    store = ManagedRoleStore()  # no audit
    # should not raise and should be a no-op for auditing
    store.set_role_scopes("member", ["agents:*:read"], actor="alice")
    store.assign("bob", "member", actor="alice")
    assert store.roles_of("bob") == ["member"]


def test_db_audit_sink_is_append_only_table(tmp_path):
    import sqlalchemy as sa

    db_file = tmp_path / "audit.db"
    url = f"sqlite:///{db_file}"
    sink = DbAuditSink(db_url=url)
    store = ManagedRoleStore(audit=sink)

    store.set_role_scopes("member", ["agents:*:read"], actor="alice")
    store.assign("bob", "member", actor="alice")
    store.unassign("bob", "member", actor="carol")

    eng = sa.create_engine(url)
    with eng.connect() as c:
        rows = c.execute(
            sa.text("select actor, action, target, before, after from authz_audit order by id")
        ).fetchall()
    assert [tuple(r[:3]) for r in rows] == [
        ("alice", "role.set_scopes", "member"),
        ("alice", "user.assigned", "bob"),
        ("carol", "user.unassigned", "bob"),
    ]
    # before/after persisted as JSON
    assert rows[1].before == "[]" and rows[1].after == '["member"]'


def test_http_api_records_actor_from_jwt():
    sink = _CapturingSink()
    store = ManagedRoleStore(audit=sink)
    store.set_role_scopes("admin", ["agent_os:admin"])
    store.assign("alice", "admin")  # bootstrap admin (not audited: no actor route)

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

    sink.events.clear()
    client.put("/authz/roles/runner", headers=_auth("alice"), json={"scopes": ["agents:*:run"]})
    client.post("/authz/users/bob/roles", headers=_auth("alice"), json={"role": "runner"})
    client.delete("/authz/users/bob/roles/runner", headers=_auth("alice"))

    actions = [(e.action, e.target, e.actor) for e in sink.events]
    assert actions == [
        ("role.set_scopes", "runner", "alice"),
        ("user.assigned", "bob", "alice"),
        ("user.unassigned", "bob", "alice"),
    ]


def test_audit_endpoint_returns_trail(tmp_path):
    """GET /authz/audit returns the change trail (newest first) for admins only."""
    db_file = tmp_path / "audit.db"
    store = ManagedRoleStore(audit=DbAuditSink(db_url=f"sqlite:///{db_file}"))
    store.set_role_scopes("admin", ["agent_os:admin"])
    store.assign("alice", "admin")

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

    # make a couple of changes over the API
    client.put("/authz/roles/runner", headers=_auth("alice"), json={"scopes": ["agents:*:run"]})
    client.post("/authz/users/bob/roles", headers=_auth("alice"), json={"role": "runner"})

    # admin can read the trail; newest first
    r = client.get("/authz/audit", headers=_auth("alice"))
    assert r.status_code == 200
    events = r.json()["events"]
    assert events[0]["action"] == "user.assigned" and events[0]["actor"] == "alice"
    assert events[0]["after"] == ["runner"]
    assert any(e["action"] == "role.set_scopes" and e["target"] == "runner" for e in events)

    # non-admin and anonymous are blocked
    store.assign("bob", "runner")  # bob still isn't an admin
    assert client.get("/authz/audit", headers=_auth("bob")).status_code == 403
    assert client.get("/authz/audit").status_code == 401
