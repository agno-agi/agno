"""Tool defaults and protocol-era compatibility through the full AgentOS HTTP app."""

import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import jwt
import pytest

pytest.importorskip("fastmcp")

import fastmcp  # noqa: E402

from agno.agent import Agent  # noqa: E402
from agno.os import AgentOS, MCPConfig  # noqa: E402
from agno.os.config import AuthorizationConfig  # noqa: E402
from agno.os.settings import AgnoAPISettings  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
KEY = "mcp-protocol-test-signing-key-at-least-32-bytes"
DEFAULT_TOOLS = {
    "get_agentos_config",
    "run_agent",
    "run_team",
    "run_workflow",
    "continue_run",
    "cancel_run",
    "get_sessions",
    "get_session_runs",
}


def _auth(user_id):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {"sub": user_id, "scopes": ["agent_os:admin"], "exp": int(time.time()) + 60}, KEY, algorithm="HS256"
        )
    }


def _body(response):
    if "text/event-stream" in response.headers.get("content-type", ""):
        messages = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        return next(message for message in messages if "result" in message or "error" in message)
    return response.json()


async def _rpc(client, version, method, params=None, headers=None):
    params = dict(params or {})
    request_headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": version,
        **(headers or {}),
    }
    if version == MODERN:
        params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": MODERN,
            "io.modelcontextprotocol/clientCapabilities": {},
            "io.modelcontextprotocol/clientInfo": {"name": "agno-test", "version": "1"},
        }
        request_headers["Mcp-Method"] = method
        if "name" in params:
            request_headers["Mcp-Name"] = params["name"]
    return await client.post(
        "/mcp", headers=request_headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    )


@pytest.fixture(autouse=True)
def _transport_settings(monkeypatch):
    monkeypatch.setattr(fastmcp.settings, "stateless_http", False)
    for name in ("JWT_VERIFICATION_KEY", "JWT_JWKS_FILE", "OS_SECURITY_KEY"):
        monkeypatch.delenv(name, raising=False)


@asynccontextmanager
async def _client(config, *, authenticated=False):
    agent = Agent(id="docs", telemetry=False)
    os = AgentOS(
        id="mcp-protocol-test",
        agents=[agent],
        mcp=config,
        settings=AgnoAPISettings(os_security_key=None),
        authorization=authenticated,
        authorization_config=AuthorizationConfig(verification_keys=[KEY], algorithm="HS256", verify_audience=False)
        if authenticated
        else None,
        telemetry=False,
    )
    app = os.get_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost", follow_redirects=True
        ) as client:
            yield client


@pytest.mark.parametrize("version", [MODERN, LEGACY])
@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize(
    "surface,stateless", [("plain", False), ("default", False), ("default", True), ("custom", False), ("custom", True)]
)
async def test_protocol_versions_preserve_tool_surface_and_identity(version, authenticated, surface, stateless):
    calls = []

    def echo(message: str, user_id: Optional[str] = None) -> str:
        """Echo the message with the caller identity injected by AgentOS."""
        calls.append(user_id)
        return message

    if surface == "plain":
        config = True
    elif surface == "default":
        config = MCPConfig(default_tools=True, stateless=stateless)
    else:
        config = MCPConfig(tools=[echo], stateless=stateless)
    async with _client(config, authenticated=authenticated) as client:
        headers = _auth("alice") if authenticated else {}
        if version == MODERN:
            response = await _rpc(client, version, "server/discover", headers=headers)
            assert response.status_code == 200, response.text
            assert MODERN in _body(response)["result"]["supportedVersions"]
            assert "mcp-session-id" not in response.headers
        else:
            response = await _rpc(
                client,
                version,
                "initialize",
                {"protocolVersion": LEGACY, "capabilities": {}, "clientInfo": {"name": "agno-test", "version": "1"}},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            assert _body(response)["result"]["protocolVersion"] == LEGACY
            assert ("mcp-session-id" in response.headers) is (not stateless)
            if "mcp-session-id" in response.headers:
                headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
            initialized = await client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": LEGACY, **headers},
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            assert initialized.status_code == 202

        response = await _rpc(client, version, "tools/list", headers=headers)
        assert response.status_code == 200, response.text
        result = _body(response)["result"]
        assert {tool["name"] for tool in result["tools"]} == ({"echo"} if surface == "custom" else DEFAULT_TOOLS)
        if version == MODERN:
            assert result["resultType"] == "complete"
            assert result["ttlMs"] == 0
            assert result["cacheScope"] == "private"
        params = (
            {"name": "echo", "arguments": {"message": "hello"}}
            if surface == "custom"
            else {"name": "get_agentos_config", "arguments": {}}
        )
        response = await _rpc(client, version, "tools/call", params, headers)
        assert response.status_code == 200, response.text
        assert not _body(response)["result"].get("isError", False)
        if surface == "custom":
            assert _body(response)["result"]["content"][0]["text"] == "hello"
            assert calls == ["alice" if authenticated else None]
        if authenticated:
            # An existing protocol session must never bypass per-request authentication.
            session_only = {key: value for key, value in headers.items() if key != "Authorization"}
            assert (await _rpc(client, version, "tools/call", params, session_only)).status_code == 401
            assert (
                await _rpc(client, version, "tools/call", params, {**session_only, "Authorization": "Bearer invalid"})
            ).status_code == 401


@pytest.mark.parametrize("method_header", [None, "tools/call"])
async def test_modern_method_headers_are_validated_before_dispatch(method_header):
    async with _client(True) as client:
        headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": MODERN}
        if method_header is not None:
            headers["Mcp-Method"] = method_header
        response = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": MODERN,
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                },
            },
        )
        assert response.status_code == 400
        assert _body(response)["error"]["code"] == -32020


