"""The WebSocket surface rules on the deployment's admin scope, not on the default one.

``admin_scope`` and ``user_isolation`` are deployment settings configured
independently of any JWT key source, and the auth layer stamps both on
``app.state`` in every authenticated mode. The WebSocket config resolver read
them only on the branch where a JWT validator exists, so a deployment
authenticated by security key or by service-account tokens fell through to a
blank config: the WebSocket dispatcher then treated the DEFAULT scope name as
admin (promoting a token that REST treats as ordinary) and ignored the
configured admin scope (demoting a token REST treats as admin) - inverted
against REST in both directions - while user isolation silently stayed off.

These tests pin the resolution on every auth shape, and pin the inversion
itself over a real socket.
"""

import json
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.middleware.jwt import AuthMiddleware, JWTMiddleware
from agno.os.scopes import AgentOSScope
from agno.os.settings import AgnoAPISettings
from agno.os.utils import resolve_ws_jwt_config

CUSTOM_ADMIN_SCOPE = "ops:admin"
DEFAULT_ADMIN_SCOPE = AgentOSScope.ADMIN.value
JWT_SECRET = "ws-scope-secret-value-32-bytes-long"
OS_ID = "ws-scope-os"


def _ws_admin_scope(app) -> str:
    """The admin scope the WebSocket dispatcher ends up enforcing."""
    return resolve_ws_jwt_config(app).get("admin_scope") or DEFAULT_ADMIN_SCOPE


def _ws_user_isolation(app) -> bool:
    return bool(resolve_ws_jwt_config(app).get("user_isolation", False))


def _rest_admin_scope(app) -> str:
    """The admin scope the HTTP surface enforces, read from app.state.

    AgentOS populates app.state for every authenticated mode; the REST helpers
    and the MCP identity bridge read it from there.
    """
    raw = getattr(app.state, "admin_scope", None)
    return raw if isinstance(raw, str) and raw else DEFAULT_ADMIN_SCOPE


def _rest_user_isolation(app) -> bool:
    return bool(getattr(app.state, "user_isolation_enabled", False))


def _authorization_config(**overrides) -> AuthorizationConfig:
    values: Dict[str, Any] = {"admin_scope": CUSTOM_ADMIN_SCOPE, "user_isolation": True}
    values.update(overrides)
    return AuthorizationConfig(**values)


def _jwt_app(tmp_path):
    """Shape 1: JWT-authenticated deployment (the branch that already worked)."""
    return AgentOS(
        id=OS_ID,
        db=SqliteDb(db_file=str(tmp_path / "jwt.db")),
        authorization=True,
        authorization_config=_authorization_config(verification_keys=[JWT_SECRET], algorithm="HS256"),
        telemetry=False,
    ).get_app()


def _security_key_app(tmp_path):
    """Shape 2: security-key deployment - no JWT key anywhere."""
    return AgentOS(
        id=OS_ID,
        db=SqliteDb(db_file=str(tmp_path / "seckey.db")),
        settings=AgnoAPISettings(os_security_key="sec-key-1"),
        authorization_config=_authorization_config(),
        telemetry=False,
    ).get_app()


def _service_account_app(tmp_path):
    """Shape 3: service-account tokens over a security-key deployment."""
    return AgentOS(
        id=OS_ID,
        db=SqliteDb(db_file=str(tmp_path / "sa.db")),
        settings=AgnoAPISettings(os_security_key="sec-key-2"),
        authorization_config=_authorization_config(user_isolation=False),
        telemetry=False,
    ).get_app()


def _keyless_app(tmp_path):
    """Shape 4: no credential configured at all - no auth layer is installed."""
    return AgentOS(id=OS_ID, db=SqliteDb(db_file=str(tmp_path / "open.db")), telemetry=False).get_app()


