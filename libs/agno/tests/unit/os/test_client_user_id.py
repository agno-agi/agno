from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.client import AgentOSClient
from agno.db.base import SessionType

# ---------------------------------------------------------------------------
# SDK Client tests — verify user_id is serialized into HTTP request params
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_agent_serializes_empty_string_user_id():
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {"run_id": "run-1", "agent_id": "a-1", "content": "ok", "created_at": 0}
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_data
        await client.run_agent(agent_id="a-1", message="hi", user_id="", session_id="")

        form_data = mock_post.call_args[0][1]
        assert form_data["user_id"] == ""
        assert form_data["session_id"] == ""


@pytest.mark.asyncio
async def test_run_agent_omits_none_user_id():
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {"run_id": "run-1", "agent_id": "a-1", "content": "ok", "created_at": 0}
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_data
        await client.run_agent(agent_id="a-1", message="hi")

        form_data = mock_post.call_args[0][1]
        assert "user_id" not in form_data
        assert "session_id" not in form_data


@pytest.mark.asyncio
async def test_run_team_serializes_empty_string_user_id():
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {"run_id": "run-1", "team_id": "t-1", "content": "ok", "created_at": 0}
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_data
        await client.run_team(team_id="t-1", message="hi", user_id="", session_id="")

        form_data = mock_post.call_args[0][1]
        assert form_data["user_id"] == ""
        assert form_data["session_id"] == ""


@pytest.mark.asyncio
async def test_run_workflow_serializes_empty_string_user_id():
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {"run_id": "run-1", "workflow_id": "w-1", "content": "ok", "created_at": 0}
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_data
        await client.run_workflow(workflow_id="w-1", message="hi", user_id="", session_id="")

        form_data = mock_post.call_args[0][1]
        assert form_data["user_id"] == ""
        assert form_data["session_id"] == ""


@pytest.mark.asyncio
async def test_delete_session_includes_user_id_in_params():
    client = AgentOSClient(base_url="http://localhost:7777")
    with patch.object(client, "_adelete", new_callable=AsyncMock) as mock_delete:
        await client.delete_session("sess-1", user_id="alice")

        params = mock_delete.call_args.kwargs["params"]
        assert params["user_id"] == "alice"


@pytest.mark.asyncio
async def test_delete_session_omits_user_id_when_none():
    client = AgentOSClient(base_url="http://localhost:7777")
    with patch.object(client, "_adelete", new_callable=AsyncMock) as mock_delete:
        await client.delete_session("sess-1")

        params = mock_delete.call_args.kwargs.get("params", {})
        assert "user_id" not in params


@pytest.mark.asyncio
async def test_delete_sessions_includes_user_id_in_params():
    client = AgentOSClient(base_url="http://localhost:7777")
    with patch.object(client, "_adelete", new_callable=AsyncMock) as mock_delete:
        await client.delete_sessions(
            session_ids=["s-1"],
            session_types=[SessionType.AGENT],
            user_id="alice",
        )

        params = mock_delete.call_args.kwargs["params"]
        assert params["user_id"] == "alice"


@pytest.mark.asyncio
async def test_rename_session_includes_user_id_in_params():
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "agent_session_id": "as-1",
        "session_id": "sess-1",
        "session_name": "Renamed",
        "agent_id": "a-1",
        "user_id": "alice",
    }
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_data
        await client.rename_session("sess-1", "Renamed", user_id="alice")

        params = mock_post.call_args.kwargs["params"]
        assert params["user_id"] == "alice"


# ---------------------------------------------------------------------------
# FastAPI Router tests — verify Query(user_id) actually binds from ?user_id=
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    from agno.session.agent import AgentSession

    db = MagicMock()
    db.delete_session = MagicMock()
    db.delete_sessions = MagicMock()
    db.rename_session = MagicMock(
        return_value=AgentSession(
            session_id="sess-1",
            agent_id="a-1",
            user_id="alice",
            session_data={"session_name": "Renamed"},
            runs=[],
            created_at=0,
            updated_at=0,
        )
    )
    return db