@pytest.mark.parametrize(
    "config", [True, MCPConfig(default_tools=True), MCPConfig(default_tools=True, stateless=False)]
)
async def test_fastmcp_stateless_setting_is_preserved_for_legacy_clients(monkeypatch, config):
    monkeypatch.setattr(fastmcp.settings, "stateless_http", True)
    async with _client(config) as client:
        response = await _rpc(
            client,
            LEGACY,
            "initialize",
            {"protocolVersion": LEGACY, "capabilities": {}, "clientInfo": {"name": "agno-test", "version": "1"}},
        )
        assert response.status_code == 200, response.text
        assert "mcp-session-id" not in response.headers


async def test_modern_disconnect_cancels_the_exposed_agent_stream(monkeypatch):
    """Drive ASGI directly so a disconnect is delivered while the run is in flight."""
    started = asyncio.Event()
    stopped = asyncio.Event()
    agent = Agent(id="slow-agent", telemetry=False)

    async def arun(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
            yield RunOutput(content="unreachable")
        finally:
            stopped.set()

    async def resolve(*args, **kwargs):
        return agent

    monkeypatch.setattr(agent, "arun", arun)
    monkeypatch.setattr("agno.os.mcp._resolve_run_component", resolve)
    os = AgentOS(agents=[agent], mcp=MCPConfig(tools=[agent]), telemetry=False)
    app = os.get_app()
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "slow-agent",
            "arguments": {"message": "wait"},
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": MODERN,
                "io.modelcontextprotocol/clientCapabilities": {},
                "progressToken": "run-progress",
            },
        },
    }
    incoming = asyncio.Queue()
    await incoming.put({"type": "http.request", "body": json.dumps(request).encode(), "more_body": False})
    sent = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "root_path": "",
        "query_string": b"",
        "server": ("localhost", 80),
        "client": ("127.0.0.1", 1234),
        "headers": [
            (b"host", b"localhost"),
            (b"content-type", b"application/json"),
            (b"accept", b"application/json, text/event-stream"),
            (b"mcp-protocol-version", MODERN.encode()),
            (b"mcp-method", b"tools/call"),
            (b"mcp-name", b"slow-agent"),
        ],
    }
    async with app.router.lifespan_context(app):
        task = asyncio.create_task(app(scope, incoming.get, send))
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            await incoming.put({"type": "http.disconnect"})
            await asyncio.wait_for(stopped.wait(), timeout=5)
            await asyncio.wait_for(task, timeout=5)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert any(message.get("status") == 200 for message in sent)
    assert any(b"notifications/progress" in message.get("body", b"") for message in sent)
