"""Verified tenant identity propagation; these tests do not assert tenant isolation."""

import json
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.agent.factory import AgentFactory
from agno.factory import RequestContext, TrustedContext
from agno.os import AgentOS
from agno.os.authz import Authorization
from agno.os.middleware.jwt import JWTMiddleware, JWTValidator
from agno.os.utils import build_request_context, resolve_ws_jwt_config

SECRET = "tenant-identity-test-secret-at-least-32-bytes"


def token(**claims):
    return jwt.encode({"sub": "same-user", **claims}, SECRET, algorithm="HS256")


def probe_app(**middleware_kwargs):
    app = FastAPI()

    @app.post("/probe")
    async def probe(request: Request):
        body = await request.json()
        ctx = build_request_context(request, factory_input=json.dumps(body))
        return {"tenant": ctx.tenant_id, "trusted": ctx.trusted.tenant_id, "input": ctx.input}

    keys = [] if middleware_kwargs.get("security_key") else [SECRET]
    app.add_middleware(JWTMiddleware, verification_keys=keys, algorithm="HS256", **middleware_kwargs)
    return app


def request(client, bearer, **body):
    return client.post(
        "/probe?tenant_id=forged-query",
        json={"tenant_id": "forged-body", **body},
        headers={"Authorization": f"Bearer {bearer}", "X-Tenant-Id": "forged-header"},
    )


@pytest.mark.parametrize("tenant", ["acme", "globex", " space-preserved "])
def test_verified_identity_ignores_client_input(tenant):
    with TestClient(probe_app(tenant_claim="org_id")) as client:
        result = request(client, token(org_id=tenant)).json()
    assert result == {"tenant": tenant, "trusted": tenant, "input": {"tenant_id": "forged-body"}}


@pytest.mark.parametrize("claims", [{}, {"scopes": ["agent_os:admin"]}])
def test_missing_claim_has_no_tenant(claims):
    with TestClient(probe_app(tenant_claim="org_id")) as client:
        assert request(client, token(**claims)).json()["tenant"] is None


def test_admin_retains_tenant():
    with TestClient(probe_app(tenant_claim="org_id", authorization=True)) as client:
        assert request(client, token(org_id="acme", scopes=["agent_os:admin"])).json()["tenant"] == "acme"


@pytest.mark.parametrize("value", [None, "", "  ", 1, True, [], {}, ["acme"]])
def test_malformed_present_claim_rejects_authentication(value):
    with TestClient(probe_app(tenant_claim="org_id")) as client:
        assert request(client, token(org_id=value)).status_code == 401


def test_unconfigured_identity_remains_none_even_with_malformed_claim():
    with TestClient(probe_app()) as client:
        assert request(client, token(org_id=["acme"])).json()["tenant"] is None


def test_invalid_signature_cannot_assert_tenant():
    forged = jwt.encode(
        {"sub": "same-user", "org_id": "acme"}, "wrong-secret-at-least-32-bytes-long", algorithm="HS256"
    )
    with TestClient(probe_app(tenant_claim="org_id")) as client:
        assert request(client, forged).status_code == 401


@pytest.mark.parametrize("value", ["", " ", 123, False, []])
def test_invalid_configuration_rejected(value):
    with pytest.raises(ValueError, match="tenant_claim"):
        Authorization(tenant_claim=value)
    with pytest.raises(ValueError, match="tenant_claim"):
        JWTValidator(verification_keys=[SECRET], algorithm="HS256", tenant_claim=value)


def test_unverified_mode_cannot_enable_tenant_identity():
    with pytest.raises(ValueError, match="signature validation"):
        JWTValidator(validate=False, tenant_claim="org_id")
    with pytest.raises(ValueError, match="signature validation"):
        JWTMiddleware(FastAPI(), validate=False, tenant_claim="org_id")


@pytest.mark.parametrize("credential", ["operator-key", "scheduler-secret"])
def test_operator_and_scheduler_credentials_have_no_tenant(credential):
    app = probe_app(tenant_claim="org_id", security_key="operator-key")
    app.state.internal_service_token = "scheduler-secret"
    with TestClient(app) as client:
        result = request(client, credential)
    assert result.status_code == 200
    assert result.json()["tenant"] is None


@pytest.mark.parametrize("verified", [True, False])
def test_mounted_middleware_normalizes_only_verified_outer_claims(verified):
    inner = probe_app(tenant_claim="org_id")
    outer = FastAPI()
    outer.mount("/child", inner)
    outer.add_middleware(JWTMiddleware, verification_keys=[SECRET], algorithm="HS256", validate=verified)
    with TestClient(outer) as client:
        result = client.post("/child/probe", json={}, headers={"Authorization": f"Bearer {token(org_id='acme')}"})
    assert result.status_code == (200 if verified else 401)
    if verified:
        assert result.json()["tenant"] == "acme"


def test_authorization_wires_rest_mcp_and_websocket_validators():
    from agno.os.mcp import _identity_bridge_kwargs
    from agno.os.mcp_auth import _build_jwt_token_verifier

    os = AgentOS(
        telemetry=False,
        agents=[Agent(id="demo")],
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256", tenant_claim="org_id"),
    )
    app = os.get_app()
    validator = resolve_ws_jwt_config(app)["validator"]
    assert validator.tenant_claim == "org_id"
    assert _build_jwt_token_verifier(os)._validator.tenant_claim == "org_id"
    assert _identity_bridge_kwargs(os)["tenant_claim"] == "org_id"
    assert "tenant_claim" not in os.authorization_config.model_dump()

    @app.post("/probe")
    async def probe(request: Request):
        return {"tenant": build_request_context(request).tenant_id}

    with TestClient(app) as client:
        result = request(client, token(org_id="acme", scopes=["agent_os:admin"]))
    assert result.status_code == 200
    assert result.json()["tenant"] == "acme"


