from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.db.base import BaseDb, SessionType
from agno.db.sqlite import SqliteDb
from agno.os.interfaces.msteams.router import (
    _SESSION_DISPATCH,
    _format_reasoning,
    _resolve_session_config,
    attach_routes,
)
from agno.session.agent import AgentSession


@pytest.mark.parametrize("text", ["hello", "/new"])
def test_sync_session_db_calls_run_off_event_loop(text):
    import threading
    from unittest.mock import AsyncMock

    from agno.run.agent import RunOutput

    loop_threads = []
    db_threads = []
    db = MagicMock(spec=BaseDb)

    def get_sessions(**kwargs):
        db_threads.append(threading.get_ident())
        return [], 0

    def upsert_session(session):
        db_threads.append(threading.get_ident())
        return session

    async def typing(*args, **kwargs):
        loop_threads.append(threading.get_ident())

    db.get_sessions.side_effect = get_sessions
    db.upsert_session.side_effect = upsert_session
    agent = SimpleNamespace(
        id="agent", name="Agent", db=db, arun=AsyncMock(return_value=RunOutput(run_id="run", content="ok"))
    )
    client, env = _build_test_client(agent=agent)
    try:
        with (
            patch("agno.os.interfaces.msteams.router.typing_indicator_async", side_effect=typing),
            patch("agno.os.interfaces.msteams.router.send_teams_message_async", new_callable=AsyncMock),
        ):
            response = client.post(
                "/messages",
                json={
                    "type": "message",
                    "text": text,
                    "serviceUrl": "https://svc",
                    "from": {"id": "u"},
                    "conversation": {"id": "c", "conversationType": "groupChat"},
                },
            )
        assert response.status_code == 200
        assert len(db_threads) == 1
        assert len(loop_threads) == 1
        assert db_threads[0] != loop_threads[0]
        if text == "/new":
            db.upsert_session.assert_called_once()
            agent.arun.assert_not_called()
        else:
            db.get_sessions.assert_called_once()
            agent.arun.assert_awaited_once()
    finally:
        env.stop()


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
def test_streaming_entity_configuration_still_sends_one_final_reply(kind):
    from unittest.mock import AsyncMock

    from agno.agent import Agent
    from agno.models.base import Model
    from agno.models.message import MessageMetrics
    from agno.models.response import ModelResponse
    from agno.team import Team
    from agno.workflow import Step, Workflow

    class ReplyModel(Model):
        def __init__(self):
            super().__init__(id="offline", name="Offline", provider="test")

        def invoke(self, *args, **kwargs):
            return ModelResponse(role="assistant", content="final reply", response_usage=MessageMetrics())

        async def ainvoke(self, *args, **kwargs):
            return self.invoke()

        def invoke_stream(self, *args, **kwargs):
            yield self.invoke()

        async def ainvoke_stream(self, *args, **kwargs):
            yield self.invoke()

        def _parse_provider_response(self, response, **kwargs):
            return response

        def _parse_provider_response_delta(self, response):
            return response

    member = Agent(id="member", name="Member", model=ReplyModel(), telemetry=False)
    if kind == "agent":
        entity = Agent(id="agent", model=ReplyModel(), stream=True, telemetry=False)
    elif kind == "team":
        entity = Team(id="team", model=ReplyModel(), members=[member], stream=True, telemetry=False)
    else:
        entity = Workflow(id="workflow", steps=[Step(name="Reply", agent=member)], stream=True, telemetry=False)
    client, env = _build_test_client(**{kind: entity})
    try:
        with (
            patch("agno.os.interfaces.msteams.router.typing_indicator_async", new_callable=AsyncMock),
            patch("agno.os.interfaces.msteams.router.send_teams_message_async", new_callable=AsyncMock) as send,
        ):
            response = client.post(
                "/messages",
                json={
                    "type": "message",
                    "id": "request",
                    "text": "hello",
                    "serviceUrl": "https://svc",
                    "from": {"id": "u"},
                    "conversation": {"id": "c"},
                },
            )
        assert response.status_code == 200
        send.assert_awaited_once()
        assert send.call_args.args[2] == "final reply"
        assert entity.stream is True
    finally:
        env.stop()