@pytest.fixture
def test_app(mock_db, monkeypatch):
    monkeypatch.delenv("OS_SECURITY_KEY", raising=False)

    from agno.os.routers.session.session import get_session_router
    from agno.os.settings import AgnoAPISettings

    settings = AgnoAPISettings()
    dbs = {"default": [mock_db]}
    router = get_session_router(dbs, settings)

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def test_app_with_jwt(mock_db, monkeypatch):
    """Test app with simulated JWT middleware that sets request.state.user_id."""
    monkeypatch.delenv("OS_SECURITY_KEY", raising=False)

    from starlette.middleware.base import BaseHTTPMiddleware

    from agno.os.routers.session.session import get_session_router
    from agno.os.settings import AgnoAPISettings

    settings = AgnoAPISettings()
    dbs = {"default": [mock_db]}
    router = get_session_router(dbs, settings)

    app = FastAPI()
    app.include_router(router)

    class FakeJWTMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.user_id = "jwt_alice"
            return await call_next(request)

    app.add_middleware(FakeJWTMiddleware)
    return app


def test_router_delete_session_jwt_overrides_query_user_id(test_app_with_jwt, mock_db):
    """JWT user_id must always override client-supplied ?user_id (IDOR protection)."""
    client = TestClient(test_app_with_jwt)
    resp = client.delete("/sessions/sess-1?user_id=attacker")
    assert resp.status_code == 204

    call_kwargs = mock_db.delete_session.call_args.kwargs
    assert call_kwargs["user_id"] == "jwt_alice"
    assert call_kwargs["session_id"] == "sess-1"


def test_router_delete_sessions_jwt_overrides_query_user_id(test_app_with_jwt, mock_db):
    """JWT user_id must override client-supplied ?user_id for bulk delete."""
    client = TestClient(test_app_with_jwt)
    resp = client.request(
        "DELETE",
        "/sessions?user_id=attacker",
        json={"session_ids": ["s-1"], "session_types": ["agent"]},
    )
    assert resp.status_code == 204

    call_kwargs = mock_db.delete_sessions.call_args.kwargs
    assert call_kwargs["user_id"] == "jwt_alice"


def test_router_rename_session_jwt_overrides_query_user_id(test_app_with_jwt, mock_db):
    """JWT user_id must override client-supplied ?user_id for rename."""
    client = TestClient(test_app_with_jwt)
    resp = client.post(
        "/sessions/sess-1/rename?user_id=attacker",
        json={"session_name": "Hacked"},
    )
    assert resp.status_code == 200

    call_kwargs = mock_db.rename_session.call_args.kwargs
    assert call_kwargs["user_id"] == "jwt_alice"
    assert call_kwargs["session_id"] == "sess-1"


def test_router_delete_session_receives_user_id_from_query(test_app, mock_db):
    """Verify FastAPI binds user_id from ?user_id=alice to the endpoint param."""
    client = TestClient(test_app)
    resp = client.delete("/sessions/sess-1?user_id=alice")
    assert resp.status_code == 204

    mock_db.delete_session.assert_called_once()
    call_kwargs = mock_db.delete_session.call_args.kwargs
    assert call_kwargs["user_id"] == "alice"
    assert call_kwargs["session_id"] == "sess-1"


def test_router_delete_session_user_id_defaults_to_none(test_app, mock_db):
    """Without ?user_id=, the param should be None (no user scoping)."""
    client = TestClient(test_app)
    resp = client.delete("/sessions/sess-1")
    assert resp.status_code == 204

    call_kwargs = mock_db.delete_session.call_args.kwargs
    assert call_kwargs["user_id"] is None


def test_router_delete_sessions_receives_user_id_from_query(test_app, mock_db):
    """Verify bulk delete binds user_id from query string."""
    client = TestClient(test_app)
    resp = client.request(
        "DELETE",
        "/sessions?user_id=alice",
        json={"session_ids": ["s-1"], "session_types": ["agent"]},
    )
    assert resp.status_code == 204

    mock_db.delete_sessions.assert_called_once()
    call_kwargs = mock_db.delete_sessions.call_args.kwargs
    assert call_kwargs["user_id"] == "alice"


def test_router_rename_session_receives_user_id_from_query(test_app, mock_db):
    """Verify rename binds user_id from query string."""
    client = TestClient(test_app)
    resp = client.post(
        "/sessions/sess-1/rename?user_id=alice",
        json={"session_name": "Renamed"},
    )
    assert resp.status_code == 200

    mock_db.rename_session.assert_called_once()
    call_kwargs = mock_db.rename_session.call_args.kwargs
    assert call_kwargs["user_id"] == "alice"
    assert call_kwargs["session_id"] == "sess-1"
    assert call_kwargs["session_name"] == "Renamed"
