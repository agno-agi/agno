"""One runtime serving anonymous clients and the JWT-authenticated Control Plane."""

import time
from contextlib import ExitStack
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, MCPConfig
from agno.os.config import AuthorizationConfig
from agno.os.middleware.jwt import AuthMiddleware
from agno.os.public import PublicSurface
from agno.os.public._limits import Admission

KEY = "public-control-plane-test-signing-key"
ORIGIN = "https://os.agno.com"


class AnswerModel(Model):
    def __init__(self):
        super().__init__(id="test-answer", name="test-answer", provider="test")

    def invoke(self, *args, **kwargs):
        return ModelResponse(role="assistant", content="Hello", response_usage=MessageMetrics())

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


class AdmissionRecorder:
    ready = True

    def __init__(self):
        self.calls = []
        self.client_ids = []
        self.allowed = True

    async def aconsume(self, bucket, *, client_id):
        self.calls.append(bucket)
        self.client_ids.append(client_id)
        return Admission(self.allowed, retry_after=60)

    async def _aprepare(self):
        pass


def token(scopes=None, *, key=KEY, audience="mixed-os", expires=300):
    return jwt.encode(
        {
            "sub": "operator",
            "scopes": scopes if scopes is not None else ["agent_os:admin"],
            "aud": audience,
            "exp": int(time.time()) + expires,
        },
        key,
        algorithm="HS256",
    )


def auth(value=None):
    return {"Authorization": "Bearer " + (value if value is not None else token())}


def echo(message: str) -> str:
    return message


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    for name in ("JWT_VERIFICATION_KEY", "JWT_JWKS_FILE", "OS_SECURITY_KEY"):
        monkeypatch.delenv(name, raising=False)
    # Code-defined component discovery needs no PostgreSQL connection. Session
    # requests below use a real SQLite store; quota calls are recorded separately.
    monkeypatch.setattr("agno.agent.agent.get_agents", lambda **kwargs: [])
    db = SqliteDb(id="sessions", db_file=str(tmp_path / "sessions.db"))
    agent = Agent(id="docs", name="Docs", db=db, model=AnswerModel(), telemetry=False)
    hidden = Agent(id="private", db=db, model=AnswerModel(), telemetry=False)
    surface = PublicSurface(agents=[agent], mcp=True)
    limiter = AdmissionRecorder()
    surface._limiter = limiter
    os = AgentOS(
        id="mixed-os",
        agents=[agent, hidden],
        db=PostgresDb(db_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused"),
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[KEY], algorithm="HS256", verify_audience=True, user_isolation=True
        ),
        public=surface,
        mcp=MCPConfig(tools=[echo], default_tools=False, lifecycle_tools=False, stateless=True),
        internal_service_token="scheduler-secret",
        telemetry=False,
        auto_provision_dbs=False,
        cors_allowed_origins=[ORIGIN],
    )
    return SimpleNamespace(os=os, surface=surface, limiter=limiter, db=db)


def test_public_chat_and_authenticated_control_plane_share_one_app(runtime):
    client = TestClient(runtime.os.get_app())
    public = client.get("/agents")
    assert public.json() == [{"id": "docs", "name": "Docs", "description": ""}]
    assert "Authorization" in public.headers["vary"]
    assert client.get("/info").json()["auth_mode"] == "jwt"
    assert client.get("/config").status_code == 401
    assert client.get("/agents/private").status_code == 401

    run = client.post("/agents/docs/runs", data={"message": "hi", "stream": "false"})
    assert run.status_code == 200, run.text
    assert run.json()["content"] == "Hello"
    assert runtime.limiter.calls == ["run"]

    config = client.get("/config", headers=auth())
    assert config.status_code == 200, config.text
    assert config.json()["os_id"] == "mixed-os"
    assert config.headers["cache-control"] == "private, no-store"
    agents = client.get("/agents", headers=auth())
    assert {item["id"] for item in agents.json()} == {"docs", "private"}
    assert "model" in agents.json()[0]
    assert client.get("/agents/private", headers=auth()).status_code == 200
    assert client.get("/openapi.json").status_code == 401
    assert client.get("/openapi.json", headers=auth()).status_code == 200
    assert client.head("/health", headers=auth()).status_code == 200
    sessions = client.get("/sessions", params={"db_id": "sessions"}, headers=auth())
    assert sessions.status_code == 200, sessions.text
    assert run.json()["session_id"] in sessions.text
    assert runtime.limiter.calls == ["run"]