class TestEveryAuthShapeResolvesTheDeploymentSettings:
    """One resolution per auth shape, checked against what REST reads."""

    def test_jwt_deployment_is_unchanged(self, tmp_path):
        app = _jwt_app(tmp_path)
        config = resolve_ws_jwt_config(app)

        assert config["validator"] is not None
        assert config["auth_required"] is True
        assert config["admin_scope"] == CUSTOM_ADMIN_SCOPE
        assert config["user_isolation"] is True
        assert _ws_admin_scope(app) == _rest_admin_scope(app) == CUSTOM_ADMIN_SCOPE
        assert _ws_user_isolation(app) == _rest_user_isolation(app) is True

    def test_security_key_deployment_agrees_with_rest(self, tmp_path):
        app = _security_key_app(tmp_path)

        # No JWT validator: this is precisely the branch that returned blank.
        assert resolve_ws_jwt_config(app)["validator"] is None
        assert _rest_admin_scope(app) == CUSTOM_ADMIN_SCOPE
        assert _ws_admin_scope(app) == _rest_admin_scope(app)
        assert _ws_user_isolation(app) == _rest_user_isolation(app) is True

    def test_service_account_deployment_agrees_with_rest(self, tmp_path):
        app = _service_account_app(tmp_path)

        assert resolve_ws_jwt_config(app)["validator"] is None
        assert _ws_admin_scope(app) == _rest_admin_scope(app) == CUSTOM_ADMIN_SCOPE
        # Isolation is off in this deployment, and must stay off on both surfaces.
        assert _ws_user_isolation(app) == _rest_user_isolation(app) is False

    def test_keyless_deployment_falls_back_on_both_surfaces(self, tmp_path):
        app = _keyless_app(tmp_path)

        # Nothing is configured, so both surfaces use the default scope name.
        assert _ws_admin_scope(app) == _rest_admin_scope(app) == DEFAULT_ADMIN_SCOPE
        assert _ws_user_isolation(app) == _rest_user_isolation(app) is False
        assert resolve_ws_jwt_config(app)["auth_required"] is False

    def test_configured_scope_is_never_the_default_name(self, tmp_path):
        """Guard the guard: the assertions above would be vacuous if the custom
        scope happened to equal the default."""
        assert CUSTOM_ADMIN_SCOPE != DEFAULT_ADMIN_SCOPE
        assert _ws_admin_scope(_security_key_app(tmp_path)) != DEFAULT_ADMIN_SCOPE


class TestManualMiddlewareBeforeAnyHttpRequest:
    """app.state is only populated lazily on the manual setup path, and a
    keyless auth layer never populates it at all."""

    def test_keyless_auth_layer_kwargs_are_read(self):
        app = FastAPI()
        app.add_middleware(
            AuthMiddleware,
            security_key="manual-key",
            admin_scope=CUSTOM_ADMIN_SCOPE,
            user_isolation=True,
        )

        config = resolve_ws_jwt_config(app)

        # Still not a JWT deployment: the WS endpoint keeps falling through to
        # the PAT and security-key auth paths.
        assert config["validator"] is None
        assert config["auth_required"] is False
        assert config["admin_scope"] == CUSTOM_ADMIN_SCOPE
        assert config["user_isolation"] is True

    def test_jwt_middleware_kwargs_are_still_read(self):
        app = FastAPI()
        app.add_middleware(
            JWTMiddleware,
            verification_keys=[JWT_SECRET],
            algorithm="HS256",
            admin_scope=CUSTOM_ADMIN_SCOPE,
            user_isolation=True,
        )

        config = resolve_ws_jwt_config(app)

        assert config["validator"] is not None
        assert config["auth_required"] is True
        assert config["admin_scope"] == CUSTOM_ADMIN_SCOPE
        assert config["user_isolation"] is True

    def test_nothing_configured_stays_blank(self):
        config = resolve_ws_jwt_config(FastAPI())

        assert config["admin_scope"] is None
        assert config["user_isolation"] is False

    def test_state_wins_over_middleware_kwargs(self):
        """app.state is the live decision; the kwargs are only the fallback."""
        app = FastAPI()
        app.add_middleware(AuthMiddleware, security_key="manual-key", admin_scope="stale:admin")
        app.state.admin_scope = CUSTOM_ADMIN_SCOPE

        assert resolve_ws_jwt_config(app)["admin_scope"] == CUSTOM_ADMIN_SCOPE


class FakeAccount:
    def __init__(self, principal: str, scopes: List[str]):
        self.principal = principal
        self.scopes = scopes


# The socket greets on connect and confirms the authentication twice (the
# manager's own frame plus the endpoint's), so tests read past those.
HANDSHAKE_EVENTS = ("connected", "authenticated", "ping")


