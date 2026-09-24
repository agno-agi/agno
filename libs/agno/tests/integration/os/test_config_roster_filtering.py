"""GET /config lists only the agents, teams and workflows the caller may read.

``config:read`` admits the caller to the OS description. It used to return every component's
id, name and description regardless of the caller's grants, while ``/agents`` filtered. Now the
roster goes through the same provider-backed filter as the list routes.
"""

import time

import jwt
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.authz import Authorization
from agno.team import Team

SECRET = "config-roster-secret-at-least-32-bytes!!"
OS_ID = "config-roster-os"


def _auth(scopes) -> dict:
    payload = {"sub": "someone", "aud": OS_ID, "scopes": scopes, "exp": int(time.time()) + 3600}
    return {"Authorization": f"Bearer {jwt.encode(payload, SECRET, algorithm='HS256')}"}


def _client(tmp_path, authorization=True):
    db = SqliteDb(db_file=str(tmp_path / "cfg.db"))
    a1 = Agent(id="a1", name="Agent One", db=InMemoryDb())
    a2 = Agent(id="a2", name="Agent Two", db=InMemoryDb())
    team = Team(id="t1", name="Team", members=[a1], db=InMemoryDb())
    kwargs = {}
    if authorization:
        kwargs["authorization"] = Authorization(verification_keys=[SECRET], audience=OS_ID, algorithm="HS256")
    return TestClient(AgentOS(id=OS_ID, db=db, agents=[a1, a2], teams=[team], **kwargs).get_app())


def _ids(payload, key):
    return sorted(item["id"] for item in payload[key])


def test_config_roster_is_filtered_by_grant(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/config", headers=_auth(["config:read", "agents:a1:read"]))
    assert resp.status_code == 200, resp.text
    assert _ids(resp.json(), "agents") == ["a1"]
    assert _ids(resp.json(), "teams") == []


def test_config_roster_is_complete_for_a_global_grant(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/config", headers=_auth(["config:read", "agents:read", "teams:read"]))
    assert _ids(resp.json(), "agents") == ["a1", "a2"]
    assert _ids(resp.json(), "teams") == ["t1"]


def test_config_roster_is_complete_for_an_admin(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/config", headers=_auth(["agent_os:admin"]))
    assert _ids(resp.json(), "agents") == ["a1", "a2"]


def test_config_roster_is_unfiltered_without_authorization(tmp_path):
    client = _client(tmp_path, authorization=False)
    resp = client.get("/config")
    assert _ids(resp.json(), "agents") == ["a1", "a2"]
