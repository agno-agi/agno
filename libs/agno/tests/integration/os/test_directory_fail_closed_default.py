"""The directory kill switch fails closed by default.

``disabled`` is a revocation that outlives a valid token. A directory read that errors while
checking it used to let the request through unless the operator opted into ``fail_closed``,
so an outage silently re-enabled every revoked account. The default is now closed (503);
``fail_closed=False`` keeps the availability-first behaviour for deployments that want it.
"""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.authz import Authorization, UserDirectory

SECRET = "directory-fail-closed-secret-32-bytes!!"
OS_ID = "directory-fail-closed-os"


def _auth(sub: str) -> dict:
    payload = {"sub": sub, "aud": OS_ID, "scopes": ["agents:read"], "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(payload, SECRET, algorithm='HS256')}"}


def _client(tmp_path, directory: UserDirectory) -> TestClient:
    db = SqliteDb(db_file=str(tmp_path / "dir.db"))
    authz = Authorization(verification_keys=[SECRET], audience=OS_ID, algorithm="HS256")
    agent_os = AgentOS(
        id=OS_ID, db=db, agents=[Agent(id="a", db=InMemoryDb())], authorization=authz, user_directory=directory
    )
    return TestClient(agent_os.get_app())


def _break_directory(directory: UserDirectory) -> None:
    async def boom(*args, **kwargs):
        raise RuntimeError("directory database unreachable")

    directory.ais_disabled = boom  # type: ignore[method-assign]
    directory.aget = boom  # type: ignore[method-assign]


def test_default_is_fail_closed():
    assert UserDirectory().fail_closed is True


def test_a_directory_error_denies_by_default(tmp_path):
    directory = UserDirectory(auto_provision=False)
    client = _client(tmp_path, directory)
    assert client.get("/agents", headers=_auth("alice")).status_code == 200
    _break_directory(directory)
    resp = client.get("/agents", headers=_auth("alice"))
    assert resp.status_code == 503
    assert resp.json()["detail"] == "User directory unavailable"


def test_fail_closed_false_keeps_the_request_flowing(tmp_path):
    directory = UserDirectory(auto_provision=False, fail_closed=False)
    client = _client(tmp_path, directory)
    _break_directory(directory)
    assert client.get("/agents", headers=_auth("alice")).status_code == 200


@pytest.mark.parametrize("auto_provision", [True, False])
def test_the_default_applies_to_both_provisioning_modes(tmp_path, auto_provision):
    directory = UserDirectory(auto_provision=auto_provision)
    client = _client(tmp_path, directory)
    _break_directory(directory)
    assert client.get("/agents", headers=_auth("alice")).status_code == 503
