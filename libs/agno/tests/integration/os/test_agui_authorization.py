"""AGUI authorization gate.

AGUI mounts POST {prefix}/agui, which runs the bound agent/team, and does not
self-authenticate -- so under authorization=True it must be scope-gated. Interfaces
declare their own scope mappings (Interface.get_scope_mappings), merged at startup
against the actual mount prefix, so a custom prefix is covered too.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.interfaces.agui import AGUI

JWT_SECRET = "test-secret-for-agui-authz"


def _token(scopes):
    payload = {
        "sub": "user-1",
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _client(prefix=""):
    agent = Agent(id="agui-agent", name="AGUI Agent", db=InMemoryDb())
    agent_os = AgentOS(
        id="agui-authz-os",
        agents=[agent],
        interfaces=[AGUI(agent=agent, prefix=prefix)],
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
    )
    return TestClient(agent_os.get_app())


@pytest.mark.parametrize("prefix", ["", "/chat/public"])
def test_agui_run_blocked_without_run_scope(prefix):
    client = _client(prefix)
    resp = client.post(
        f"{prefix}/agui",
        json={},
        headers={"Authorization": f"Bearer {_token(['config:read'])}"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize("prefix", ["", "/chat/public"])
def test_agui_run_passes_authorization_with_run_scope(prefix):
    # agents:run clears the scope gate (403 would fire in middleware before the body is
    # even validated); a bad body may then 422, which is fine -- we only assert not 401/403.
    client = _client(prefix)
    resp = client.post(
        f"{prefix}/agui",
        json={},
        headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
    )
    assert resp.status_code not in (401, 403), resp.text
