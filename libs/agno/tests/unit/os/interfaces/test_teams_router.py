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
    """No credentials plus the bypass flag: the only shape in which the bypass
    applies. Caller must ``env_patch.stop()`` after the request runs, since the
    flag is read lazily inside the webhook."""
    router = APIRouter()
    env_patch = patch.dict(
        "os.environ",
        {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "true"},
        clear=True,
    )
    env_patch.start()
    attach_routes(router, agent=agent, team=team, workflow=workflow)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), env_patch


# === attach_routes: required entity guard ===


def test_attach_routes_requires_entity():
    router = APIRouter()
    with patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app", "MICROSOFT_APP_PASSWORD": "pw"},
        clear=True,
    ):
        with pytest.raises(ValueError, match="agent, team, or workflow"):
            attach_routes(router)


# === _SESSION_DISPATCH shape ===


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


# === _resolve_session_config ===


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


# === _format_reasoning ===


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


# === GET /status ===


def test_status_endpoint_reports_available():
    client, env_patch = _build_test_client(agent=_stub_agent_with_db())
    try:
        resp = client.get("/status")
        assert resp.status_code == 200
        assert resp.json() == {"status": "available"}
    finally:
        env_patch.stop()


# === POST /messages — JWT rejection and body validation ===


def test_webhook_rejects_when_jwt_fails():
    """Enforced before the body is parsed."""
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


# === Post-run conversation-reference write ===


def test_conversation_ref_is_written_to_the_run_session_not_the_newest():
    """A concurrent message from the same user can make a newer session exist by
    the time this run finishes, so the two are not the same row."""
    run_session = SimpleNamespace(session_id="teams:agent-1:user-1:OLD", session_data={"existing": "kept"})
    newer_session = SimpleNamespace(session_id="teams:agent-1:user-1:NEW", session_data={})
    seen = {}

    async def fake_arun(text, **kwargs):
        return SimpleNamespace(
            status="COMPLETED", content="ok", session_id="teams:agent-1:user-1:OLD", reasoning_content=None
        )

    async def fake_aget_session(session_id=None):
        seen["requested"] = session_id
        return run_session if session_id == run_session.session_id else newer_session

    async def fake_asave_session(session):
        seen["saved"] = session

    fake_db = MagicMock(spec=BaseDb)
    # 1st call: the pre-run lookup resolves the run onto OLD.
    # 2nd call: whatever a latest-by-user re-read would have found -- NEW.
    fake_db.get_sessions = MagicMock(side_effect=[[run_session], [newer_session]])
    agent = SimpleNamespace(
        id="agent-1",
        name="Stub Agent",
        db=fake_db,
        arun=fake_arun,
        aget_session=fake_aget_session,
        asave_session=fake_asave_session,
    )

    client, env_patch = _build_test_client(agent=agent)
    try:
        with (
            patch("agno.os.interfaces.teams.router.typing_indicator_async"),
            patch("agno.os.interfaces.teams.router.send_teams_message_async"),
        ):
            resp = client.post(
                "/messages",
                json={
                    "type": "message",
                    "id": "act-1",
                    "serviceUrl": "https://svc/",
                    "from": {"id": "29:u", "aadObjectId": "user-1"},
                    "conversation": {"id": "conv-1"},
                    "recipient": {"id": "28:bot"},
                    "text": "hello",
                },
            )
        assert resp.status_code == 200
    finally:
        env_patch.stop()

    # Outcome first: the ref belongs on the run's session and nowhere else.
    # A latest-by-user re-read puts it on newer_session instead.
    assert run_session.session_data["teams_conversation_ref"]["conversation_id"] == "conv-1"
    assert newer_session.session_data == {}
    # the merge must not drop keys that were already on the session
    assert run_session.session_data["existing"] == "kept"
    # and it got there by asking for that id, not by taking whatever was newest
    assert seen["requested"] == "teams:agent-1:user-1:OLD"
    assert seen["saved"].session_id == "teams:agent-1:user-1:OLD"


# === Operation ids ===


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