def _next_event(ws, expected: str) -> Dict[str, Any]:
    """Read frames until the expected event arrives."""
    for _ in range(10):
        frame = json.loads(ws.receive_text())
        if frame.get("event") == expected:
            return frame
        assert frame.get("event") in HANDSHAKE_EVENTS, frame
    raise AssertionError(f"never received {expected}")


def _any_event(ws) -> str:
    """The first frame that is not part of the handshake."""
    for _ in range(10):
        frame = json.loads(ws.receive_text())
        if frame.get("event") not in HANDSHAKE_EVENTS:
            return frame.get("event")
    raise AssertionError("no event arrived")


def _patch_pat_identity(monkeypatch, *, principal: str, scopes: List[str]) -> None:
    """Accept one PAT with the given identity, without touching the database."""

    async def fake_verify(token, app, client_key=None):
        return SimpleNamespace(ok=True, status=None, account=FakeAccount(principal, scopes))

    monkeypatch.setattr("agno.os.router.verify_websocket_service_account", fake_verify)


def _capture_start_workflow(monkeypatch) -> List[Dict[str, Any]]:
    """Record the auth context and message the dispatcher hands the handler."""
    captured: List[Dict[str, Any]] = []

    async def fake_handler(websocket, message, os, **kwargs):
        captured.append({"message": message, "ws_auth": kwargs.get("ws_auth")})
        await websocket.send_text(json.dumps({"event": "captured"}))

    monkeypatch.setattr("agno.os.router.handle_workflow_via_websocket", fake_handler)
    return captured


def _start_workflow_as(app, monkeypatch, *, scopes: List[str]) -> Dict[str, Any]:
    captured = _capture_start_workflow(monkeypatch)
    _patch_pat_identity(monkeypatch, principal="sa:runner", scopes=scopes)

    with TestClient(app).websocket_connect("/workflows/ws") as ws:
        ws.send_text(json.dumps({"action": "authenticate", "token": "agno_pat_fake"}))
        _next_event(ws, "authenticated")
        ws.send_text(
            json.dumps({"action": "start-workflow", "workflow_id": "wf-1", "message": "hi", "user_id": "victim"})
        )
        _next_event(ws, "captured")

    assert len(captured) == 1
    return captured[0]


class TestTheInversionOverTheRealSocket:
    """A security-key deployment with a custom admin scope, driven by a PAT."""

    def test_default_scope_name_is_not_admin(self, tmp_path, monkeypatch):
        app = _security_key_app(tmp_path)
        result = _start_workflow_as(app, monkeypatch, scopes=["workflows:run", DEFAULT_ADMIN_SCOPE])

        # This deployment does not treat the default scope name as admin, so the
        # caller is ordinary: their run is attributed to the token, not to the
        # user_id the client frame chose.
        assert result["ws_auth"].is_admin is False
        assert result["message"]["user_id"] == "sa:runner"

    def test_configured_scope_is_admin(self, tmp_path, monkeypatch):
        app = _security_key_app(tmp_path)
        result = _start_workflow_as(app, monkeypatch, scopes=["workflows:run", CUSTOM_ADMIN_SCOPE])

        # The configured admin scope grants admin on this surface too, so the
        # act-on-behalf-of user_id in the frame survives.
        assert result["ws_auth"].is_admin is True
        assert result["message"]["user_id"] == "victim"

    def test_user_isolation_reaches_the_handler(self, tmp_path, monkeypatch):
        app = _security_key_app(tmp_path)
        result = _start_workflow_as(app, monkeypatch, scopes=["workflows:run"])

        assert result["ws_auth"].user_isolation_enabled is True
        assert result["message"]["user_id"] == "sa:runner"

    def test_isolation_off_deployment_keeps_it_off(self, tmp_path, monkeypatch):
        app = _service_account_app(tmp_path)
        result = _start_workflow_as(app, monkeypatch, scopes=["workflows:run"])

        assert result["ws_auth"].user_isolation_enabled is False

    def test_jwt_deployment_is_unchanged_over_the_socket(self, tmp_path, monkeypatch):
        """Control: the branch that already worked keeps working."""
        app = _jwt_app(tmp_path)

        forged = _start_workflow_as(app, monkeypatch, scopes=["workflows:run", DEFAULT_ADMIN_SCOPE])
        assert forged["ws_auth"].is_admin is False

        real = _start_workflow_as(app, monkeypatch, scopes=["workflows:run", CUSTOM_ADMIN_SCOPE])
        assert real["ws_auth"].is_admin is True


