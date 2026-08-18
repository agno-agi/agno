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


def _db_url() -> str:
    """A throwaway file-backed SQLite URL. Managed roles require a DB (no in-memory
    mode); file-backed so the same DB is visible across the threads TestClient uses."""
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".authz.db")
    os.close(fd)
    return f"sqlite:///{path}"


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
    store = ManagedRoleStore(audit=sink, db_url=_db_url())

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
    # before/after captured on the widen — full entries (scope + effect) so an
    # allow<->deny flip is visible in the trail.
    widen = sink.events[1]
    assert widen.before == [{"scope": "agents:read", "effect": "allow"}]
    assert {e["scope"] for e in widen.after} == {"agents:read", "agents:run"}
    assert all(e["effect"] == "allow" for e in widen.after)
    # assignment diff
    assign = sink.events[2]
    assert assign.before == [] and assign.after == ["member"]
    # every event is timestamped
    assert all(e.timestamp > 0 for e in sink.events)


def test_no_sink_means_no_overhead_and_no_events():
    store = ManagedRoleStore(db_url=_db_url())  # no audit
    # should not raise and should be a no-op for auditing
    store.set_role_scopes("member", ["agents:*:read"], actor="alice")
    store.assign("bob", "member", actor="alice")
    assert store.roles_of("bob") == ["member"]


def test_db_audit_sink_is_append_only_table(tmp_path):
    import sqlalchemy as sa

    db_file = tmp_path / "audit.db"
    url = f"sqlite:///{db_file}"
    sink = DbAuditSink(db_url=url)
    store = ManagedRoleStore(audit=sink, db_url=_db_url())

    store.set_role_scopes("member", ["agents:*:read"], actor="alice")
    store.assign("bob", "member", actor="alice")
    store.unassign("bob", "member", actor="carol")

    eng = sa.create_engine(url)
    with eng.connect() as c:
        rows = c.execute(
            sa.text("select actor, action, target, before, after from agno_authz_audit order by created_at")
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
    store = ManagedRoleStore(audit=sink, db_url=_db_url())
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

    store.set_role_scopes("runner", ["agents:read"])  # role must exist before PUT /scopes
    sink.events.clear()
    client.put("/authz/roles/runner/scopes", headers=_auth("alice"), json={"scopes": ["agents:*:run"]})
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
    store = ManagedRoleStore(db_url=_db_url())
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
        changes = c.execute(sa.text("select action, target from agno_authz_audit order by created_at")).fetchall()
        decisions = c.execute(
            sa.text("select action, target, token_ref from agno_authz_decisions order by created_at")
        ).fetchall()

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
    store = ManagedRoleStore(audit=sink, db_url=_db_url())
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

    # admin reads the decision trail (paginated {data, meta})
    r = client.get("/authz/decisions", headers=_auth("alice"))
    assert r.status_code == 200
    body = r.json()
    events = body["data"]
    assert body["meta"]["total_count"] >= len(events)
    assert any(e["action"] == "access.allowed" and e["metadata"]["token"] == "dec-1" for e in events)

    # /authz/audit (changes) does NOT contain the access.* decisions
    changes = client.get("/authz/audit", headers=_auth("alice")).json()["data"]
    assert all(not e["action"].startswith("access.") for e in changes)

    # non-admin and anonymous are blocked
    assert client.get("/authz/decisions", headers=_auth("bob")).status_code == 403
    assert client.get("/authz/decisions").status_code == 401


def test_audit_endpoint_returns_trail(tmp_path):
    """GET /authz/audit returns the change trail (newest first) for admins only."""
    db_file = tmp_path / "audit.db"
    store = ManagedRoleStore(audit=DbAuditSink(db_url=f"sqlite:///{db_file}"), db_url=_db_url())
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
    client.post("/authz/roles", headers=_auth("alice"), json={"slug": "runner"})
    client.put("/authz/roles/runner/scopes", headers=_auth("alice"), json={"scopes": ["agents:*:run"]})
    client.post("/authz/users/bob/roles", headers=_auth("alice"), json={"role": "runner"})

    # admin can read the trail; newest first, paginated {data, meta}
    r = client.get("/authz/audit", headers=_auth("alice"))
    assert r.status_code == 200
    body = r.json()
    events = body["data"]
    assert body["meta"]["page"] == 1 and body["meta"]["total_count"] == len(events)
    assert events[0]["action"] == "user.assigned" and events[0]["actor"] == "alice"
    assert events[0]["after"] == ["runner"]
    assert any(e["action"] == "role.set_scopes" and e["target"] == "runner" for e in events)

    # page/limit slice the trail (page 2 with limit 1 = the second-newest event)
    paged = client.get("/authz/audit?limit=1&page=2", headers=_auth("alice")).json()
    assert len(paged["data"]) == 1
    assert paged["data"][0]["action"] == events[1]["action"]
    assert paged["meta"]["total_count"] == len(events) and paged["meta"]["page"] == 2

    # search filters over actor/action/target (case-insensitive), counted in meta
    found = client.get("/authz/audit?search=SET_SCOPES", headers=_auth("alice")).json()
    assert found["data"] and all(e["action"] == "role.set_scopes" for e in found["data"])
    assert found["meta"]["total_count"] == len(found["data"])
    assert client.get("/authz/audit?search=zzz-no-match", headers=_auth("alice")).json()["data"] == []

    # sort_order=asc flips to oldest first
    asc = client.get("/authz/audit?sort_order=asc", headers=_auth("alice")).json()["data"]
    assert [e["action"] for e in asc] == [e["action"] for e in reversed(events)]

    # sort_by any sortable field; an unknown field is a 422, not a 500
    by_action = client.get("/authz/audit?sort_by=action&sort_order=asc", headers=_auth("alice")).json()["data"]
    assert [e["action"] for e in by_action] == sorted(e["action"] for e in events)
    assert client.get("/authz/audit?sort_by=evil", headers=_auth("alice")).status_code == 422

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


def test_per_resource_deny_is_recorded_when_it_denies_independently():
    """The per-resource gate records its own DENY.

    Note the route gate is ALREADY resource-aware (it puts resource_id in the context,
    so a managed-role per-resource denial is decided -- and recorded -- there, with the
    concrete resource in the target). The gap this covers is the case the route gate
    can't: a provider whose ``check`` is stricter than its ``authorize_route``, so the
    route is allowed and the per-resource dependency is what actually blocks. Without
    recording here that denial would be invisible -- the trail would show the route
    allowed and never show what stopped the request.
    """
    from agno.os.authz.provider import AuthorizationProvider

    class RouteOpenResourceClosed(AuthorizationProvider):
        """Lets every route through, then denies the specific resource."""

        def check(self, ctx):
            return False

        def accessible_resource_ids(self, ctx):
            return {"*"}

        def authorize_route(self, ctx, required_scopes):
            return True

    sink = _CapturingSink()
    db = InMemoryDb()
    agent_os = AgentOS(
        id=OS_ID,
        agents=[Agent(id="yours", name="Yours", db=db)],
        db=db,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            verify_audience=True,
            audience=OS_ID,
            authorization_provider=RouteOpenResourceClosed(),
            audit=sink,
        ),
    )
    client = TestClient(agent_os.get_app())
    r = client.post("/agents/yours/runs", headers=_auth("bob"), data={"message": "hi"})
    assert r.status_code == 403, r.text

    resource_denials = [e for e in sink.events if e.metadata.get("reason") == "resource_access_denied"]
    assert resource_denials, f"per-resource deny not recorded; got {[(e.action, e.target) for e in sink.events]}"
    ev = resource_denials[0]
    assert ev.action == "access.denied" and ev.actor == "bob"
    assert "yours" in ev.target