def test_scoped_jwt_uses_existing_permissions_and_native_run_schema(runtime):
    client = TestClient(runtime.os.get_app())
    headers = auth(token(["agents:docs:read", "agents:docs:run"]))
    assert client.get("/config", headers=headers).status_code == 403
    assert client.get("/sessions", headers=headers).status_code == 403
    assert client.get("/agents/private", headers=headers).status_code == 403
    assert [item["id"] for item in client.get("/agents", headers=headers).json()] == ["docs"]
    fields = {"message": "hi", "stream": "false", "user_id": "cannot-impersonate"}
    assert client.post("/agents/docs/runs", data=fields).status_code == 400
    result = client.post("/agents/docs/runs", data=fields, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["user_id"] == "operator"
    assert runtime.limiter.calls == ["run"]
    assert client.post("/agents/private/runs", data=fields, headers=headers).status_code == 403


@pytest.mark.parametrize(
    "credential",
    ["", "garbage", token(key="wrong-signing-key-at-least-32-bytes"), token(audience="another-os"), token(expires=-60)],
)
@pytest.mark.parametrize("path", ["/config", "/agents", "/info", "/agents/docs/runs", "/mcp"])
def test_bad_credentials_never_fall_back_to_public(runtime, credential, path):
    client = TestClient(runtime.os.get_app())
    response = client.request(
        "POST" if path.endswith("runs") or path == "/mcp" else "GET", path, headers=auth(credential)
    )
    assert response.status_code == 401
    assert runtime.limiter.calls == []


def test_duplicate_bearers_and_insufficient_scopes_fail_before_admission(runtime):
    client = TestClient(runtime.os.get_app())
    headers = [("Authorization", "Bearer " + token()), ("Authorization", "Bearer invalid")]
    assert client.get("/config", headers=headers).status_code == 401
    response = client.post("/agents/docs/runs", data={"message": "hi"}, headers=auth(token(["config:read"])))
    assert response.status_code == 403
    assert not runtime.limiter.calls


def test_public_limits_remain_independent_of_authenticated_rest(runtime):
    runtime.limiter.allowed = False
    client = TestClient(runtime.os.get_app())
    response = client.post("/agents/docs/runs", data={"message": "hi"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert client.get("/config", headers=auth()).status_code == 200
    # Even a verified admin JWT cannot bypass public MCP admission.
    for headers in ({}, auth()):
        assert (
            client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=headers).status_code
            == 429
        )
    assert runtime.limiter.calls == ["run", "mcp", "mcp"]


def test_scheduler_keeps_its_narrow_access(runtime):
    client = TestClient(runtime.os.get_app())
    headers = auth("scheduler-secret")
    assert client.get("/config", headers=headers).status_code == 403
    result = client.post(
        "/agents/private/runs", headers=headers, data={"message": "hi", "stream": "false", "user_id": "owner"}
    )
    assert result.status_code == 200, result.text
    assert not runtime.limiter.calls


def test_scoped_workflow_service_account_keeps_public_input_and_quota_rules(runtime):
    from uuid import uuid4

    from pydantic import BaseModel

    from agno.db.schemas.service_accounts import ServiceAccount
    from agno.os.service_accounts import ServiceAccountVerifier, generate_token
    from agno.workflow import Step, StepInput, StepOutput, Workflow

    class SyncInput(BaseModel):
        reason: str

    def sync(step_input: StepInput) -> StepOutput:
        return StepOutput(content="synchronized")

    workflow = Workflow(id="sync", input_schema=SyncInput, db=runtime.db, steps=[Step(name="sync", executor=sync)])
    runtime.os.workflows = [workflow]
    runtime.surface.workflows = [workflow]
    runtime.os._service_account_verifier = ServiceAccountVerifier(runtime.db)
    plaintext, digest, prefix = generate_token()
    runtime.db.create_service_account(
        ServiceAccount(
            id=str(uuid4()),
            name="sync-hook",
            token_hash=digest,
            token_prefix=prefix,
            scopes=["workflows:sync:run", "workflows:sync:read"],
            created_at=int(time.time()),
        ).to_dict()
    )
    client = TestClient(runtime.os.get_app())
    route = "/workflows/sync/runs"
    fields = {"message": '{"reason":"test"}', "stream": "false"}
    assert client.post(route, data=fields).status_code == 401
    assert client.post(route, data={**fields, "user_id": "owner"}, headers=auth(plaintext)).status_code == 400
    response = client.post(route, data=fields, headers=auth(plaintext))
    assert response.status_code == 200, response.text
    run = response.json()
    response = client.get(
        route + "/" + run["run_id"], params={"session_id": run["session_id"]}, headers=auth(plaintext)
    )
    assert response.status_code == 200, response.text
    assert client.get("/config", headers=auth(plaintext)).status_code == 403
    assert runtime.limiter.calls == ["run", "run"]


@pytest.mark.parametrize("scopes", [["agent_os:admin"], ["config:read"]])
def test_workflow_socket_requires_authentication_even_before_first_http_request(runtime, scopes):
    client = TestClient(runtime.os.get_app())
    with client.websocket_connect("/workflows/ws") as socket:
        assert socket.receive_json()["event"] == "connected"
        socket.send_json({"action": "ping"})
        assert socket.receive_json()["event"] == "auth_required"
        socket.send_json({"action": "authenticate", "token": "invalid"})
        assert socket.receive_json()["event"] == "auth_error"
        socket.send_json({"action": "authenticate", "token": token(scopes)})
        assert socket.receive_json()["event"] == "authenticated"
        assert socket.receive_json()["event"] == "authenticated"
        socket.send_json({"action": "ping"})
        assert socket.receive_json()["event"] == "pong"
        if scopes == ["config:read"]:
            socket.send_json({"action": "start-workflow", "workflow_id": "private-workflow"})
            assert socket.receive_json() == {"event": "error", "error": "Insufficient permissions to run this workflow"}


def test_mounted_runtime_keeps_route_permissions_and_public_selection(runtime):
    parent = FastAPI()
    parent.mount("/runtime", runtime.os.get_app())
    client = TestClient(parent)
    assert client.get("/runtime/agents").status_code == 200
    assert client.get("/runtime/config", headers=auth()).status_code == 200
    assert client.get("/runtime/config", headers=auth(token(["agents:read"]))).status_code == 403
    assert client.post("/runtime/agents/private/runs", data={"message": "hi"}).status_code == 401
    with client.websocket_connect("/runtime/workflows/ws") as socket:
        assert socket.receive_json()["event"] == "connected"
        socket.send_json({"action": "ping"})
        assert socket.receive_json()["event"] == "auth_required"


@pytest.mark.parametrize("mounted", [False, True])
@pytest.mark.parametrize("credential_kind", ["jwt", "pat"])
@pytest.mark.parametrize("path", ["/config", "/sessions", "/metrics", "/schedules"])
def test_native_management_scopes_are_enforced_with_and_without_mounts(runtime, mounted, credential_kind, path):
    from uuid import uuid4

    from agno.db.schemas.service_accounts import ServiceAccount
    from agno.os.service_accounts import ServiceAccountVerifier, generate_token

    runtime.os.public = None
    runtime.os.db = runtime.db
    runtime.os._service_account_verifier = ServiceAccountVerifier(runtime.db)

    def credential(scopes):
        if credential_kind == "jwt":
            return token(scopes)
        plaintext, digest, prefix = generate_token()
        runtime.db.create_service_account(
            ServiceAccount(
                id=str(uuid4()),
                name="test-" + uuid4().hex,
                token_hash=digest,
                token_prefix=prefix,
                scopes=scopes,
                created_at=int(time.time()),
            ).to_dict()
        )
        return plaintext

    app = runtime.os.get_app()
    if mounted:
        parent = FastAPI()
        parent.mount("/runtime", app)
        app = parent
    client = TestClient(app)
    url = ("/runtime" if mounted else "") + path
    params = {"db_id": "sessions"} if path in ("/sessions", "/metrics") else {}
    assert client.get(url, params=params).status_code == 401
    denied = client.get(url, params=params, headers=auth(credential([])))
    assert denied.status_code == 403, denied.text
    allowed = client.get(url, params=params, headers=auth(credential(["agent_os:admin"])))
    assert allowed.status_code == 200, allowed.text


@pytest.mark.parametrize("mounted", [False, True])
def test_public_info_counts_only_selected_components_and_preserves_discovery_schema(runtime, mounted):
    from agno.team import Team
    from agno.workflow import Workflow

    public_team = Team(id="public-team", members=[runtime.os.agents[0]], model=AnswerModel(), telemetry=False)
    private_team = Team(id="private-team", members=[runtime.os.agents[1]], model=AnswerModel(), telemetry=False)
    public_workflow = Workflow(id="public-workflow", steps=[], telemetry=False)
    private_workflow = Workflow(id="private-workflow", steps=[], telemetry=False)
    runtime.os.teams = [public_team, private_team]
    runtime.os.workflows = [public_workflow, private_workflow]
    runtime.surface.teams = [public_team]
    runtime.surface.workflows = [public_workflow]
    app = runtime.os.get_app()
    path = "/info"
    if mounted:
        parent = FastAPI()
        parent.mount("/runtime", app)
        app = parent
        path = "/runtime/info"
    client = TestClient(app)
    anonymous = client.get(path)
    authenticated = client.get(path, headers=auth())
    assert anonymous.status_code == authenticated.status_code == 200
    public_info = anonymous.json()
    native_info = authenticated.json()
    assert public_info.keys() == native_info.keys()
    for kind in ("agent", "team", "workflow"):
        assert public_info[kind + "_count"] == 1
        assert native_info[kind + "_count"] == 2
    for field in ("os_id", "name", "os_version", "agno_version", "auth_mode", "mcp"):
        assert public_info[field] == native_info[field]
    assert public_info["auth_mode"] == "jwt"
    assert "Authorization" in anonymous.headers["vary"]
    assert authenticated.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("unavailable", [False, True])
def test_public_socket_admission_rejects_before_accept(runtime, unavailable):
    runtime.surface.client_id = lambda request: request.headers["x-real-ip"]
    runtime.limiter.allowed = False
    if unavailable:

        async def fail(*args, **kwargs):
            raise RuntimeError("quota store unavailable")

        runtime.limiter.aconsume = fail
    with pytest.raises(WebSocketDisconnect) as closed:
        with TestClient(runtime.os.get_app()).websocket_connect("/workflows/ws", headers={"x-real-ip": "8.8.8.8"}):
            pytest.fail("Rejected upgrade must not be accepted")
    assert closed.value.code == 1008
    if not unavailable:
        assert runtime.limiter.calls == ["socket"]
        assert runtime.limiter.client_ids == ["8.8.8.8"]


def test_public_socket_pending_capacity_releases_on_authentication_and_disconnect(runtime, monkeypatch):
    monkeypatch.setattr("agno.os.public._middleware.MAX_PENDING_WEBSOCKETS", 2)
    client = TestClient(runtime.os.get_app())
    with ExitStack() as stack:
        first = stack.enter_context(client.websocket_connect("/workflows/ws"))
        second = stack.enter_context(client.websocket_connect("/workflows/ws"))
        assert first.receive_json()["event"] == second.receive_json()["event"] == "connected"
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/workflows/ws"):
                pytest.fail("Pending capacity must be enforced")
        assert closed.value.code == 1008
        assert runtime.limiter.calls == ["socket", "socket"]
        first.send_json({"action": "authenticate", "token": token()})
        assert first.receive_json()["event"] == "authenticated"
        assert first.receive_json()["event"] == "authenticated"
        first.send_json({"action": "ping"})
        assert first.receive_json()["event"] == "pong"
        with client.websocket_connect("/workflows/ws") as third:
            assert third.receive_json()["event"] == "connected"
        with client.websocket_connect("/workflows/ws") as fourth:
            assert fourth.receive_json()["event"] == "connected"
        assert runtime.limiter.calls == ["socket"] * 4


@pytest.mark.parametrize("keep_alive", [False, True])
def test_public_socket_authentication_deadline_cannot_be_extended(runtime, monkeypatch, keep_alive):
    monkeypatch.setattr("agno.os.router.PUBLIC_WS_AUTH_TIMEOUT", 0.2)
    client = TestClient(runtime.os.get_app())
    with client.websocket_connect("/workflows/ws") as socket:
        assert socket.receive_json()["event"] == "connected"
        started = time.monotonic()
        with pytest.raises(WebSocketDisconnect) as closed:
            if keep_alive:
                while time.monotonic() - started < 2:
                    socket.send_json({"action": "ping"})
                    assert socket.receive_json()["event"] == "auth_required"
                    time.sleep(0.03)
                pytest.fail("Messages must not extend the authentication deadline")
            else:
                socket.receive_json()
        assert closed.value.code == 1008


def test_public_socket_closes_after_five_failed_authentication_attempts(runtime):
    with TestClient(runtime.os.get_app()).websocket_connect("/workflows/ws") as socket:
        assert socket.receive_json()["event"] == "connected"
        for _ in range(5):
            socket.send_json({"action": "authenticate", "token": "invalid"})
            assert socket.receive_json()["event"] == "auth_error"
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == 1008


def test_public_socket_authentication_deadline_ends_after_verification(runtime, monkeypatch):
    monkeypatch.setattr("agno.os.router.PUBLIC_WS_AUTH_TIMEOUT", 0.2)
    with TestClient(runtime.os.get_app()).websocket_connect("/workflows/ws") as socket:
        assert socket.receive_json()["event"] == "connected"
        socket.send_json({"action": "authenticate", "token": token()})
        assert socket.receive_json()["event"] == "authenticated"
        assert socket.receive_json()["event"] == "authenticated"
        time.sleep(0.3)
        socket.send_json({"action": "ping"})
        assert socket.receive_json()["event"] == "pong"


def test_cors_covers_preflights_and_authorization_errors(runtime):
    client = TestClient(runtime.os.get_app())
    response = client.options(
        "/config",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    response = client.get("/config", headers={"Origin": ORIGIN, **auth("invalid")})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_unverified_development_middleware_cannot_open_the_public_api(runtime):
    app = runtime.os.get_app()
    app.add_middleware(AuthMiddleware, validate=False, authorization=True)
    response = TestClient(app).get("/config", headers=auth(token(key="untrusted-signature-key-at-least-32-bytes")))
    assert response.status_code == 404


def test_public_only_mode_retains_its_closed_api_and_sockets(runtime):
    runtime.os.authorization = False
    runtime.os.authorization_config = None
    client = TestClient(runtime.os.get_app())
    assert client.get("/config", headers=auth()).status_code == 404
    assert client.get("/info").status_code == 404
    assert client.get("/agents").status_code == 200
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect("/workflows/ws"):
            pass
    assert error.value.code == 1008


def test_custom_workflow_socket_cannot_inherit_the_native_authentication_exemption(runtime):
    from fastapi import WebSocket

    base = FastAPI()

    @base.websocket("/workflows/ws")
    async def custom_socket(socket: WebSocket):
        await socket.accept()
        await socket.send_json({"private": "custom-handler"})

    runtime.os.base_app = base
    client = TestClient(runtime.os.get_app())
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect("/workflows/ws"):
            pass
    assert error.value.code == 1008


def test_mcp_serves_only_explicit_tools_for_anonymous_and_admin_callers(runtime):
    with TestClient(runtime.os.get_app()) as client:
        for credentials in ({}, auth()):
            response = client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream", **credentials},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert response.status_code == 200, response.text
            import json

            data = (
                response.json()
                if response.headers["content-type"].startswith("application/json")
                else json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith("data: ")))
            )
            assert [tool["name"] for tool in data["result"]["tools"]] == ["echo"]
    assert runtime.limiter.calls == ["mcp", "mcp"]


def test_configured_mcp_oauth_still_requires_its_own_authentication(runtime):
    from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider

    runtime.os.mcp_auth = InMemoryOAuthProvider(base_url="http://localhost")
    with TestClient(runtime.os.get_app(), base_url="http://localhost") as client:
        assert client.get("/.well-known/oauth-authorization-server").status_code == 200
        response = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 401, response.text
        assert "resource_metadata" in response.headers["www-authenticate"]
        assert client.get("/config", headers=auth()).status_code == 200