def test_jwt_failure_does_not_log_untrusted_key_id(caplog):
    import json
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from agno.os.interfaces.msteams import security
    from agno.os.interfaces.msteams.helpers import MSTeamsConfig

    secret_url = "https://example.com/doc?sig=SECRET123"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="known-key", use="sig")
    token = jwt.encode(
        {
            "aud": "app",
            "iss": "https://api.botframework.com",
            "exp": int(time.time()) + 600,
            "serviceurl": "https://svc",
        },
        key,
        algorithm="RS256",
        headers={"kid": secret_url},
    )
    router = APIRouter()
    attach_routes(
        router,
        agent=SimpleNamespace(id="agent", name="Agent", db=None),
        config=MSTeamsConfig(app_id="app", app_password="secret", tenant_id="tenant"),
    )
    app = FastAPI()
    app.include_router(router)
    with (
        patch.object(security, "_jwk_client", security._BotFrameworkJWKClient(security._OPENID_METADATA_URL)),
        patch.object(security, "_fetch_openid_metadata", return_value={"jwks_uri": "https://example.com/keys"}),
        patch("jwt.PyJWKClient.fetch_data", return_value={"keys": [jwk]}),
        TestClient(app) as client,
    ):
        response = client.post(
            "/messages",
            json={"type": "conversationUpdate", "serviceUrl": "https://svc"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403
    assert secret_url not in caplog.text
    assert "SECRET123" not in caplog.text
    assert token not in caplog.text


@pytest.mark.parametrize("mode", ["ok", "error", "raise", "lookup", "save", "reset", "send", "unsupported"])
def test_activity_logs_never_include_content_or_exception_text(mode, caplog):
    import logging
    from unittest.mock import AsyncMock

    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus
    from agno.utils import log

    secret_url = "https://example.com/doc?sig=SECRET123"
    db = MagicMock(spec=BaseDb)
    db.get_sessions.return_value = ([], 0)
    if mode == "lookup":
        db.get_sessions.side_effect = RuntimeError(secret_url)
    if mode == "reset":
        db.upsert_session.side_effect = RuntimeError(secret_url)
    output = RunOutput(
        run_id="failed-run",
        content=secret_url if mode == "error" else "ok",
        status=RunStatus.error if mode == "error" else RunStatus.completed,
    )
    agent = SimpleNamespace(
        id="agent",
        name="Agent",
        db=db,
        arun=AsyncMock(return_value=output),
        aget_session=AsyncMock(return_value=SimpleNamespace(session_data={})),
        asave_session=AsyncMock(side_effect=RuntimeError(secret_url) if mode == "save" else None),
    )
    if mode == "raise":
        agent.arun.side_effect = RuntimeError(secret_url)
    client, env = _build_test_client(agent=agent)
    activity = {
        "type": secret_url if mode == "unsupported" else "message",
        "id": "logging",
        "text": secret_url,
        "serviceUrl": "https://svc",
        "from": {"id": "user"},
        "conversation": {"id": "personal", "conversationType": "personal"},
        "attachments": [{"name": "doc.pdf", "contentUrl": secret_url}],
    }
    if mode == "reset":
        activity["text"] = "/new"
    try:
        with (
            patch.object(log, "debug_on", True),
            caplog.at_level(logging.DEBUG, logger=log.logger.name),
            patch("agno.os.interfaces.msteams.router.typing_indicator_async", new_callable=AsyncMock),
            patch(
                "agno.os.interfaces.msteams.router.download_attachments_async",
                new_callable=AsyncMock,
                return_value=({}, []),
            ),
            patch(
                "agno.os.interfaces.msteams.router.send_teams_message_async",
                new_callable=AsyncMock,
                side_effect=RuntimeError(secret_url) if mode == "send" else None,
            ),
        ):
            assert client.post("/messages", json=activity).status_code == 200
        assert secret_url not in caplog.text
        assert "SECRET123" not in caplog.text
        if mode == "error":
            assert "failed-run" in caplog.text
            assert "status" in caplog.text
    finally:
        env.stop()


@pytest.mark.parametrize("second_id,expected,count", [("same", "duplicate", 1), ("different", "processing", 2)])
def test_redelivered_activity_runs_only_once(second_id, expected, count):
    from unittest.mock import AsyncMock

    from agno.run.agent import RunOutput

    entity = SimpleNamespace(
        id="a", name="Agent", db=None, arun=AsyncMock(return_value=RunOutput(run_id="r", content="ok"))
    )
    client, env = _build_test_client(agent=entity)
    activity = {
        "type": "message",
        "id": "same",
        "text": "hello",
        "serviceUrl": "https://svc",
        "from": {"id": "u"},
        "conversation": {"id": "c"},
    }
    try:
        with (
            patch("agno.os.interfaces.msteams.router.typing_indicator_async", new_callable=AsyncMock),
            patch("agno.os.interfaces.msteams.router.send_teams_message_async", new_callable=AsyncMock),
        ):
            assert client.post("/messages", json=activity).json() == {"status": "processing"}
            activity["id"] = second_id
            assert client.post("/messages", json=activity).json() == {"status": expected}
        assert entity.arun.await_count == count
    finally:
        env.stop()


def test_rejected_token_does_not_mark_activity_id():
    from unittest.mock import AsyncMock

    client, env = _build_test_client(agent=_stub_agent_with_db())
    activity = {"type": "conversationUpdate", "id": "retry-after-rejection"}
    try:
        with patch(
            "agno.os.interfaces.msteams.router.validate_bot_framework_jwt",
            new_callable=AsyncMock,
            side_effect=[None, {}, {}],
        ):
            assert client.post("/messages", json=activity).status_code == 403
            assert client.post("/messages", json=activity).json() == {"status": "processing"}
            assert client.post("/messages", json=activity).json() == {"status": "duplicate"}
    finally:
        env.stop()


def test_duplicate_tracker_is_per_mounted_interface():
    first, env1 = _build_test_client(agent=_stub_agent_with_db())
    second, env2 = _build_test_client(agent=_stub_agent_with_db())
    activity = {"type": "conversationUpdate", "id": "same-for-two-bots"}
    try:
        assert first.post("/messages", json=activity).json() == {"status": "processing"}
        assert first.post("/messages", json=activity).json() == {"status": "duplicate"}
        assert second.post("/messages", json=activity).json() == {"status": "processing"}
    finally:
        env2.stop()
        env1.stop()


@pytest.mark.parametrize("field", ["conversation", "from", "recipient", "attachments", "entities"])
@pytest.mark.parametrize("value", ["bad", 12, [None, "bad"]])
def test_webhook_treats_wrong_nested_types_as_missing(field, value):
    from unittest.mock import AsyncMock

    from agno.run.agent import RunOutput

    entity = SimpleNamespace(
        id="agent", name="Agent", db=None, arun=AsyncMock(return_value=RunOutput(run_id="r", content="final reply"))
    )
    client, env = _build_test_client(agent=entity)
    activity = {
        "type": "message",
        "id": "malformed",
        "text": "hello",
        "serviceUrl": "https://svc",
        "conversation": {"id": "c"},
        "from": {"id": "u"},
        "recipient": {"id": "bot", "name": "Bot"},
        field: value,
    }
    try:
        with (
            patch("agno.os.interfaces.msteams.router.typing_indicator_async", new_callable=AsyncMock),
            patch("agno.os.interfaces.msteams.router.send_teams_message_async", new_callable=AsyncMock) as send,
        ):
            assert client.post("/messages", json=activity).status_code == 200
        if field in ("conversation", "from"):
            entity.arun.assert_not_called()
            send.assert_not_called()
        else:
            entity.arun.assert_awaited_once()
            send.assert_awaited_once()
            assert send.call_args.args[2] == "final reply"
    finally:
        env.stop()


def test_failed_reference_save_still_replies_and_next_personal_message_repairs_it(tmp_path):
    from unittest.mock import AsyncMock

    from agno.run.agent import RunOutput

    db = SqliteDb(db_file=str(tmp_path / "repair.db"))
    scope = "msteams:agent:personal:user"
    saves = []

    async def arun(text, **kwargs):
        current = db.get_session(session_id=kwargs["session_id"], session_type=SessionType.AGENT)
        if current is None:
            db.upsert_session(
                AgentSession(
                    session_id=kwargs["session_id"], user_id="user", agent_id="agent", session_data={"keep": "value"}
                )
            )
        return RunOutput(run_id="run", session_id=kwargs["session_id"], content="reply")

    async def get_session(session_id):
        assert session_id == scope
        return db.get_session(session_id=session_id, session_type=SessionType.AGENT)

    async def save_session(session):
        saves.append(session.session_id)
        if len(saves) == 1:
            raise RuntimeError("storage unavailable")
        db.upsert_session(session)

    entity = SimpleNamespace(
        id="agent", name="Agent", db=db, arun=arun, aget_session=get_session, asave_session=save_session
    )
    client, env = _build_test_client(agent=entity)
    activity = {
        "type": "message",
        "id": "first",
        "text": "hello",
        "serviceUrl": "https://svc",
        "from": {"id": "user"},
        "recipient": {"id": "bot"},
        "conversation": {"id": "personal", "conversationType": "personal"},
    }
    try:
        with (
            patch("agno.os.interfaces.msteams.router.typing_indicator_async", new_callable=AsyncMock),
            patch("agno.os.interfaces.msteams.router.send_teams_message_async", new_callable=AsyncMock) as send,
        ):
            assert client.post("/messages", json=activity).status_code == 200
            stored = db.get_session(session_id=scope, session_type=SessionType.AGENT)
            assert stored.session_data == {"keep": "value"}
            assert send.call_args.args[2] == "reply"
            activity["id"] = "second"
            assert client.post("/messages", json=activity).status_code == 200
            stored = db.get_session(session_id=scope, session_type=SessionType.AGENT)
            assert stored.session_data["keep"] == "value"
            assert stored.session_data["msteams_conversation_ref"]["conversation_id"] == "personal"
            assert send.await_count == 2
            assert all(call.args[2] == "reply" for call in send.call_args_list)
        assert saves == [scope, scope]
    finally:
        env.stop()


def test_remote_entity_replies_without_local_session_features():
    import asyncio
    from unittest.mock import AsyncMock, PropertyMock

    from agno.agent import RemoteAgent
    from agno.os.interfaces.msteams import MSTeams
    from agno.remote.base import RemoteDb
    from agno.run.agent import RunOutput

    remote_db = RemoteDb(id="remote-db", client=MagicMock())
    entity = RemoteAgent(base_url="https://remote.example", agent_id="remote-agent")
    with (
        patch.object(RemoteAgent, "name", new_callable=PropertyMock, return_value="Remote"),
        patch.object(RemoteAgent, "db", new_callable=PropertyMock, return_value=remote_db),
        patch.object(
            entity, "arun", new_callable=AsyncMock, return_value=RunOutput(run_id="r", content="remote reply")
        ) as run,
    ):
        client, env = _build_test_client(agent=entity)
        activity = {
            "type": "message",
            "id": "normal",
            "text": "hello",
            "serviceUrl": "https://svc",
            "from": {"id": "u"},
            "conversation": {"id": "c", "conversationType": "personal"},
        }
        try:
            with (
                patch("agno.os.interfaces.msteams.router.typing_indicator_async", new_callable=AsyncMock),
                patch("agno.os.interfaces.msteams.router.send_teams_message_async", new_callable=AsyncMock) as send,
            ):
                assert client.post("/messages", json=activity).status_code == 200
                assert send.call_args.args[2] == "remote reply"
                activity.update(id="reset", text="/new")
                assert client.post("/messages", json=activity).status_code == 200
                assert send.call_args.args[2] == "Session reset requires storage to be configured."
                assert asyncio.run(MSTeams(agent=entity).asend_alert("u", "alert")) is False
            run.assert_awaited_once()
            assert run.call_args.kwargs["stream"] is False
            assert remote_db.client.mock_calls == []
        finally:
            env.stop()


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
        {"MICROSOFT_APP_ID": "app", "MICROSOFT_APP_PASSWORD": "pw", "MICROSOFT_APP_TENANT_ID": "tenant"},
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
    """A parsed activity cannot start background work without a valid token."""
    router = APIRouter()
    with patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app-id", "MICROSOFT_APP_PASSWORD": "secret", "MICROSOFT_APP_TENANT_ID": "tenant"},
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


# === Session selection ===


def test_two_same_second_resets_use_the_later_reset(tmp_path):
    from unittest.mock import AsyncMock

    from agno.run.agent import RunOutput

    db = SqliteDb(db_file=str(tmp_path / "reset_order.db"))
    agent = SimpleNamespace(
        id="agent-1", name="Agent", db=db, arun=AsyncMock(return_value=RunOutput(run_id="run", content="ok"))
    )
    client, env = _build_test_client(agent=agent)
    activity = {
        "type": "message",
        "serviceUrl": "https://svc",
        "from": {"id": "user-1"},
        "conversation": {"id": "channel;messageid=root", "conversationType": "channel"},
        "text": "/new",
    }
    scope = "msteams:agent-1:channel;messageid=root:user-1"
    try:
        with (
            patch("agno.os.interfaces.msteams.router.typing_indicator_async", new_callable=AsyncMock),
            patch("agno.os.interfaces.msteams.router.send_teams_message_async", new_callable=AsyncMock),
            patch("agno.os.interfaces.msteams.router.time", return_value=1_700_000_060),
            patch(
                "agno.os.interfaces.msteams.router.time_ns",
                create=True,
                side_effect=[1_700_000_060_000_000_000, 1_700_000_060_001_000_000],
            ),
            patch(
                "agno.os.interfaces.msteams.router.uuid4",
                side_effect=[SimpleNamespace(hex="f" * 32), SimpleNamespace(hex="0" * 32)],
            ),
        ):
            for activity_id in ["reset-first", "reset-second"]:
                activity["id"] = activity_id
                assert client.post("/messages", json=activity).status_code == 200
            agent.arun.assert_not_called()
            activity.update(id="after-resets", text="after both resets")
            assert client.post("/messages", json=activity).status_code == 200
        agent.arun.assert_awaited_once()
        assert agent.arun.call_args.kwargs["session_id"] == f"{scope}:17000000600010000"
        rows, total = db.get_sessions(session_type=SessionType.AGENT, deserialize=False)
        assert total == 2
        assert {row["session_id"] for row in rows} == {f"{scope}:1700000060000ffff", f"{scope}:17000000600010000"}
    finally:
        env.stop()


def test_new_session_survives_a_same_second_save_on_the_old_one(tmp_path):
    """`/new` races the run that was in flight when it was typed: that run's save
    stamps the old session with the same whole second the new one was created in."""
    db = SqliteDb(db_file=str(tmp_path / "teams_sessions.db"))
    old_id = "msteams:agent-1:conv-1:user-1"
    new_id = "msteams:agent-1:conv-1:user-1:0a1b2c3d"
    first_message, reset = 1_700_000_000, 1_700_000_060

    old = AgentSession(
        session_id=old_id,
        user_id="user-1",
        agent_id="agent-1",
        created_at=first_message,
        updated_at=first_message,
    )
    db.upsert_sessions([old], preserve_updated_at=True)
    db.upsert_sessions(
        [AgentSession(session_id=new_id, user_id="user-1", agent_id="agent-1", created_at=reset, updated_at=reset)],
        preserve_updated_at=True,
    )
    # The in-flight run lands its save on the old session in that same second.
    old.updated_at = reset
    db.upsert_sessions([old], preserve_updated_at=True)

    ran_on = {}

    async def fake_arun(text, **kwargs):
        ran_on["session_id"] = kwargs.get("session_id")
        return SimpleNamespace(
            status="COMPLETED", content="ok", session_id=kwargs.get("session_id"), reasoning_content=None
        )

    async def fake_aget_session(session_id=None):
        return None

    agent = SimpleNamespace(id="agent-1", name="Stub Agent", db=db, arun=fake_arun, aget_session=fake_aget_session)

    client, env_patch = _build_test_client(agent=agent)
    try:
        with (
            patch("agno.os.interfaces.msteams.router.typing_indicator_async"),
            patch("agno.os.interfaces.msteams.router.send_teams_message_async"),
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
                    "text": "next message",
                },
            )
        assert resp.status_code == 200
    finally:
        env_patch.stop()

    assert ran_on["session_id"] == new_id


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
    # Only OLD exists when the run starts; NEW is created while it is in flight.
    fake_db.get_sessions = MagicMock(return_value=([{"session_id": run_session.session_id, "created_at": 1}], 1))
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
            patch("agno.os.interfaces.msteams.router.typing_indicator_async"),
            patch("agno.os.interfaces.msteams.router.send_teams_message_async"),
        ):
            resp = client.post(
                "/messages",
                json={
                    "type": "message",
                    "id": "act-1",
                    "serviceUrl": "https://svc/",
                    "from": {"id": "29:u", "aadObjectId": "user-1"},
                    "conversation": {"id": "conv-1", "conversationType": "personal"},
                    "recipient": {"id": "28:bot"},
                    "text": "hello",
                    "channelId": "msteams",
                },
            )
        assert resp.status_code == 200
    finally:
        env_patch.stop()

    # Outcome first: the ref belongs on the run's session and nowhere else.
    # A latest-by-user re-read puts it on newer_session instead.
    assert run_session.session_data["msteams_conversation_ref"]["conversation_id"] == "conv-1"
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
        {"MICROSOFT_APP_ID": "app", "MICROSOFT_APP_PASSWORD": "pw", "MICROSOFT_APP_TENANT_ID": "tenant"},
        clear=True,
    ):
        attach_routes(router, agent=stub)

    operation_ids = {route.operation_id for route in router.routes if hasattr(route, "operation_id")}
    assert "msteams_status_weather_bot" in operation_ids
    assert "msteams_webhook_weather_bot" in operation_ids