def test_audit_sink_is_mirrored_onto_the_mcp_subapp():
    """The MCP tool gate resolves its sink from the mounted sub-app's state (request.app
    is the sub-app, not the main app). Without this mirror MCP decisions can't be
    recorded at all, leaving the access trail covering REST/WS but silently missing the
    entire MCP transport."""
    pytest.importorskip("fastmcp")
    sink = _CapturingSink()
    store = ManagedRoleStore(db_url=_db_url())
    store.set_role_scopes("viewer", ["agents:*:read"])

    db = InMemoryDb()
    agent_os = AgentOS(
        id=OS_ID,
        agents=[Agent(id="research-agent", name="Research Agent", db=db)],
        db=db,
        authorization=True,
        mcp_server=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[SECRET],
            algorithm="HS256",
            authorization_provider=store.provider,
            audit=sink,
        ),
    )
    app = agent_os.get_app()
    assert getattr(app.state, "authz_audit", None) is sink
    sub = getattr(getattr(agent_os, "_mcp_app", None), "state", None)
    assert getattr(sub, "authz_audit", None) is sink, "MCP sub-app must resolve the SAME audit sink"


def test_audit_row_survives_a_control_char_in_the_target(tmp_path):
    """Audit-suppression regression (PERS-2). A NUL in the request path (sent as %00,
    decoded into the ASGI path) makes the decision row's INSERT fail on Postgres, which
    the sink swallows -- so the probe vanishes from the trail. Control chars are now
    stripped so a mangled-but-present row is written instead of dropped."""
    from agno.os.authz.audit import _sanitize_text

    # the sanitizer strips NUL and other C0 controls, keeps tab/newline and normal text
    assert _sanitize_text("GET /agents/x\x00") == "GET /agents/x"
    assert _sanitize_text("a\x01b\x1fc") == "abc"
    assert _sanitize_text("keep\ttab\nnewline") == "keep\ttab\nnewline"

    sink = DbAuditSink(db_url=f"sqlite:///{tmp_path / 'audit.db'}")
    sink.record(AuditEvent(action="access.denied", actor="attacker", target="GET /agents/research-agent\x00"))
    decisions = sink.read_decisions()
    assert len(decisions) == 1, "the audit row must be written, not silently dropped"
    assert "\x00" not in decisions[0]["target"]
    assert decisions[0]["target"] == "GET /agents/research-agent"