def test_manual_websocket_config_validates_tenant():
    app = probe_app(tenant_claim="org_id")
    validator = resolve_ws_jwt_config(app)["validator"]
    claims = validator.extract_claims(validator.validate_token(token(org_id="acme")))
    assert claims["tenant_id"] == "acme"
    with pytest.raises(jwt.InvalidTokenError):
        validator.validate_token(token(org_id=[]))


@pytest.mark.asyncio
async def test_sync_and_async_factory_identity():
    agent = MagicMock(id="result", db=None, knowledge=None, tools=None)
    seen = []

    def build(ctx):
        seen.append((ctx.user_id, ctx.tenant_id, ctx.trusted.tenant_id))
        return agent

    async def abuild(ctx):
        return build(ctx)

    factory = AgentFactory(id="sync", db=MagicMock(), factory=build)
    async_factory = AgentFactory(id="async", db=MagicMock(), factory=abuild)
    acme = RequestContext(user_id="same-user", input={"tenant_id": "forged"}, trusted=TrustedContext(tenant_id="acme"))
    globex = RequestContext(user_id="same-user", trusted=TrustedContext(tenant_id="globex"))
    factory.invoke(acme)
    await factory.invoke_async(globex)
    await async_factory.invoke_async(acme)
    assert seen == [("same-user", "acme", "acme"), ("same-user", "globex", "globex"), ("same-user", "acme", "acme")]
    with pytest.raises(FrozenInstanceError):
        acme.tenant_id = "forged"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claims,expected,status",
    [
        ({"sub": "user", "org_id": "acme"}, "acme", None),
        ({"sub": "user"}, None, None),
        ({"sub": "user", "org_id": []}, None, 403),
        ({"sub": "sa:service", "agno_service_account": "service", "org_id": "acme"}, None, None),
        ({"sub": "__oauth__:client", "agno_mcp_internal_issuer": True, "org_id": "acme"}, None, None),
    ],
)
async def test_mcp_verified_identity_bridge(claims, expected, status):
    from agno.os.mcp_auth import MCPIdentityBridgeMiddleware

    captured = []
    sent = []

    async def downstream(scope, receive, send):
        captured.append(scope["state"].get("tenant_id"))

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "user": SimpleNamespace(access_token=SimpleNamespace(claims=claims, scopes=[]))}
    bridge = MCPIdentityBridgeMiddleware(downstream, tenant_claim="org_id")
    await bridge(scope, None, send)
    if status:
        assert not captured
        assert sent[0]["status"] == status
    else:
        assert captured == [expected]


def test_unconfigured_claim_extraction_keeps_legacy_shape():
    validator = JWTValidator(verification_keys=[SECRET], algorithm="HS256")
    assert validator.extract_claims({"sub": "user", "org_id": "acme"}) == {
        "user_id": "user",
        "session_id": None,
        "scopes": [],
        "audience": None,
    }


@pytest.mark.asyncio
async def test_mcp_jwt_verifier_rejects_malformed_tenant():
    from agno.os.mcp_auth import JWTBearerTokenVerifier

    verifier = JWTBearerTokenVerifier(
        JWTValidator(verification_keys=[SECRET], algorithm="HS256", tenant_claim="org_id")
    )
    assert await verifier.verify_token(token(org_id=[])) is None
    verified = await verifier.verify_token(token(org_id="acme"))
    assert verified is not None
    assert verified.claims["org_id"] == "acme"


def test_mounted_middleware_rejects_malformed_claim_from_verified_outer():
    inner = probe_app(tenant_claim="org_id")
    outer = FastAPI()
    outer.mount("/child", inner)
    outer.add_middleware(JWTMiddleware, verification_keys=[SECRET], algorithm="HS256")
    with TestClient(outer) as client:
        response = client.post("/child/probe", json={}, headers={"Authorization": f"Bearer {token(org_id=[])}"})
    assert response.status_code == 401


def test_websocket_reauthentication_does_not_delegate_jwt_tenant_to_pat(monkeypatch):
    async def verify_pat(token, app, client_key=None):
        return SimpleNamespace(ok=True, account=SimpleNamespace(principal="sa:runner", scopes=["workflows:run"]))

    async def capture(websocket, message, os, **kwargs):
        await websocket.send_json({"event": "captured", "tenant": kwargs["ws_user_context"].get("tenant_id")})

    monkeypatch.setattr("agno.os.router.verify_websocket_service_account", verify_pat)
    monkeypatch.setattr("agno.os.router.handle_workflow_via_websocket", capture)
    os = AgentOS(
        id="tenant-ws",
        agents=[Agent(id="demo")],
        telemetry=False,
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256", tenant_claim="org_id"),
    )
    with TestClient(os.get_app()).websocket_connect("/workflows/ws") as ws:
        for bearer, expected in [(token(org_id="acme", scopes=["workflows:run"]), "acme"), ("agno_pat_fake", None)]:
            ws.send_json({"action": "authenticate", "token": bearer})
            for _ in range(10):
                if ws.receive_json().get("event") == "authenticated":
                    break
            else:
                pytest.fail("WebSocket authentication did not finish")
            ws.send_json({"action": "start-workflow", "workflow_id": "demo", "message": "hi", "tenant_id": "forged"})
            for _ in range(10):
                event = ws.receive_json()
                if event.get("event") not in ("connected", "authenticated", "ping"):
                    break
            assert event == {"event": "captured", "tenant": expected}
