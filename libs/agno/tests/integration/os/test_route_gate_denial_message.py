"""The route gate's denial log names the plane that decided.

Under managed roles with ``trust_token_scopes=False`` the token's scopes are never consulted, so
the old "Required: [...], User has: [...]" line listed the required scope inside the user's own
list and read as a contradiction. The log must say the provider refused the subject, that the
subject holds no role, and that token scopes are not trusted. Under the scope plane the
required-versus-held comparison is the truth and stays.
"""

import logging
import time
from contextlib import contextmanager

import jwt
import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.db.in_memory import InMemoryDb  # noqa: E402
from agno.db.sqlite import SqliteDb  # noqa: E402
from agno.os import AgentOS  # noqa: E402
from agno.os.authz import Authorization  # noqa: E402

SECRET = "denial-message-secret-at-least-256-bits-xxxxxxxxxx"
OS_ID = "denial-os"
_LOGGERS = ("agno", "agno-agent", "agno-team", "agno-workflow")


def _token(sub, scopes):
    payload = {"sub": sub, "aud": OS_ID, "scopes": scopes, "exp": int(time.time()) + 3600}
    return {"Authorization": "Bearer " + jwt.encode(payload, SECRET, algorithm="HS256")}


@contextmanager
def _warnings():
    """Capture WARNING records on every agno logger with the level pinned, so an earlier run in the
    session cannot hide the line (log_warning writes to whichever logger the last run selected)."""
    messages: list = []

    class _Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    handler = _Capture()
    handler.setLevel(logging.WARNING)
    loggers = [logging.getLogger(n) for n in _LOGGERS]
    levels = [lg.level for lg in loggers]
    for lg in loggers:
        lg.setLevel(logging.WARNING)
        lg.addHandler(handler)
    try:
        yield messages
    finally:
        for lg, lvl in zip(loggers, levels):
            lg.removeHandler(handler)
            lg.setLevel(lvl)


def _client(tmp_path, *, roles: bool):
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    authz = Authorization(db=db, verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID)
    if roles:
        authz.define_role("admin", ["agent_os:admin"])
        authz.define_role("viewer", ["agents:*:read"])
        authz.assign("vic", "viewer")
    agents = [Agent(id="a", name="A", db=InMemoryDb())]
    return TestClient(AgentOS(id=OS_ID, db=db, agents=agents, authorization=authz).get_app())


def test_denial_under_managed_roles_names_the_provider_not_the_token_scopes(tmp_path):
    """A control-plane token carrying config:read and agent_os:admin, no role in the store."""
    client = _client(tmp_path, roles=True)
    with _warnings() as messages:
        r = client.get("/config", headers=_token("operator", ["config:read", "agent_os:admin"]))
    assert r.status_code == 403
    denial = [m for m in messages if "/config" in m]
    assert denial, messages
    line = denial[-1]
    assert "User has" not in line  # the old contradiction: the required scope listed as held
    assert "provider refused" in line and "'operator'" in line
    assert "holds no role" in line
    assert "not trusted" in line and "trust_token_scopes" in line


def test_denial_under_managed_roles_names_the_held_role(tmp_path):
    """A subject WITH a role that simply does not grant the route."""
    client = _client(tmp_path, roles=True)
    with _warnings() as messages:
        r = client.get("/config", headers=_token("vic", []))
    assert r.status_code == 403
    line = [m for m in messages if "/config" in m][-1]
    assert "holds role(s) ['viewer']" in line and "do not authorize GET /config" in line
    assert "User has" not in line


def test_denial_under_the_scope_plane_keeps_required_versus_held(tmp_path):
    """No roles: token scopes are the authority, so the comparison IS the reason."""
    client = _client(tmp_path, roles=False)
    with _warnings() as messages:
        r = client.get("/config", headers=_token("bob", ["agents:read"]))
    assert r.status_code == 403
    line = [m for m in messages if "/config" in m][-1]
    assert "Required: ['config:read']" in line and "User has: ['agents:read']" in line


def test_denial_under_roles_claim_names_the_token_carried_role(tmp_path):
    """External IdP: the engine decides on the role the TOKEN carries, not on stored assignments,
    so the line must name that role rather than claim the subject holds none."""
    db = SqliteDb(db_file=str(tmp_path / "idp.db"))
    authz = Authorization(
        db=db, verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID, roles_claim="role"
    )
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"])
    client = TestClient(
        AgentOS(id=OS_ID, db=db, agents=[Agent(id="a", name="A", db=InMemoryDb())], authorization=authz).get_app()
    )
    payload = {
        "sub": "idp-user",
        "aud": OS_ID,
        "role": "viewer",
        "scopes": ["config:read"],
        "exp": int(time.time()) + 3600,
    }
    headers = {"Authorization": "Bearer " + jwt.encode(payload, SECRET, algorithm="HS256")}
    with _warnings() as messages:
        r = client.get("/config", headers=headers)
    assert r.status_code == 403
    line = [m for m in messages if "/config" in m][-1]
    assert "token carries role(s) ['viewer']" in line and "do not authorize GET /config" in line
    assert "holds no role" not in line and "User has" not in line