class TestRbacUsesTheSameScope:
    """The run-permission gate reads the same admin scope, so an admin PAT
    carrying no explicit workflows:run must still be allowed - and a forged
    one must not."""

    def _run_permission_outcome(self, app, monkeypatch, scopes: List[str]) -> Optional[str]:
        _capture_start_workflow(monkeypatch)
        _patch_pat_identity(monkeypatch, principal="sa:runner", scopes=scopes)
        with TestClient(app).websocket_connect("/workflows/ws") as ws:
            ws.send_text(json.dumps({"action": "authenticate", "token": "agno_pat_fake"}))
            _next_event(ws, "authenticated")
            ws.send_text(json.dumps({"action": "start-workflow", "workflow_id": "wf-1", "message": "hi"}))
            return _any_event(ws)

    def test_configured_admin_scope_alone_passes_rbac(self, tmp_path, monkeypatch):
        app = _security_key_app(tmp_path)
        assert self._run_permission_outcome(app, monkeypatch, [CUSTOM_ADMIN_SCOPE]) == "captured"

    def test_default_scope_name_alone_fails_rbac(self, tmp_path, monkeypatch):
        app = _security_key_app(tmp_path)
        assert self._run_permission_outcome(app, monkeypatch, [DEFAULT_ADMIN_SCOPE]) == "error"


@pytest.mark.parametrize("action", ["reconnect", "continue-workflow"])
def test_every_ws_action_uses_the_same_admin_scope(tmp_path, monkeypatch, action):
    """start-workflow, reconnect and continue-workflow each re-derive is_admin
    from the same resolved scope, so all three move together."""
    captured: List[Dict[str, Any]] = []

    async def fake_handler(websocket, message, os, **kwargs):
        captured.append({"message": message, "ws_auth": kwargs.get("ws_auth")})
        await websocket.send_text(json.dumps({"event": "captured"}))

    target = {
        "reconnect": "agno.os.router.handle_workflow_subscription",
        "continue-workflow": "agno.os.router.handle_workflow_continue_via_websocket",
    }[action]
    monkeypatch.setattr(target, fake_handler)
    _patch_pat_identity(monkeypatch, principal="sa:runner", scopes=["workflows:run", CUSTOM_ADMIN_SCOPE])

    app = _security_key_app(tmp_path)
    with TestClient(app).websocket_connect("/workflows/ws") as ws:
        ws.send_text(json.dumps({"action": "authenticate", "token": "agno_pat_fake"}))
        _next_event(ws, "authenticated")
        ws.send_text(
            json.dumps(
                {
                    "action": action,
                    "workflow_id": "wf-1",
                    "run_id": "r-1",
                    "session_id": "s-1",
                    "user_id": "victim",
                }
            )
        )
        _next_event(ws, "captured")

    assert captured[0]["ws_auth"].is_admin is True
    assert captured[0]["ws_auth"].user_isolation_enabled is True


class TestSecurityKeyOnlySocket:
    """A socket authenticated by the bare security key carries no identity and
    no scopes, so scope enforcement stays off and the run-ownership gates stay
    dormant - but the deployment's isolation flag now reaches the dispatcher,
    which stops taking the run's user_id from the client frame.

    The REST surface differs here: its security-key branch never stamps the
    isolation flag on the request, so a security-key REST caller keeps the
    user_id it sends. Pinned so the difference is visible, not discovered.
    """

    def test_identity_is_not_taken_from_the_frame(self, tmp_path, monkeypatch):
        captured = _capture_start_workflow(monkeypatch)
        app = _security_key_app(tmp_path)

        with TestClient(app).websocket_connect("/workflows/ws") as ws:
            ws.send_text(json.dumps({"action": "authenticate", "token": "sec-key-1"}))
            _next_event(ws, "authenticated")
            ws.send_text(
                json.dumps({"action": "start-workflow", "workflow_id": "wf-1", "message": "hi", "user_id": "victim"})
            )
            _next_event(ws, "captured")

        ws_auth = captured[0]["ws_auth"]
        assert ws_auth.jwt_enabled is False
        assert ws_auth.is_admin is False
        assert ws_auth.user_isolation_enabled is True
        assert captured[0]["message"]["user_id"] is None
