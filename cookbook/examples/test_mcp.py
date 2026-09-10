"""Local HTTP/MCP integration: real JWT validation, schema injection and storage.
Run with either brain's dev environment. The model boundary is stubbed explicitly.
"""

import importlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["second_brain", "team_brain"])
async def test_verified_mcp_identity(name, tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    monkeypatch.setenv("JWT_VERIFICATION_KEY", public)
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(Path(__file__).parent / name))
    sys.modules.pop(name, None)
    module = importlib.import_module(name)
    app = module.app
    seen = []

    async def stub_model_run(message, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(get_content_as_string=lambda: "model stub")

    component = module.second_brain if name == "second_brain" else module.librarian
    monkeypatch.setattr(component, "arun", stub_model_run)
    headers = {"Accept": "application/json, text/event-stream"}

    def token(user):
        return jwt.encode(
            {
                "sub": user,
                "aud": module.agent_os.id,
                "scopes": ["agents:run"],
                "iat": int(time.time()),
                "exp": int(time.time()) + 120,
            },
            key,
            algorithm="RS256",
        )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            initialize = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "examples-test", "version": "1"},
                },
            }
            assert (
                await client.post("/mcp", json=initialize, headers=headers)
            ).status_code == 401
            assert (
                await client.post(
                    "/mcp",
                    json=initialize,
                    headers={**headers, "Authorization": "Bearer invalid"},
                )
            ).status_code == 401
            for user in ["alice", "bob"]:
                auth = {**headers, "Authorization": "Bearer " + token(user)}
                response = await client.post("/mcp", json=initialize, headers=auth)
                assert response.status_code == 200, response.text
                if response.headers.get("mcp-session-id"):
                    auth["mcp-session-id"] = response.headers["mcp-session-id"]
                await client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    headers=auth,
                )

                async def rpc(method, params=None):
                    response = await client.post(
                        "/mcp",
                        json={
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": method,
                            "params": params or {},
                        },
                        headers=auth,
                    )
                    assert response.status_code == 200, response.text
                    if response.headers.get("content-type", "").startswith(
                        "text/event-stream"
                    ):
                        return json.loads(
                            next(
                                line[6:]
                                for line in response.text.splitlines()
                                if line.startswith("data: ")
                            )
                        )
                    return response.json()

                listing = await rpc("tools/list")
                tools = {tool["name"]: tool for tool in listing["result"]["tools"]}
                expected = (
                    {"ask_second_brain"}
                    if name == "second_brain"
                    else {"remember", "recall"}
                )
                assert set(tools) == expected
                assert all(
                    "user_id" not in tool["inputSchema"].get("properties", {})
                    for tool in tools.values()
                )
                tool = "ask_second_brain" if name == "second_brain" else "remember"
                arguments = (
                    {"message": "Remember Harbor"}
                    if name == "second_brain"
                    else {
                        "project": "Harbor",
                        "decision": "checklist",
                        "reasoning": "maintenance",
                    }
                )
                result = await rpc("tools/call", {"name": tool, "arguments": arguments})
                assert not result.get("error") and not result["result"].get(
                    "isError"
                ), result
                spoofed = await rpc(
                    "tools/call",
                    {"name": tool, "arguments": {**arguments, "user_id": "mallory"}},
                )
                # Hidden identity arguments are rejected by the MCP schema.
                assert spoofed.get("error") or spoofed["result"].get("isError"), spoofed
                unauthorized = await client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": tool, "arguments": arguments},
                    },
                    headers=headers,
                )
                assert unauthorized.status_code == 401
                if name == "team_brain":
                    recalled = await rpc(
                        "tools/call",
                        {
                            "name": "recall",
                            "arguments": {"question": "Who decided, and why?"},
                        },
                    )
                    assert not recalled["result"].get("isError"), recalled
            assert {run["user_id"] for run in seen} == {"alice", "bob"}
            if name == "team_brain":
                records = [
                    json.loads(line)
                    for line in module.fs.read(module.DECISION_LOG).splitlines()
                ]
                assert len(records) == 2
                assert {record["author"] for record in records} == {"alice", "bob"}
                assert all(record["author"] != "mallory" for record in records)
            else:
                assert {run["user_id"] for run in seen} == {"alice", "bob"}
                assert len({run["session_id"] for run in seen}) == len(seen)