def test_denial_by_an_explicit_deny_names_the_deny_not_a_missing_grant(tmp_path):
    """Wildcard allow plus a resource-specific deny: the role DOES grant agents:read, so 'does not
    grant' would send an operator to add a grant that exists. The line must name the deny."""
    db = SqliteDb(db_file=str(tmp_path / "deny.db"))
    authz = Authorization(db=db, verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID)
    authz.define_role("reader", ["agents:*:read", ("agents:secret:read", "deny")])
    authz.assign("rae", "reader")
    agents = [Agent(id="pub", name="P", db=InMemoryDb()), Agent(id="secret", name="S", db=InMemoryDb())]
    client = TestClient(AgentOS(id=OS_ID, db=db, agents=agents, authorization=authz).get_app())
    with _warnings() as messages:
        assert client.get("/agents/pub", headers=_token("rae", [])).status_code == 200
        r = client.get("/agents/secret", headers=_token("rae", []))
    assert r.status_code == 403
    line = [m for m in messages if "/agents/secret" in m][-1]
    assert "do not grant" not in line
    assert "explicit deny on 'agents/secret'" in line
    assert "holds role(s) ['reader']" in line


async def test_ambiguous_route_action_does_not_report_an_unrelated_deny(tmp_path):
    """A custom mapping can require two actions on one resource route, and then the route has no
    single action to look denials up for. Querying with no action filter would surface a deny on
    ANY action; here the request fails for a missing run grant while the only deny is on write,
    so the line must not claim that deny applies."""
    from starlette.requests import Request

    from agno.os.middleware.jwt import JWTMiddleware

    db = SqliteDb(db_file=str(tmp_path / "ambig.db"))
    authz = Authorization(db=db, verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID)
    authz.define_role("reader", ["agents:*:read", ("agents:secret:write", "deny")])
    authz.assign("rae", "reader")
    agents = [Agent(id="secret", name="S", db=InMemoryDb())]
    app = AgentOS(id=OS_ID, db=db, agents=agents, authorization=authz).get_app()
    TestClient(app).get("/health")  # materialise the routes and app.state the gate reads

    mw = JWTMiddleware(app=None, verification_keys=[SECRET], algorithm="HS256")
    scope = {"type": "http", "method": "GET", "path": "/agents/secret", "headers": [], "query_string": b"", "app": app}
    request = Request(scope)
    request.state.user_id = "rae"
    request.state.claims = {"sub": "rae"}
    request.state.scopes = []
    request.state.authorization_enabled = True
    with _warnings() as messages:
        response = await mw._acheck_scopes(
            request,
            "GET",
            "/agents/secret",
            [],
            None,
            None,
            scope_mappings={"GET /agents/*": ["agents:read", "agents:run"]},
        )
    assert response is not None and response.status_code == 403
    line = [m for m in messages if "/agents/secret" in m][-1]
    assert "explicit deny" not in line  # the write deny did not decide this request
    assert "holds role(s) ['reader']" in line


def test_denial_of_a_directory_user_with_no_assignment_names_the_default_role(tmp_path):
    """A known directory user with no assignment is evaluated through the is_default role at
    decision time, so 'holds no role' would be wrong: the default role decided."""
    from agno.os.authz import UserDirectory

    db = SqliteDb(db_file=str(tmp_path / "default.db"))
    authz = Authorization(db=db, verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID)
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"], default=True)
    users = UserDirectory(db=db, auto_provision=False)
    users.upsert("dana", email="d@co")  # in the directory, never assigned a role
    agents = [Agent(id="a", name="A", db=InMemoryDb())]
    client = TestClient(
        AgentOS(
            id=OS_ID,
            db=db,
            agents=agents,
            authorization=authz,
            user_directory=users,
        ).get_app()
    )
    with _warnings() as messages:
        assert client.get("/agents/a", headers=_token("dana", [])).status_code == 200  # the default role reads
        r = client.get("/config", headers=_token("dana", []))
    assert r.status_code == 403
    line = [m for m in messages if "/config" in m][-1]
    assert "holds no role" not in line
    assert "default role ['viewer']" in line and "does not authorize GET /config" in line


# ------------------------------------------------------------------ the explanation follows the plane that decided
# Three ways the line could say something untrue: blaming roles when a custom provider decided,
# citing trust_token_scopes=False when that flag was not the reason, and claiming the default role
# applied when the engine (reading through its own db) never applied it.


