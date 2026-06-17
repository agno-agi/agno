"""Audit trail for managed-role changes.

The policy engine can't attribute who changed a policy (it never sees the actor),
so change-audit lives at our layer. These tests verify that role and
assignment mutations emit append-only AuditEvents with the acting principal and
the before/after, both via the store directly and through the admin HTTP API.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sqlalchemy")  # managed roles persist/enforce via the native engine + SQLAlchemy

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


def _token(sub: str, jti: str | None = None) -> str:
    claims = {"sub": sub, "aud": OS_ID, "scopes": [], "exp": datetime.now(UTC) + timedelta(hours=1)}
    if jti is not None:
        claims["jti"] = jti
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _auth(sub: str, jti: str | None = None) -> dict:
    return {"Authorization": f"Bearer {_token(sub, jti)}"}


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
        rows = c.execute(sa.text("select actor, action, target, before, after from authz_audit order by id")).fetchall()
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


def _decision_os(sink):
    """An AgentOS where viewer can read agents but not delete sessions, with the
    given sink wired for decision audit."""
    store = ManagedRoleStore()
    store.set_role_scopes("viewer", ["agents:*:read"])
    store.assign("bob", "viewer")

    db = InMemoryDb()
    agent = Agent(id="research-agent", name="Research Agent", db=db)
    agent_os = AgentOS(
        id=OS_ID,
        agents=[agent],
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=store.provider,
            audit=sink,  # <- decision audit
        ),
    )
    return store, agent_os


def test_decision_audit_records_allow_and_deny():
    """Each authorization decision (allow/deny) is recorded with the principal and
    a non-secret token reference when an audit sink is on AuthorizationConfig."""
    sink = _CapturingSink()
    _, agent_os = _decision_os(sink)
    client = TestClient(agent_os.get_app())

    client.get("/agents/research-agent", headers=_auth("bob"))  # allowed (viewer reads)
    client.delete("/sessions/s1", headers=_auth("bob"))  # denied (no sessions:delete)

    by_action = {(e.action, e.actor) for e in sink.events}
    assert ("access.allowed", "bob") in by_action
    assert ("access.denied", "bob") in by_action

    denied = next(e for e in sink.events if e.action == "access.denied")
    assert denied.target.startswith("DELETE /sessions")
    assert "sessions:delete" in (denied.metadata.get("required") or [])
    # a token reference is captured, but NOT the raw token
    assert denied.metadata.get("token") and len(denied.metadata["token"]) <= 16


def test_decision_token_ref_prefers_jti_over_hash():
    """The token reference is the token's jti when present (so it correlates to the
    issuer's logs); only without a jti do we fall back to a short hash."""
    sink = _CapturingSink()
    _, agent_os = _decision_os(sink)
    client = TestClient(agent_os.get_app())

    client.get("/agents/research-agent", headers=_auth("bob", jti="tok-abc-123"))  # has jti
    client.get("/agents/research-agent", headers=_auth("bob"))  # no jti -> hash

    refs = [e.metadata.get("token") for e in sink.events if e.action == "access.allowed"]
    assert "tok-abc-123" in refs  # jti used verbatim
    hashed = [r for r in refs if r != "tok-abc-123"]
    assert hashed and all(len(r) == 12 for r in hashed)  # fallback is the short hash


def test_decision_and_change_audit_go_to_separate_tables(tmp_path):
    """One DbAuditSink, two physically separate tables: role/assignment changes in
    authz_audit, per-request decisions in authz_decisions."""
    import sqlalchemy as sa

    db_file = tmp_path / "audit.db"
    url = f"sqlite:///{db_file}"
    sink = DbAuditSink(db_url=url)

    store, agent_os = _decision_os(sink)
    # also route the store's change events to the same sink
    store._audit = sink  # noqa: SLF001 (test wiring)
    store.set_role_scopes("viewer", ["agents:*:read", "agents:*:run"], actor="alice")  # a change

    client = TestClient(agent_os.get_app())
    client.get("/agents/research-agent", headers=_auth("bob", jti="jti-1"))  # a decision (allow)
    client.delete("/sessions/s1", headers=_auth("bob", jti="jti-2"))  # a decision (deny)

    eng = sa.create_engine(url)
    with eng.connect() as c:
        changes = c.execute(sa.text("select action, target from authz_audit order by id")).fetchall()
        decisions = c.execute(sa.text("select action, target, token_ref from authz_decisions order by id")).fetchall()

    # change table holds only the role change, no access.* rows
    assert [tuple(r) for r in changes] == [("role.set_scopes", "viewer")]
    # decision table holds only access.* rows, with the jti as the token ref
    actions = {(r[0], r[2]) for r in decisions}
    assert ("access.allowed", "jti-1") in actions
    assert ("access.denied", "jti-2") in actions
    assert all(r[0].startswith("access.") for r in decisions)

    # the readers are separated too
    assert all(not e["action"].startswith("access.") for e in sink.read())
    assert all(e["action"].startswith("access.") for e in sink.read_decisions())


def test_decisions_endpoint_returns_trail_for_admin(tmp_path):
    """GET /authz/decisions returns the decision trail (newest first) for admins;
    it is separate from /authz/audit (changes)."""
    db_file = tmp_path / "audit.db"
    sink = DbAuditSink(db_url=f"sqlite:///{db_file}")
    store = ManagedRoleStore(audit=sink)
    store.set_role_scopes("admin", ["agent_os:admin"])
    store.assign("alice", "admin")
    store.set_role_scopes("viewer", ["agents:*:read"])
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
            audit=sink,  # decisions land here too
        ),
    )
    app = agent_os.get_app()
    app.include_router(get_roles_router(store))
    client = TestClient(app)

    client.get("/agents/research-agent", headers=_auth("bob", jti="dec-1"))  # allowed decision

    # admin reads the decision trail
    r = client.get("/authz/decisions", headers=_auth("alice"))
    assert r.status_code == 200
    events = r.json()["events"]
    assert any(e["action"] == "access.allowed" and e["metadata"]["token"] == "dec-1" for e in events)

    # /authz/audit (changes) does NOT contain the access.* decisions
    changes = client.get("/authz/audit", headers=_auth("alice")).json()["events"]
    assert all(not e["action"].startswith("access.") for e in changes)

    # non-admin and anonymous are blocked
    assert client.get("/authz/decisions", headers=_auth("bob")).status_code == 403
    assert client.get("/authz/decisions").status_code == 401


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


def test_db_audit_sink_never_raises_into_caller(tmp_path, monkeypatch):
    """#7: DbAuditSink.record must swallow DB errors (contract) so a failing audit
    write can't turn a successful role change into a 500."""
    from agno.os.authz.audit import AuditEvent, DbAuditSink

    sink = DbAuditSink(db_url=f"sqlite:///{tmp_path / 'audit.db'}")

    def boom(_event):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(sink, "_record_change", boom)
    monkeypatch.setattr(sink, "_record_decision", boom)
    # both trails: must not propagate
    sink.record(AuditEvent(action="role.set_scopes", actor="alice", target="m"))
    sink.record(AuditEvent(action="access.denied", actor="bob", target="GET /x"))
