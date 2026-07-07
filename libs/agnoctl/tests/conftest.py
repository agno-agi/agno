"""Test fixtures: an in-memory fake AgentOS served through httpx.MockTransport."""

import json
from typing import Any, Dict, List, Optional

import httpx
import pytest


class FakeAgentOS:
    """Simulates the AgentOS endpoints the CLI touches.

    auth_mode: "none" | "security_key" | "jwt"
    info_discovery: serve the mcp/auth_mode fields on /info (newer servers)
    mcp_requires_token: enforce tokens on /mcp (False models servers predating enforcement)
    """

    def __init__(
        self,
        auth_mode: str = "security_key",
        security_key: str = "test-admin-key",
        mcp_enabled: bool = True,
        info_discovery: bool = True,
        mcp_requires_token: bool = True,
        sse_responses: bool = False,
        agno_version: str = "2.7.0",
    ):
        self.auth_mode = auth_mode
        self.security_key = security_key
        self.mcp_enabled = mcp_enabled
        self.info_discovery = info_discovery
        self.mcp_requires_token = mcp_requires_token
        self.sse_responses = sse_responses
        self.agno_version = agno_version

        self.accounts: Dict[str, Dict[str, Any]] = {}  # name -> account dict (with plaintext token)
        self.create_calls = 0
        self.mcp_tools = ["run_agent", "run_team", "run_workflow", "get_agentos_config"]
        self._next_id = 1

    # -- helpers -------------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def active_tokens(self) -> List[str]:
        return [a["token"] for a in self.accounts.values() if not a.get("revoked_at")]

    def _bearer(self, request: httpx.Request) -> Optional[str]:
        value = request.headers.get("Authorization")
        if value and value.lower().startswith("bearer "):
            return value[len("bearer ") :]
        return value

    def _is_admin(self, request: httpx.Request) -> bool:
        if self.auth_mode == "none":
            return True
        return self._bearer(request) == self.security_key

    def _account_response(self, account: Dict[str, Any], include_token: bool = False) -> Dict[str, Any]:
        payload = {k: v for k, v in account.items() if k != "token"}
        # Render scopes in the parsed RBAC shape the server returns; the store keeps raw strings.
        payload["scopes"] = [self._scope_object(s) for s in account.get("scopes") or []]
        if include_token:
            payload["token"] = account["token"]
        return payload

    def _scope_object(self, raw: str) -> Dict[str, Any]:
        parts = raw.split(":")
        return {
            "id": None,
            "raw": raw,
            "namespace": parts[0],
            "sub_namespace": ":".join(parts[1:-1]) if len(parts) > 2 else None,
            "permission": parts[-1],
            "value": "allow",
        }

    def _jsonrpc_response(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> httpx.Response:
        if self.sse_responses:
            body = "event: message\ndata: " + json.dumps(payload) + "\n\n"
            return httpx.Response(
                200, content=body.encode(), headers={"content-type": "text/event-stream", **(headers or {})}
            )
        return httpx.Response(200, json=payload, headers=headers or {})

    # -- request handler -----------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "instantiated_at": "2026-07-04T00:00:00Z"})

        if path == "/info":
            payload: Dict[str, Any] = {"agno_version": self.agno_version, "agents": 1, "teams": 0, "workflows": 0}
            if self.info_discovery:
                payload["mcp"] = {"enabled": self.mcp_enabled, "path": "/mcp" if self.mcp_enabled else None}
                payload["auth_mode"] = self.auth_mode
            return httpx.Response(200, json=payload)

        if path == "/config":
            if self.auth_mode == "none":
                return httpx.Response(200, json={"os_id": "fake"})
            if self._bearer(request) == self.security_key:
                return httpx.Response(200, json={"os_id": "fake"})
            detail = (
                "Authorization header required" if self.auth_mode == "security_key" else "Authorization header missing"
            )
            return httpx.Response(401, json={"detail": detail})

        if path == "/service-accounts" and method == "POST":
            if not self._is_admin(request):
                return httpx.Response(401, json={"detail": "Invalid authentication token"})
            body = json.loads(request.content)
            name = body["name"]
            if name in self.accounts and not self.accounts[name].get("revoked_at"):
                return httpx.Response(409, json={"detail": "Service account '" + name + "' already exists"})
            self.create_calls += 1
            # Like the real server, the write shape is {scope, effect} objects only;
            # a plain-string scope is a 422. The store keeps raw strings.
            requested_scopes = body.get("scopes")
            if requested_scopes is not None and any(not isinstance(s, dict) for s in requested_scopes):
                return httpx.Response(422, json={"detail": "scopes must be {scope, effect} objects"})
            # Realistic length: real tokens are agno_pat_ + 43 base62 chars, so the
            # 16-char display prefix must never contain the whole token.
            token = "agno_pat_" + (name.replace("-", "") + str(self._next_id) + "x" * 40)[:43]
            account = {
                "id": "sa-" + str(self._next_id),
                "name": name,
                "principal": "sa:" + name,
                "token_prefix": token[:16],
                "scopes": [s["scope"] for s in requested_scopes]
                if requested_scopes is not None
                else ["agents:run", "teams:run", "workflows:run", "sessions:read"],
                "created_at": 1780000000,
                "expires_at": None if body.get("never_expires") else 1790000000,
                "last_used_at": None,
                "revoked_at": None,
                "created_by": None,
                "token": token,
            }
            self._next_id += 1
            self.accounts[name] = account
            return httpx.Response(201, json=self._account_response(account, include_token=True))

        if path == "/service-accounts" and method == "GET":
            if not self._is_admin(request):
                return httpx.Response(401, json={"detail": "Invalid authentication token"})
            data = [self._account_response(a) for a in self.accounts.values()]
            return httpx.Response(
                200,
                json={"data": data, "meta": {"page": 1, "limit": 100, "total_pages": 1, "total_count": len(data)}},
            )

        if path.startswith("/service-accounts/") and method == "DELETE":
            if not self._is_admin(request):
                return httpx.Response(401, json={"detail": "Invalid authentication token"})
            account_id = path.rsplit("/", 1)[1]
            for account in self.accounts.values():
                if account["id"] == account_id:
                    account["revoked_at"] = 1780000001
                    return httpx.Response(204)
            return httpx.Response(404, json={"detail": "Service account not found"})

        if path == "/mcp":
            if not self.mcp_enabled:
                return httpx.Response(404, json={"detail": "Not Found"})
            if self.mcp_requires_token and self.auth_mode != "none":
                token = self._bearer(request)
                if token != self.security_key and token not in self.active_tokens():
                    return httpx.Response(401, json={"detail": "Invalid authentication token"})
            message = json.loads(request.content) if request.content else {}
            rpc_method = message.get("method")
            if rpc_method == "initialize":
                return self._jsonrpc_response(
                    {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "result": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "FakeAgentOS", "version": self.agno_version},
                        },
                    },
                    headers={"mcp-session-id": "fake-session-1"},
                )
            if rpc_method == "notifications/initialized":
                return httpx.Response(202)
            if rpc_method == "tools/list":
                return self._jsonrpc_response(
                    {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "result": {"tools": [{"name": name} for name in self.mcp_tools]},
                    }
                )
            return self._jsonrpc_response(
                {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32601, "message": "Method not found"}}
            )

        return httpx.Response(404, json={"detail": "Not Found"})


@pytest.fixture
def fake_os(monkeypatch: pytest.MonkeyPatch) -> FakeAgentOS:
    """A security-key-mode fake AgentOS wired into every CLI HTTP client."""
    fake = FakeAgentOS()
    install_fake(monkeypatch, fake)
    return fake


def install_fake(monkeypatch: pytest.MonkeyPatch, fake: FakeAgentOS) -> None:
    import agnoctl.http as http_module

    monkeypatch.setattr(http_module, "_transport_override", fake.transport())
    # Keep host-machine credentials and URL overrides out of tests.
    for var in ("AGNO_ADMIN_TOKEN", "OS_SECURITY_KEY", "AGENTOS_URL"):
        monkeypatch.delenv(var, raising=False)