def test_operation_ids_fall_back_to_entity_type_when_name_missing():
    stub = SimpleNamespace(id="agent-1", name=None, db=MagicMock(spec=BaseDb))
    router = APIRouter()
    with patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "app", "MICROSOFT_APP_PASSWORD": "pw", "MICROSOFT_APP_TENANT_ID": "tenant"},
        clear=True,
    ):
        attach_routes(router, agent=stub)

    operation_ids = {route.operation_id for route in router.routes if hasattr(route, "operation_id")}
    assert "msteams_status_agent" in operation_ids
    assert "msteams_webhook_agent" in operation_ids


@pytest.mark.parametrize(
    "mime,content,notice",
    [
        ("application/zip", b"zip", "archive.zip"),
        ("application/x-zip", b"zip", "archive.zip"),
        ("application/x-zip-compressed", b"zip", "archive.zip"),
        ("application/pdf", b"oversized", "archive.zip (too large)"),
    ],
)
def test_attachment_notice_keeps_text_and_interface_cap(mime, content, notice):
    from unittest.mock import AsyncMock

    import httpx

    from agno.os.interfaces.msteams import MSTeams
    from agno.run.agent import RunOutput

    entity = SimpleNamespace(
        id="agent", name="Agent", db=None, arun=AsyncMock(return_value=RunOutput(run_id="run", content="done"))
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=content, headers={"Content-Type": mime})
        )
    )
    with (
        patch.dict("os.environ", {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "true"}, clear=True),
        patch("httpx.AsyncClient", return_value=client),
        patch("agno.os.interfaces.msteams.router.typing_indicator_async", new_callable=AsyncMock),
        patch("agno.os.interfaces.msteams.router.send_teams_message_async", new_callable=AsyncMock),
    ):
        app = FastAPI()
        app.include_router(MSTeams(agent=entity, max_file_size=4).get_router())
        with TestClient(app) as webhook:
            response = webhook.post(
                "/msteams/messages",
                json={
                    "type": "message",
                    "text": "keep my text",
                    "serviceUrl": "https://svc",
                    "conversation": {"id": "c"},
                    "from": {"id": "u"},
                    "attachments": [{"name": "archive.zip", "contentUrl": "https://other/file"}],
                },
            )
    assert response.status_code == 200
    entity.arun.assert_awaited_once()
    assert entity.arun.call_args.args[0] == f"[Some attachments could not be read: {notice}]\n\nkeep my text"
    assert "files" not in entity.arun.call_args.kwargs


