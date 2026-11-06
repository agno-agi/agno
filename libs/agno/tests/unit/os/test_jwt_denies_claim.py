"""A token's denies claim is enforced on every path that reads JWT scopes."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.auth import _caller_is_approval_admin
from agno.os.config import AuthorizationConfig, MCPConfig
from agno.os.mcp_auth import _build_jwt_token_verifier

SECRET = "denies-claim-test-secret-at-least-32-bytes"


def _make_os(tmp_path, mcp=False, **config):
    return AgentOS(
        id="denies-test",
        db=SqliteDb(db_file=str(tmp_path / "app.db")),
        agents=[Agent(id="x", telemetry=False), Agent(id="y", telemetry=False)],
        company=CompanyConfig(),
        authorization=True,
        authorization_config=AuthorizationConfig(verification_keys=[SECRET], algorithm="HS256", **config),
        mcp=MCPConfig(default_tools=True, stateless=True) if mcp else None,
        telemetry=False,
    )


@pytest.fixture
def agent_os(tmp_path):
    return _make_os(tmp_path)


@pytest.fixture
def client(agent_os):
    return TestClient(agent_os.get_app())


def _token(agent_os, scopes, denies=None):
    payload = {
        "sub": "user",
        "aud": agent_os.id,
        "scopes": scopes,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    if denies is not None:
        payload["denies"] = denies
    return jwt.encode(payload, SECRET, algorithm="HS256")


def _headers(agent_os, scopes, denies=None):
    return {"Authorization": "Bearer " + _token(agent_os, scopes, denies)}


class TestRouteGate:
    def test_admin_without_denies_reaches_the_route(self, agent_os, client):
        response = client.delete("/company/tasks/missing", headers=_headers(agent_os, ["agent_os:admin"]))
        assert response.status_code not in (401, 403)

    def test_admin_deny_blocks_only_the_denied_action(self, agent_os, client):
        headers = _headers(agent_os, ["agent_os:admin"], ["tasks:delete"])
        assert client.delete("/company/tasks/missing", headers=headers).status_code == 403
        assert client.get("/company/tasks", headers=headers).status_code == 200

    def test_wildcard_allow_with_per_id_deny_blocks_that_agent(self, agent_os, client):
        headers = _headers(agent_os, ["agents:*:read"], ["agents:x:read"])
        assert client.get("/agents/x", headers=headers).status_code == 403

    def test_malformed_denies_claim_grants_nothing(self, agent_os, client):
        headers = _headers(agent_os, ["agent_os:admin"], {"tasks": "delete"})
        assert client.get("/company/tasks", headers=headers).status_code == 403


class TestServiceAccountMinting:
    def _mint(self, client, headers, scopes):
        body = {
            "name": "minted",
            "scopes": [{"scope": s, "effect": "allow"} for s in scopes],
            "allow_privileged_scopes": True,
        }
        return client.post("/service-accounts", json=body, headers=headers)

    def test_cannot_mint_admin_to_escape_a_deny(self, agent_os, client):
        headers = _headers(agent_os, ["agent_os:admin"], ["tasks:delete"])
        assert self._mint(client, headers, ["agent_os:admin"]).status_code == 403

    def test_cannot_mint_the_denied_scope(self, agent_os, client):
        headers = _headers(agent_os, ["agent_os:admin"], ["tasks:delete"])
        assert self._mint(client, headers, ["tasks:delete"]).status_code == 403

    def test_cannot_mint_a_wildcard_covering_a_per_id_deny(self, agent_os, client):
        headers = _headers(agent_os, ["service_accounts:write", "agents:*:run"], ["agents:x:run"])
        assert self._mint(client, headers, ["agents:*:run"]).status_code == 403

    def test_can_still_mint_allowed_scopes(self, agent_os, client):
        headers = _headers(agent_os, ["agent_os:admin"], ["tasks:delete"])
        assert self._mint(client, headers, ["tasks:read"]).status_code == 201


class TestOtherTokenEntryPoints:
    def test_websocket_validator_applies_denies(self, agent_os):
        app = agent_os.get_app()
        payload = jwt.decode(
            _token(agent_os, ["agent_os:admin"], ["tasks:delete"]), options={"verify_signature": False}
        )
        scopes = app.state.jwt_validator.extract_claims(payload)["scopes"]
        assert "agent_os:admin" not in scopes and "tasks:delete" not in scopes
        assert "tasks:write" in scopes

    def test_mcp_jwt_verifier_applies_denies(self, agent_os):
        verifier = _build_jwt_token_verifier(agent_os)
        access_token = asyncio.run(verifier.verify_token(_token(agent_os, ["agents:*:run"], ["agents:x:run"])))
        assert access_token is not None
        assert access_token.scopes == []

    def test_external_mcp_provider_applies_denies(self):
        pytest.importorskip("fastmcp")
        from fastmcp.server.auth import RemoteAuthProvider
        from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
        from pydantic import AnyHttpUrl

        from agno.os.mcp_auth import _MarkerScrubbingProvider

        tokens = {
            "denied": {"client_id": "u", "scopes": ["agents:*:run", "agents:read"], "denies": ["agents:x:run"]},
            "plain": {"client_id": "u", "scopes": ["agents:*:run"]},
        }
        provider = _MarkerScrubbingProvider(
            RemoteAuthProvider(
                token_verifier=StaticTokenVerifier(tokens=tokens),
                authorization_servers=[AnyHttpUrl("https://as.example.com")],
                base_url="http://localhost",
            )
        )
        assert asyncio.run(provider.verify_token("denied")).scopes == ["agents:read"]
        assert asyncio.run(provider.verify_token("plain")).scopes == ["agents:*:run"]


class TestTokensWithoutDenies:
    def test_websocket_and_mcp_scopes_are_unchanged(self, agent_os):
        app = agent_os.get_app()
        token = _token(agent_os, ["agent_os:admin", "agents::run"])
        payload = jwt.decode(token, options={"verify_signature": False})
        assert app.state.jwt_validator.extract_claims(payload)["scopes"] == ["agent_os:admin", "agents::run"]
        access_token = asyncio.run(_build_jwt_token_verifier(agent_os).verify_token(token))
        assert access_token.scopes == ["agent_os:admin", "agents::run"]


class TestClaimsCopies:
    def test_mcp_claims_carry_the_restricted_scopes(self, agent_os):
        access_token = asyncio.run(
            _build_jwt_token_verifier(agent_os).verify_token(_token(agent_os, ["agents:*:run"], ["agents:x:run"]))
        )
        assert access_token.claims["scopes"] == []

    def test_request_state_claims_carry_the_restricted_scopes(self, agent_os):
        app = agent_os.get_app()

        @app.get("/denies-probe")
        def probe(request: Request):
            return {"scopes": request.state.scopes, "claims_scopes": request.state.claims["scopes"]}

        response = TestClient(app).get(
            "/denies-probe", headers=_headers(agent_os, ["tasks:read", "tasks:delete"], ["tasks:delete"])
        )
        assert response.json() == {"scopes": ["tasks:read"], "claims_scopes": ["tasks:read"]}


class TestScheduling:
    def _schedule(self, client, headers, agent_id):
        body = {"name": "nightly-" + agent_id, "cron_expr": "0 0 * * *", "endpoint": f"/agents/{agent_id}/runs"}
        return client.post("/schedules", json={**body, "payload": {"message": "hi"}}, headers=headers)

    def test_cannot_schedule_a_run_of_a_denied_agent(self, agent_os, client):
        headers = _headers(agent_os, ["schedules:write", "agents:*:run"], ["agents:x:run"])
        assert self._schedule(client, headers, "x").status_code == 403

    def test_schedules_a_run_without_denies(self, agent_os, client):
        headers = _headers(agent_os, ["schedules:write", "agents:*:run"])
        assert self._schedule(client, headers, "x").status_code == 201


class TestApprovalAdminGate:
    """The approval-admin check passes no admin_scope, so it honours the default spelling."""

    @pytest.fixture
    def custom_admin_client(self, tmp_path):
        agent_os = _make_os(tmp_path, admin_scope="acme:root")
        app = agent_os.get_app()

        @app.get("/approval-admin-probe")
        def probe(request: Request):
            return {"admin": _caller_is_approval_admin(request, request.state.scopes)}

        return agent_os, TestClient(app)

    def test_deny_revokes_approval_admin(self, custom_admin_client):
        agent_os, client = custom_admin_client
        headers = _headers(agent_os, ["agent_os:admin"], ["approvals:write"])
        assert client.get("/approval-admin-probe", headers=headers).json() == {"admin": False}

    def test_default_admin_spelling_is_approval_admin_without_denies(self, custom_admin_client):
        agent_os, client = custom_admin_client
        headers = _headers(agent_os, ["agent_os:admin"])
        assert client.get("/approval-admin-probe", headers=headers).json() == {"admin": True}


class TestMcpToolCall:
    @pytest.fixture
    def agent_os(self, tmp_path):
        return _make_os(tmp_path, mcp=True)

    def _run_agent(self, agent_os, scopes, denies=None):
        headers = {
            **_headers(agent_os, scopes, denies),
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        }
        call = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "run_agent", "arguments": {"agent_id": "x", "message": "hi"}},
        }
        with TestClient(agent_os.get_app()) as client:
            response = client.post("/mcp", json=call, headers=headers)
        assert response.status_code == 200, response.text
        return response.text

    def test_tool_gate_refuses_a_denied_agent(self, agent_os):
        assert "Insufficient permissions" in self._run_agent(agent_os, ["agents:*:run"], ["agents:x:run"])

    def test_tool_gate_passes_without_denies(self, agent_os):
        assert "Insufficient permissions" not in self._run_agent(agent_os, ["agents:*:run"])


class TestWebSocketHandshake:
    def _start_workflow(self, agent_os, monkeypatch, scopes, denies=None):
        captured = []

        async def fake_handler(websocket, message, os, **kwargs):
            captured.append(kwargs["ws_user_context"])
            await websocket.send_text(json.dumps({"event": "captured"}))

        monkeypatch.setattr("agno.os.router.handle_workflow_via_websocket", fake_handler)
        with TestClient(agent_os.get_app()).websocket_connect("/workflows/ws") as ws:
            ws.send_text(json.dumps({"action": "authenticate", "token": _token(agent_os, scopes, denies)}))
            assert self._next_event(ws, skip=("connected",)) == "authenticated"
            ws.send_text(json.dumps({"action": "start-workflow", "workflow_id": "wf-1", "message": "hi"}))
            outcome = self._next_event(ws, skip=("connected", "authenticated", "ping"))
        return outcome, captured

    @staticmethod
    def _next_event(ws, skip):
        """The next frame whose event is not in ``skip``; the manager and router both announce auth."""
        for _ in range(10):
            event = json.loads(ws.receive_text())["event"]
            if event not in skip:
                return event
        raise AssertionError("no event arrived")

    def test_denied_workflow_is_refused(self, agent_os, monkeypatch):
        outcome, captured = self._start_workflow(agent_os, monkeypatch, ["workflows:*:run"], ["workflows:wf-1:run"])
        assert outcome == "error" and captured == []

    def test_factory_claims_carry_the_restricted_scopes(self, agent_os, monkeypatch):
        outcome, captured = self._start_workflow(
            agent_os, monkeypatch, ["workflows:run", "agents:delete"], ["agents:delete"]
        )
        assert outcome == "captured"
        assert captured[0]["scopes"] == ["workflows:run"]
        assert captured[0]["payload"]["scopes"] == ["workflows:run"]

    def test_workflow_runs_without_denies(self, agent_os, monkeypatch):
        outcome, captured = self._start_workflow(agent_os, monkeypatch, ["workflows:*:run"])
        assert outcome == "captured"
        assert captured[0]["payload"]["scopes"] == ["workflows:*:run"]


class TestClaimKeys:
    def test_empty_denies_leaves_claims_untouched(self, agent_os):
        token = _token(agent_os, ["agents:read"], [])
        access_token = asyncio.run(_build_jwt_token_verifier(agent_os).verify_token(token))
        assert access_token.claims["scopes"] == ["agents:read"]
        assert access_token.claims["denies"] == []

    def test_external_provider_rewrites_the_oauth_scope_claim(self):
        pytest.importorskip("fastmcp")
        from fastmcp.server.auth import RemoteAuthProvider
        from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
        from pydantic import AnyHttpUrl

        from agno.os.mcp_auth import _MarkerScrubbingProvider

        tokens = {
            "denied": {
                "client_id": "u",
                "scopes": ["agents:*:run", "agents:read"],
                "scope": "agents:*:run agents:read",
                "denies": ["agents:x:run"],
            }
        }
        provider = _MarkerScrubbingProvider(
            RemoteAuthProvider(
                token_verifier=StaticTokenVerifier(tokens=tokens),
                authorization_servers=[AnyHttpUrl("https://as.example.com")],
                base_url="http://localhost",
            )
        )
        claims = asyncio.run(provider.verify_token("denied")).claims
        assert claims["scope"] == "agents:read"
        assert claims["scopes"] == ["agents:read"]
