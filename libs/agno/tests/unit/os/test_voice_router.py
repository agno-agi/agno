"""Voice sockets must enforce the same credentials and agent permissions as REST."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import jwt
import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.middleware.jwt import JWTMiddleware
from agno.os.settings import AgnoAPISettings

SECRET = "voice-test-secret-at-least-thirty-two-characters"


class StubPipe:
    def __init__(self, agent, id="test-voice"):
        self.id = id
        self.agent = agent
        self.calls = []

    async def _serve(self, websocket, *, user_id=None, session_id=None):
        self.calls.append((user_id, session_id))
        await websocket.send_json({"event": "served", "user_id": user_id, "session_id": session_id})


@pytest.fixture(autouse=True)
def clear_auth_environment(monkeypatch):
    for variable in ("JWT_VERIFICATION_KEY", "JWT_JWKS_FILE", "OS_SECURITY_KEY"):
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def pipe():
    return StubPipe(Agent(id="voice-agent", name="Voice Agent", telemetry=False))


def make_os(pipe, **kwargs):
    return AgentOS(live_sockets=[pipe], telemetry=False, **kwargs)


def token(scopes, subject="alice", **claims):
    return jwt.encode(
        {"sub": subject, "scopes": scopes, "exp": datetime.now(timezone.utc) + timedelta(minutes=5), **claims},
        SECRET,
        algorithm="HS256",
    )


def jwt_os(pipe, **config):
    return make_os(
        pipe,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256", **config),
    )


def test_live_socket_registers_its_existing_agent(pipe):
    os = make_os(pipe)
    assert os.agents == [pipe.agent]
    assert os.agents[0] is pipe.agent
    explicitly_listed = [pipe.agent]
    os = make_os(pipe, agents=explicitly_listed)
    assert len(os.agents) == 1
    assert explicitly_listed == [pipe.agent]


def test_duplicate_pipe_ids_fail_before_serving(pipe):
    with pytest.raises(ValueError, match="Duplicate voice pipe ID"):
        AgentOS(live_sockets=[pipe, StubPipe(pipe.agent)], telemetry=False)


@pytest.mark.parametrize("policy", ["preserve_base_app", "preserve_agentos", "error"])
def test_existing_socket_cannot_shadow_authenticated_voice_socket(pipe, policy):
    app = FastAPI()

    @app.websocket("/voice/{name}/pipe")
    async def unprotected_socket(websocket: WebSocket, name: str):
        await websocket.accept()

    with pytest.raises(ValueError, match="Voice route conflicts"):
        make_os(pipe, base_app=app, on_route_conflict=policy).get_app()


@pytest.mark.parametrize("id", ["../other", "voice/one", "", "voice\n", "x" * 65])
def test_invalid_pipe_id_fails_before_serving(pipe, id):
    pipe.id = id
    with pytest.raises(ValueError, match="URL-safe"):
        make_os(pipe)


def test_open_socket_has_fresh_server_sessions_and_ignores_claimed_identity(pipe):
    client = TestClient(make_os(pipe).get_app())
    sessions = []
    for _ in range(2):
        with client.websocket_connect("/voice/test-voice/pipe?user_id=mallory&session_id=stolen") as ws:
            event = ws.receive_json()
            assert event["event"] == "served"
            assert event["user_id"] is None
            UUID(event["session_id"])
            sessions.append(event["session_id"])
    assert len(set(sessions)) == 2


def test_unknown_pipe_is_rejected(pipe):
    with pytest.raises(WebSocketDisconnect):
        with TestClient(make_os(pipe).get_app()).websocket_connect("/voice/missing/pipe"):
            pass
    assert not pipe.calls


@pytest.mark.parametrize("origin", [None, "http://testserver", "https://testserver"])
def test_same_origin_and_non_browser_clients_can_connect(pipe, origin):
    headers = {"Origin": origin} if origin else {}
    with TestClient(make_os(pipe).get_app()).websocket_connect("/voice/test-voice/pipe", headers=headers) as ws:
        assert ws.receive_json()["event"] == "served"


@pytest.mark.parametrize("origin", ["https://untrusted.example", "null", "http://testserver@untrusted.example"])
def test_cross_site_socket_rejected_before_accept_and_provider_connection(pipe, origin):
    with pytest.raises(WebSocketDisconnect) as error:
        with TestClient(make_os(pipe).get_app()).websocket_connect(
            "/voice/test-voice/pipe", headers={"Origin": origin}
        ):
            pytest.fail("An untrusted origin was accepted")
    assert error.value.code == 1008
    assert not pipe.calls


def test_explicit_cors_origin_can_connect(pipe):
    app = make_os(pipe, cors_allowed_origins=["https://voice.example"]).get_app()
    with TestClient(app).websocket_connect("/voice/test-voice/pipe", headers={"Origin": "https://voice.example"}) as ws:
        assert ws.receive_json()["event"] == "served"


def test_wildcard_cors_does_not_allow_arbitrary_voice_origins(pipe):
    app = make_os(pipe, cors_allowed_origins=["*"]).get_app()
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect(
            "/voice/test-voice/pipe", headers={"Origin": "https://untrusted.example"}
        ):
            pytest.fail("Wildcard CORS allowed an untrusted voice origin")
    assert not pipe.calls


def test_security_key_authenticates_before_opening_pipe(pipe):
    client = TestClient(make_os(pipe, settings=AgnoAPISettings(os_security_key=SECRET)).get_app())
    with client.websocket_connect("/voice/test-voice/pipe") as ws:
        assert ws.receive_json()["event"] == "auth_required"
        assert not pipe.calls
        ws.send_json({"action": "authenticate", "token": SECRET, "user_id": "mallory", "session_id": "stolen"})
        assert ws.receive_json()["event"] == "authenticated"
        result = ws.receive_json()
        assert result["user_id"] is None
        assert result["session_id"] != "stolen"


def test_live_socket_only_adds_its_canonical_pipe_route(pipe):
    client = TestClient(make_os(pipe).get_app())
    assert client.get("/voice/test-voice").status_code == 404
    assert client.get("/voice/static/voice-client.js").status_code == 404
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/voice/test-voice/ws"):
            pass
    with client.websocket_connect("/voice/test-voice/pipe") as ws:
        assert ws.receive_json()["event"] == "served"


def test_pipe_id_static_is_allowed(pipe):
    pipe.id = "static"
    app = make_os(pipe).get_app()
    with TestClient(app).websocket_connect("/voice/static/pipe") as ws:
        assert ws.receive_json()["event"] == "served"


@pytest.mark.parametrize("message", [{"action": "authenticate", "token": "wrong"}, [], {"type": "start"}])
def test_bad_credentials_never_open_pipe(pipe, message):
    client = TestClient(make_os(pipe, settings=AgnoAPISettings(os_security_key=SECRET)).get_app())
    with client.websocket_connect("/voice/test-voice/pipe") as ws:
        assert ws.receive_json()["event"] == "auth_required"
        ws.send_json(message)
        assert ws.receive_json()["event"] == "auth_error"
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 1008
    assert not pipe.calls


def test_binary_audio_before_authentication_is_rejected(pipe):
    client = TestClient(make_os(pipe, settings=AgnoAPISettings(os_security_key=SECRET)).get_app())
    with client.websocket_connect("/voice/test-voice/pipe") as ws:
        ws.receive_json()
        ws.send_bytes(b"\x00\x00" * 320)
        assert ws.receive_json()["event"] == "auth_error"
    assert not pipe.calls


def test_jwt_resource_scope_and_subject_are_enforced(pipe):
    client = TestClient(jwt_os(pipe, user_isolation=True).get_app())
    with client.websocket_connect("/voice/test-voice/pipe?user_id=mallory") as ws:
        ws.receive_json()
        ws.send_json({"action": "authenticate", "token": token(["agents:voice-agent:run"]), "user_id": "mallory"})
        assert ws.receive_json() == {"event": "authenticated", "user_id": "alice"}
        assert ws.receive_json()["user_id"] == "alice"
    assert pipe.calls[0][0] == "alice"


@pytest.mark.parametrize("scopes", [["agents:read"], ["agents:other-agent:run"], []])
def test_jwt_wrong_scopes_cannot_start_voice(pipe, scopes):
    client = TestClient(jwt_os(pipe).get_app())
    with client.websocket_connect("/voice/test-voice/pipe") as ws:
        ws.receive_json()
        ws.send_json({"action": "authenticate", "token": token(scopes)})
        assert ws.receive_json()["event"] == "auth_error"
    assert not pipe.calls


def test_jwt_wrong_audience_is_rejected(pipe):
    client = TestClient(jwt_os(pipe, verify_audience=True, audience="voice-os").get_app())
    with client.websocket_connect("/voice/test-voice/pipe") as ws:
        ws.receive_json()
        ws.send_json({"action": "authenticate", "token": token(["agents:run"], aud="other-os")})
        assert ws.receive_json()["event"] == "auth_error"
    assert not pipe.calls


def test_jwt_cannot_spoof_service_account_principal(pipe):
    client = TestClient(jwt_os(pipe).get_app())
    with client.websocket_connect("/voice/test-voice/pipe") as ws:
        ws.receive_json()
        ws.send_json({"action": "authenticate", "token": token(["agents:run"], subject="sa:bot")})
        assert ws.receive_json()["event"] == "auth_error"
    assert not pipe.calls


def test_manual_jwt_middleware_protects_first_socket(pipe):
    app = make_os(pipe).get_app()
    app.add_middleware(JWTMiddleware, verification_keys=[SECRET], algorithm="HS256")
    with TestClient(app).websocket_connect("/voice/test-voice/pipe") as ws:
        assert ws.receive_json()["event"] == "auth_required"
        ws.send_json({"action": "authenticate", "token": token(["agents:run"])})
        assert ws.receive_json()["event"] == "authenticated"
        assert ws.receive_json()["user_id"] == "alice"


@pytest.mark.parametrize("scopes, allowed", [(["agents:run"], True), (["agents:read"], False)])
def test_service_account_scopes_apply_even_without_jwt(pipe, scopes, allowed):
    app = make_os(pipe).get_app()
    app.state.service_account_verifier = SimpleNamespace(
        verify=AsyncMock(
            return_value=SimpleNamespace(ok=True, account=SimpleNamespace(principal="sa:bot", scopes=scopes))
        )
    )
    with TestClient(app).websocket_connect(
        "/voice/test-voice/pipe", headers={"Authorization": "Bearer agno_pat_test"}
    ) as ws:
        first = ws.receive_json()
        assert first["event"] == ("authenticated" if allowed else "auth_error")
        if allowed:
            assert ws.receive_json()["user_id"] == "sa:bot"
    assert bool(pipe.calls) is allowed


def test_voice_listing_describes_each_pipe_and_appears_in_docs(pipe):
    client = TestClient(make_os(pipe).get_app())
    response = client.get("/voice")
    assert response.status_code == 200
    assert response.json() == [
        {"id": "test-voice", "agent_id": "voice-agent", "agent_name": "Voice Agent", "path": "/voice/test-voice/pipe"}
    ]
    assert "/voice" in client.get("/openapi.json").json()["paths"]


def test_voice_listing_requires_the_security_key(pipe):
    client = TestClient(make_os(pipe, settings=AgnoAPISettings(os_security_key=SECRET)).get_app())
    assert client.get("/voice").status_code == 401
    response = client.get("/voice", headers={"Authorization": f"Bearer {SECRET}"})
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["test-voice"]


def test_voice_listing_only_shows_pipes_for_readable_agents():
    other = StubPipe(Agent(id="other-agent", name="Other", telemetry=False), id="other-voice")
    mine = StubPipe(Agent(id="voice-agent", name="Voice Agent", telemetry=False))
    os = AgentOS(
        live_sockets=[mine, other],
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256"),
    )
    client = TestClient(os.get_app())
    assert client.get("/voice").status_code == 401
    scoped = client.get("/voice", headers={"Authorization": f"Bearer {token(['agents:voice-agent:read'])}"})
    assert scoped.status_code == 200
    assert [item["id"] for item in scoped.json()] == ["test-voice"]
    assert client.get("/voice", headers={"Authorization": f"Bearer {token(['teams:read'])}"}).status_code == 403