@pytest.mark.parametrize(
    "text,expected",
    [
        ("<at>Other</at> /new", "@Other /new"),
        ("Display /new", "Display /new"),
        ("<at>Bot</at> /new please", "Display /new please"),
    ],
)
def test_non_commands_keep_mentions_and_reach_agent(text, expected):
    from unittest.mock import AsyncMock

    from agno.run.agent import RunOutput

    entity = SimpleNamespace(
        id="agent", name="Agent", db=None, arun=AsyncMock(return_value=RunOutput(run_id="run", content="hello"))
    )
    client, env = _build_test_client(agent=entity)
    try:
        with (
            patch("agno.os.interfaces.msteams.router.typing_indicator_async", new_callable=AsyncMock),
            patch("agno.os.interfaces.msteams.router.send_teams_message_async", new_callable=AsyncMock),
        ):
            response = client.post(
                "/messages",
                json={
                    "type": "message",
                    "text": text,
                    "serviceUrl": "https://svc",
                    "from": {"id": "u"},
                    "conversation": {"id": "c", "conversationType": "groupChat"},
                    "recipient": {"id": "bot", "name": "Display"},
                    "entities": [
                        {"type": "mention", "text": "<at>Bot</at>", "mentioned": {"id": "bot"}},
                        {"type": "mention", "text": "<at>Other</at>", "mentioned": {"id": "other"}},
                    ],
                },
            )
        assert response.status_code == 200
        entity.arun.assert_awaited_once()
        assert entity.arun.call_args.args[0] == expected
    finally:
        env.stop()


