"""AGUI authorization + run-identity gate.

AGUI mounts POST {prefix}/agui, which runs the bound agent/team, and does not
self-authenticate -- so under authorization=True it must be scope-gated. Interfaces
declare their own scope mappings (Interface.get_scope_mappings), merged at startup
against the actual mount prefix, so a custom prefix is covered too.

Run identity must be pinned to the authenticated principal: forwardedProps.user_id
is client-supplied and is honoured for attribution only when the caller is anonymous
(and never for a reserved principal) -- the same contract as A2A and REST.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.interfaces.agui import AGUI
from agno.team import Team

JWT_SECRET = "test-secret-for-agui-authz"


def _token(scopes, sub="user-1"):
    payload = {
        "sub": sub,
        "scopes": scopes,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _run_body(user_id=None):
    return {
        "thread_id": "thread-1",
        "run_id": "run-1",
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "hi"}],
        "tools": [],
        "context": [],
        "forwarded_props": {"user_id": user_id} if user_id else {},
    }


async def _empty_stream():
    return
    yield


def _build(prefix="", authorization=True, team=False):
    """Build (entity, client) with AGUI mounted; entity is the instance runs dispatch to."""
    agent = Agent(id="agui-agent", name="AGUI Agent", db=InMemoryDb())
    if team:
        entity = Team(id="agui-team", name="AGUI Team", members=[agent], db=InMemoryDb())
        agui = AGUI(team=entity, prefix=prefix)
    else:
        entity = agent
        agui = AGUI(agent=agent, prefix=prefix)
    os_kwargs = (
        {
            "authorization": True,
            "authorization_config": AuthorizationConfig(verification_keys=[JWT_SECRET], algorithm="HS256"),
        }
        if authorization
        else {}
    )
    agent_os = AgentOS(id="agui-authz-os", agents=[agent], interfaces=[agui], **os_kwargs)
    return entity, TestClient(agent_os.get_app())


# ------------------------------------------------------------------ scope gating


@pytest.mark.parametrize("prefix", ["", "/chat/public"])
def test_agui_run_blocked_without_run_scope(prefix):
    _entity, client = _build(prefix)
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
    _entity, client = _build(prefix)
    resp = client.post(
        f"{prefix}/agui",
        json={},
        headers={"Authorization": f"Bearer {_token(['agents:run'])}"},
    )
    assert resp.status_code not in (401, 403), resp.text


def test_agui_team_gated_on_teams_run():
    # A team-bound AGUI requires teams:run, not agents:run.
    _entity, client = _build(team=True)
    resp = client.post("/agui", json={}, headers={"Authorization": f"Bearer {_token(['agents:run'])}"})
    assert resp.status_code == 403, resp.text
    resp = client.post("/agui", json={}, headers={"Authorization": f"Bearer {_token(['teams:run'])}"})
    assert resp.status_code not in (401, 403), resp.text


def test_agui_scope_family_matches_router_dispatch_when_both_set():
    # The router dispatches agent-wins (`entity = agent or team`); the scope mapping must
    # gate on the SAME family, or teams:run tokens could execute the agent and legitimate
    # agents:run holders would get 403.
    agent = Agent(id="agui-agent", name="AGUI Agent", db=InMemoryDb())
    team = Team(id="agui-team", name="AGUI Team", members=[agent], db=InMemoryDb())
    agui = AGUI(agent=agent, team=team)
    assert agui.get_scope_mappings() == {"POST /agui": ["agents:run"]}


# ------------------------------------------------------------------ identity pinning


def test_authenticated_caller_identity_pinned():
    # Authenticated user-1 supplies forwardedProps user_id "victim" -> the run must be
    # attributed to user-1 (the same B2-class fix A2A got; AGUI writes sessions/memories).
    entity, client = _build()
    with patch.object(entity, "arun", MagicMock(side_effect=lambda **kwargs: _empty_stream())) as mock_arun:
        resp = client.post(
            "/agui",
            json=_run_body(user_id="victim"),
            headers={"Authorization": f"Bearer {_token(['agents:run'], sub='user-1')}"},
        )
        assert resp.status_code == 200, resp.text
        mock_arun.assert_called_once()
        assert mock_arun.call_args.kwargs["user_id"] == "user-1"


def test_anonymous_caller_forwarded_props_honored():
    # Backward-compat: with no auth configured, forwardedProps user_id still attributes runs.
    entity, client = _build(authorization=False)
    with patch.object(entity, "arun", MagicMock(side_effect=lambda **kwargs: _empty_stream())) as mock_arun:
        resp = client.post("/agui", json=_run_body(user_id="external-user"))
        assert resp.status_code == 200, resp.text
        assert mock_arun.call_args.kwargs["user_id"] == "external-user"


def test_anonymous_reserved_principal_rejected():
    # An anonymous caller must not claim a server-reserved principal (sa:* / __scheduler__).
    _entity, client = _build(authorization=False)
    resp = client.post("/agui", json=_run_body(user_id="sa:evil"))
    assert resp.status_code == 403, resp.text