def test_denial_under_a_custom_provider_does_not_blame_managed_roles(tmp_path):
    """Authorization(authorization_provider=...) decides alone even when roles are defined on the
    object, so the line must not cite roles or token-scope trust that never took part."""
    from agno.os.authz import AuthorizationContext, AuthorizationProvider

    class _DenyAll(AuthorizationProvider):
        def check(self, ctx: AuthorizationContext) -> bool:
            return False

        def accessible_resource_ids(self, ctx: AuthorizationContext):
            return set()

        def authorize_route(self, ctx: AuthorizationContext, required_scopes) -> bool:
            return False

    db = SqliteDb(db_file=str(tmp_path / "custom.db"))
    authz = Authorization(
        db=db,
        verification_keys=[SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
        authorization_provider=_DenyAll(),
        trust_token_scopes=True,
    )
    authz.define_role("viewer", ["agents:*:read"])  # defined, but the override decides
    authz.assign("vic", "viewer")
    agents = [Agent(id="a", name="A", db=InMemoryDb())]
    client = TestClient(AgentOS(id=OS_ID, db=db, agents=agents, authorization=authz).get_app())
    with _warnings() as messages:
        r = client.get("/agents/a", headers=_token("vic", ["agents:read"]))
    assert r.status_code == 403
    line = [m for m in messages if "/agents/a" in m][-1]
    assert "the configured authorization provider refused it" in line
    assert "role" not in line.lower()
    assert "trust_token_scopes" not in line


def test_denial_with_trusted_token_scopes_keeps_the_scope_wording(tmp_path):
    """Under trust_token_scopes=True the caller's scopes are authoritative, so the honest line is
    required-versus-held; it must never cite trust_token_scopes=False."""
    db = SqliteDb(db_file=str(tmp_path / "trust.db"))
    authz = Authorization(
        db=db,
        verification_keys=[SECRET],
        algorithm="HS256",
        verify_audience=True,
        audience=OS_ID,
        trust_token_scopes=True,
    )
    authz.define_role("viewer", ["agents:*:read"])
    authz.assign("bob", "viewer")
    agents = [Agent(id="a", name="A", db=InMemoryDb())]
    client = TestClient(AgentOS(id=OS_ID, db=db, agents=agents, authorization=authz).get_app())
    with _warnings() as messages:
        r = client.get("/config", headers=_token("bob", ["agents:read"]))  # a scope, not the one needed
    assert r.status_code == 403
    line = [m for m in messages if "/config" in m][-1]
    assert line.startswith("Insufficient scopes for GET /config")
    assert "trust_token_scopes=False" not in line


def test_denial_on_a_split_db_does_not_claim_a_default_role_that_never_applied(tmp_path):
    """The engine applies the default role only to a directory user it can see through ITS db; with
    the directory on another db it fails closed. The line must report what the engine did, not what
    the directory alone suggests."""
    from agno.os.authz import UserDirectory

    roles_db = SqliteDb(db_file=str(tmp_path / "roles.db"))
    users_db = SqliteDb(db_file=str(tmp_path / "users.db"))
    authz = Authorization(
        db=roles_db, verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID
    )
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"], default=True)
    users = UserDirectory(db=users_db, auto_provision=False)
    users.upsert("dana", email="d@co")
    agents = [Agent(id="a", name="A", db=InMemoryDb())]
    client = TestClient(
        AgentOS(id=OS_ID, db=roles_db, agents=agents, authorization=authz, user_directory=users).get_app()
    )
    with _warnings() as messages:
        r = client.get("/agents/a", headers=_token("dana", []))
    assert r.status_code == 403  # the default never applied: the engine cannot see dana
    line = [m for m in messages if "/agents/a" in m][-1]
    assert "default role" not in line
    assert "holds no role" in line


def test_denial_of_a_directory_user_named_like_a_role_does_not_claim_the_default(tmp_path):
    """A subject whose id equals a role slug is refused by the engine's collision guard before the
    default role is ever considered, so the line must not report the default as having decided."""
    from agno.os.authz import UserDirectory

    db = SqliteDb(db_file=str(tmp_path / "collide.db"))
    authz = Authorization(db=db, verification_keys=[SECRET], algorithm="HS256", verify_audience=True, audience=OS_ID)
    authz.define_role("admin", ["agent_os:admin"])
    authz.define_role("viewer", ["agents:*:read"], default=True)
    users = UserDirectory(db=db, auto_provision=False)
    users.upsert("viewer", email="v@co")  # a directory user named like the default role, no assignment
    agents = [Agent(id="a", name="A", db=InMemoryDb())]
    client = TestClient(AgentOS(id=OS_ID, db=db, agents=agents, authorization=authz, user_directory=users).get_app())
    with _warnings() as messages:
        r = client.get("/agents/a", headers=_token("viewer", []))
    assert r.status_code == 403  # refused by the collision guard, although 'viewer' would grant the read
    line = [m for m in messages if "Denied GET /agents/a" in m][-1]
    assert "default role" not in line
    assert "holds no role" in line