def test_mention_only_reaches_agent():
    from unittest.mock import AsyncMock

    from agno.run.agent import RunOutput

    entity = SimpleNamespace(
        id="agent", name="Agent", db=None, arun=AsyncMock(return_value=RunOutput(run_id="run", content="hello"))
    )
    client, env = _build_test_client(agent=entity)
    try:
        with (
            patch("agno.os.interfaces.msteams.router.typing_indicator_async", new_callable=AsyncMock),
            patch("agno.os.interfaces.msteams.router.send_teams_message_async", new_callable=AsyncMock),
        ):
            assert (
                client.post(
                    "/messages",
                    json={
                        "type": "message",
                        "text": "<at>Bot</at>",
                        "serviceUrl": "https://svc",
                        "from": {"id": "u"},
                        "conversation": {"id": "c"},
                        "recipient": {"id": "bot", "name": "Display"},
                        "entities": [{"type": "mention", "text": "<at>Bot</at>", "mentioned": {"id": "bot"}}],
                    },
                ).status_code
                == 200
            )
        assert entity.arun.call_args.args[0] == "Display"
    finally:
        env.stop()


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
def test_paused_run_sends_only_approval_notice(kind, caplog):
    from unittest.mock import AsyncMock

    from agno.run.agent import RunOutput
    from agno.run.base import RunStatus
    from agno.run.team import TeamRunOutput
    from agno.run.workflow import WorkflowRunOutput

    output_cls = {"agent": RunOutput, "team": TeamRunOutput, "workflow": WorkflowRunOutput}[kind]
    response = output_cls(run_id="paused-run", status=RunStatus.paused, content="partial content")
    entity = SimpleNamespace(id="entity-1", name="Stub", db=None, arun=AsyncMock(return_value=response))
    client, env_patch = _build_test_client(**{kind: entity})
    try:
        with (
            patch("agno.os.interfaces.msteams.router.typing_indicator_async", new_callable=AsyncMock),
            patch("agno.os.interfaces.msteams.router.send_teams_message_async", new_callable=AsyncMock) as send,
        ):
            assert (
                client.post(
                    "/messages",
                    json={
                        "type": "message",
                        "text": "hello",
                        "serviceUrl": "https://svc/",
                        "from": {"id": "user"},
                        "conversation": {"id": "personal", "conversationType": "personal"},
                    },
                ).status_code
                == 200
            )
        assert send.await_count == 1
        assert (
            send.call_args.args[2]
            == "This request needs an approval step, which isn't available in Microsoft Teams yet."
        )
        assert "paused-run" in caplog.text
        assert "partial content" not in str(send.call_args_list)
    finally:
        env_patch.stop()


