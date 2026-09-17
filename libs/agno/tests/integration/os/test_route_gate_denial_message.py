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
    assert "holds role(s) ['viewer']" in line and "do not grant ['config:read']" in line
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
    assert "token carries role(s) ['viewer']" in line and "do not grant ['config:read']" in line
    assert "holds no role" not in line and "User has" not in line
