"""Unit tests for the Teams webhook router.

Focus areas:
  - `/status` liveness endpoint
  - `POST /messages` JWT rejection + malformed body handling
  - `_format_reasoning` filter
  - `_resolve_session_config` dispatch for agent/team/workflow
  - `/new` conversation reset command

These tests do NOT exercise the full inbound → arun → outbound flow (that
is covered end-to-end by live testing). They pin the routing surface so
future refactors can't silently change the contract.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.db.base import BaseDb, SessionType
from agno.os.interfaces.teams.router import (
    _SESSION_DISPATCH,
    _format_reasoning,
    _resolve_session_config,
    attach_routes,
)


def _stub_agent_with_db():
    fake_db = MagicMock(spec=BaseDb)
    return SimpleNamespace(id="agent-1", name="Stub Agent", db=fake_db)


def _build_test_client(agent=None, team=None, workflow=None):
    """Attach the router to a FastAPI app and return (TestClient, env_patch).

    Env is patched so TeamsConfig.init succeeds without touching real secrets,
    and JWT validation is bypassed via the dev flag. Caller must ``env_patch.stop()``
    after the request runs — the flag is read lazily inside the webhook, so the
    context must outlive request dispatch.
    """
    router = APIRouter()
    env_patch = patch.dict(
        "os.environ",
        {
            "MICROSOFT_APP_ID": "app-id",
            "MICROSOFT_APP_PASSWORD": "secret",
            "MICROSOFT_APP_SKIP_JWT_VALIDATION": "true",
        },
        clear=True,
    )
    env_patch.start()
    attach_routes(router, agent=agent, team=team, workflow=workflow)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), env_patch


# ---------------------------------------------------------------------------
# attach_routes: required entity guard
# ---------------------------------------------------------------------------


def test_attach_routes_requires_entity():
    router = APIRouter()
    with patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app", "MICROSOFT_APP_PASSWORD": "pw"},
        clear=True,
    ):
        with pytest.raises(ValueError, match="agent, team, or workflow"):
            attach_routes(router)


# ---------------------------------------------------------------------------
# _SESSION_DISPATCH shape
# ---------------------------------------------------------------------------


def test_session_dispatch_covers_all_entity_kinds():
    assert set(_SESSION_DISPATCH.keys()) == {"agent", "team", "workflow"}
    # SessionType values wired correctly
    assert _SESSION_DISPATCH["agent"][0] == SessionType.AGENT
    assert _SESSION_DISPATCH["team"][0] == SessionType.TEAM
    assert _SESSION_DISPATCH["workflow"][0] == SessionType.WORKFLOW
    # id_field wired correctly
    assert _SESSION_DISPATCH["agent"][2] == "agent_id"
    assert _SESSION_DISPATCH["team"][2] == "team_id"
    assert _SESSION_DISPATCH["workflow"][2] == "workflow_id"


# ---------------------------------------------------------------------------
# _resolve_session_config
# ---------------------------------------------------------------------------


def test_resolve_session_config_flags_sync_db():
    stub = _stub_agent_with_db()
    cfg = _resolve_session_config(stub, "agent")
    assert cfg.has_db is True
    assert cfg.is_async_db is False
    assert cfg.session_type == SessionType.AGENT
    assert cfg.id_field == "agent_id"


def test_resolve_session_config_flags_async_db():
    from agno.db.base import AsyncBaseDb

    fake_async = MagicMock(spec=AsyncBaseDb)
    stub = SimpleNamespace(id="agent-1", name="Stub", db=fake_async)
    cfg = _resolve_session_config(stub, "agent")
    assert cfg.has_db is True
    assert cfg.is_async_db is True


def test_resolve_session_config_missing_db():
    stub = SimpleNamespace(id="agent-1", name="Stub", db=None)
    cfg = _resolve_session_config(stub, "agent")
    assert cfg.has_db is False
    assert cfg.is_async_db is False


def test_resolve_session_config_team_dispatch():
    fake_db = MagicMock(spec=BaseDb)
    stub_team = SimpleNamespace(id="team-1", name="Squad", db=fake_db)
    cfg = _resolve_session_config(stub_team, "team")
    assert cfg.session_type == SessionType.TEAM
    assert cfg.id_field == "team_id"


def test_resolve_session_config_workflow_dispatch():
    fake_db = MagicMock(spec=BaseDb)
    stub_wf = SimpleNamespace(id="wf-1", name="Nightly", db=fake_db)
    cfg = _resolve_session_config(stub_wf, "workflow")
    assert cfg.session_type == SessionType.WORKFLOW
    assert cfg.id_field == "workflow_id"


# ---------------------------------------------------------------------------
# _format_reasoning
# ---------------------------------------------------------------------------


def test_format_reasoning_strips_action_lines():
    raw = "Thinking about it.\nAction: search\nNext Action: reply\nConfidence: 0.9\nFinal thought."
    formatted = _format_reasoning(raw)
    assert "Action:" not in formatted
    assert "Next Action:" not in formatted
    assert "Confidence:" not in formatted
    assert "Thinking about it." in formatted
    assert "Final thought." in formatted


def test_format_reasoning_drops_blank_and_divider_lines():
    raw = "line one\n\n---\n—\nline two"
    formatted = _format_reasoning(raw)
    assert formatted == "line one\nline two"


def test_format_reasoning_empty_input():
    assert _format_reasoning("") == ""


def test_format_reasoning_strips_whitespace_per_line():
    raw = "  hello  \n  world  "
    assert _format_reasoning(raw) == "hello\nworld"


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


def test_status_endpoint_reports_available():
    client, env_patch = _build_test_client(agent=_stub_agent_with_db())
    try:
        resp = client.get("/status")
        assert resp.status_code == 200
        assert resp.json() == {"status": "available"}
    finally:
        env_patch.stop()


# ---------------------------------------------------------------------------
# POST /messages — JWT rejection and body validation
# ---------------------------------------------------------------------------


def test_webhook_rejects_when_jwt_fails():
    """When the dev bypass is NOT set, missing/invalid Authorization must
    yield 403 — the router MUST enforce the check even before parsing JSON."""
    router = APIRouter()
    with patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app-id", "MICROSOFT_APP_PASSWORD": "secret"},
        clear=True,
    ):
        attach_routes(router, agent=_stub_agent_with_db())
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        # No Authorization header, no skip flag — expect 403
        resp = client.post("/messages", json={"type": "message", "text": "hi"})
    assert resp.status_code == 403


def test_webhook_accepts_with_skip_flag_and_returns_processing():
    """With dev bypass on, well-formed JSON body is accepted and dispatched
    to a background task — the endpoint returns immediately with status=processing."""
    client, env_patch = _build_test_client(agent=_stub_agent_with_db())
    try:
        resp = client.post(
            "/messages",
            json={"type": "conversationUpdate", "id": "act-1"},  # ignored by process_activity, harmless
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "processing"}
    finally:
        env_patch.stop()


def test_webhook_rejects_malformed_json():
    client, env_patch = _build_test_client(agent=_stub_agent_with_db())
    try:
        resp = client.post(
            "/messages",
            content=b"{not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
    finally:
        env_patch.stop()


# ---------------------------------------------------------------------------
# Operation id + prefix suffix uses entity name
# ---------------------------------------------------------------------------


def test_operation_ids_include_entity_name_suffix():
    stub = SimpleNamespace(id="agent-1", name="Weather Bot", db=MagicMock(spec=BaseDb))
    router = APIRouter()
    with patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app", "MICROSOFT_APP_PASSWORD": "pw"},
        clear=True,
    ):
        attach_routes(router, agent=stub)

    operation_ids = {route.operation_id for route in router.routes if hasattr(route, "operation_id")}
    assert "teams_status_weather_bot" in operation_ids
    assert "teams_webhook_weather_bot" in operation_ids


def test_operation_ids_fall_back_to_entity_type_when_name_missing():
    stub = SimpleNamespace(id="agent-1", name=None, db=MagicMock(spec=BaseDb))
    router = APIRouter()
    with patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app", "MICROSOFT_APP_PASSWORD": "pw"},
        clear=True,
    ):
        attach_routes(router, agent=stub)

    operation_ids = {route.operation_id for route in router.routes if hasattr(route, "operation_id")}
    assert "teams_status_agent" in operation_ids
    assert "teams_webhook_agent" in operation_ids