@pytest.mark.parametrize("kind", ["personal", "groupChat", "channel"])
@pytest.mark.parametrize("reset_text", ["/new", "<at>Bot</at> /new", "  <at>Bot</at> \n /NeW  "])
def test_conversation_scoped_reset_and_reference(tmp_path, kind, reset_text):
    from unittest.mock import AsyncMock

    db = SqliteDb(db_file=str(tmp_path / "scope.db"))
    seen = []
    seen_text = []

    async def arun(text, **kwargs):
        sid = kwargs["session_id"]
        seen.append(sid)
        seen_text.append(text)
        existing = db.get_session(session_id=sid, session_type=SessionType.AGENT)
        if existing is None:
            db.upsert_session(AgentSession(session_id=sid, agent_id="agent-1", user_id="user-1"))
        return SimpleNamespace(status="COMPLETED", content="ok", session_id=sid, reasoning_content=None)

    async def get_session(session_id):
        return db.get_session(session_id=session_id, session_type=SessionType.AGENT)

    async def save_session(session):
        db.upsert_session(session)

    agent = SimpleNamespace(
        id="agent-1", name="Stub", db=db, arun=arun, aget_session=get_session, asave_session=save_session
    )
    client, env_patch = _build_test_client(agent=agent)
    activity = {
        "type": "message",
        "id": "act",
        "serviceUrl": "https://svc/",
        "from": {"id": "user-1"},
        "recipient": {"id": "bot", "name": "Display"},
        "entities": [
            {"type": "mention", "text": "<at>Bot</at>", "mentioned": {"id": "bot"}},
            {"type": "mention", "text": "<at>Other</at>", "mentioned": {"id": "other"}},
        ],
        "text": "<at>Bot</at> hello <at>Other</at>",
    }
    own_conv = "thread;messageid=root" if kind == "channel" else kind
    try:
        with (
            patch("agno.os.interfaces.msteams.router.typing_indicator_async", new_callable=AsyncMock),
            patch("agno.os.interfaces.msteams.router.send_teams_message_async", new_callable=AsyncMock),
        ):
            for index, (conv, conv_type) in enumerate([(own_conv, kind), ("other", "groupChat"), (own_conv, kind)]):
                activity["id"] = f"message-{index}"
                activity["conversation"] = {"id": conv, "conversationType": conv_type}
                assert client.post("/messages", json=activity).status_code == 200
            own_scope = f"msteams:agent-1:{own_conv}:user-1"
            assert seen == [own_scope, "msteams:agent-1:other:user-1", own_scope]
            assert seen_text == ["Display hello @Other"] * 3
            activity["id"] = "reset"
            activity["text"] = reset_text
            assert client.post("/messages", json=activity).status_code == 200
            assert len(seen) == 3, "A reset command must not invoke the entity"
            activity["id"] = "after-reset"
            activity["text"] = "after reset"
            assert client.post("/messages", json=activity).status_code == 200
            assert seen[-1].startswith(own_scope + ":")
            assert len(seen[-1].removeprefix(own_scope + ":")) == 17
            activity["id"] = "other-conversation"
            activity["conversation"] = {"id": "other", "conversationType": "groupChat"}
            assert client.post("/messages", json=activity).status_code == 200
            assert seen[-1] == "msteams:agent-1:other:user-1"
        session = db.get_session(session_id=own_scope, session_type=SessionType.AGENT)
        assert ("msteams_conversation_ref" in (session.session_data or {})) == (kind == "personal")
    finally:
        env_patch.stop()
