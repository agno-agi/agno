"""
Secure and scope an AgentOS MCP server
======================================

Protect ``/mcp`` with an OS security key plus a database-backed ``agno_pat_``
service account. The MCP allow-list sees the PAT principal, only ``core``
built-ins are exposed, localhost host validation is enabled, and run results
use the complete structured form.

Prerequisites: OPENAI_API_KEY and OS_SECURITY_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/secure_mcp.py
Try: In another terminal, rerun this file with --client

At serve time the library warns that ``authorize`` is set while
``AgentOS(authorization=False)``. The warning does not apply to this file:
the service-account verifier populates ``request.state.user_id`` with the PAT
principal, so the allow-list receives ``sa:...`` as intended. Only anonymous
paths (for example the raw security key) reach the gate as ``None`` — which
this lesson deliberately demonstrates as the 401 case.
"""

import argparse
import asyncio
import os
from uuid import uuid4

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPServerConfig
from agno.os.settings import AgnoAPISettings
from fastmcp import Client

# ---------------------------------------------------------------------------
# Create the secured AgentOS
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENTOS_URL", "http://localhost:7777").rstrip("/")
MCP_URL = f"{BASE_URL}/mcp"
OS_SECURITY_KEY = os.environ["OS_SECURITY_KEY"]
SERVICE_ACCOUNT_PREFIX = "secure-mcp-client-"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("MCP_ALLOWED_HOSTS", "").split(",")
    if host.strip()
]
MCP_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "secure-mcp-smoke", "version": "1"},
    },
}
MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

db = SqliteDb(
    id="secure-mcp-db",
    db_file="tmp/secure_mcp.db",
)

secure_agent = Agent(
    id="secure-assistant",
    name="Secure Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer authenticated callers concisely.",
)


def authorize_service_account(user_id: str | None) -> bool:
    """Allow only service accounts minted for this MCP integration."""
    return bool(user_id and user_id.startswith(f"sa:{SERVICE_ACCOUNT_PREFIX}"))


agent_os = AgentOS(
    id="secure-mcp-os",
    description="PAT-authenticated and explicitly scoped AgentOS MCP server.",
    db=db,
    agents=[secure_agent],
    settings=AgnoAPISettings(os_security_key=OS_SECURITY_KEY),
    mcp_server=MCPServerConfig(
        include_tags={"core", "session"},
        exclude_tags={"session"},
        result_mode="full",
        authorize=authorize_service_account,
        allowed_hosts=ALLOWED_HOSTS,
    ),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Mint a PAT through REST, then use it over MCP
# ---------------------------------------------------------------------------


async def run_authenticated_client() -> None:
    account_name = f"{SERVICE_ACCOUNT_PREFIX}{uuid4().hex[:10]}"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as http:
        root_attempt = await http.post(
            "/mcp",
            json=MCP_INITIALIZE,
            headers={
                **MCP_HEADERS,
                "Authorization": f"Bearer {OS_SECURITY_KEY}",
            },
        )
        if root_attempt.status_code != 401:
            raise RuntimeError("The MCP authorize gate accepted the root key")

        bad_host_attempt = await http.post(
            "/mcp",
            json=MCP_INITIALIZE,
            headers={
                **MCP_HEADERS,
                "Authorization": f"Bearer {OS_SECURITY_KEY}",
                "Host": "untrusted.example.com",
            },
        )
        if bad_host_attempt.status_code != 400:
            raise RuntimeError("The MCP host allow-list accepted an untrusted host")

        created = await http.post(
            "/service-accounts",
            json={"name": account_name},
            headers={"Authorization": f"Bearer {OS_SECURITY_KEY}"},
        )
        created.raise_for_status()
        account = created.json()

    token = account["token"]
    if not token.startswith("agno_pat_"):
        raise RuntimeError("Service-account endpoint did not return an agno_pat_ token")

    async with Client(MCP_URL, auth=token, timeout=120) as client:
        tool_names = {tool.name for tool in await client.list_tools()}
        if "get_sessions" in tool_names or "get_session_runs" in tool_names:
            raise RuntimeError("The excluded session tool group is still visible")
        if tool_names != {
            "get_agentos_config",
            "run_agent",
            "run_team",
            "run_workflow",
            "continue_run",
            "cancel_run",
        }:
            raise RuntimeError(f"Unexpected scoped tool surface: {sorted(tool_names)}")

        result = await client.call_tool(
            "run_agent",
            {
                "agent_id": "secure-assistant",
                "message": "Reply with the exact words: authenticated MCP",
            },
        )
        payload = result.structured_content or {}
        if payload.get("status") != "COMPLETED":
            raise RuntimeError(
                f"Expected a completed authenticated run, got {payload.get('status')}"
            )
        if not payload.get("messages"):
            raise RuntimeError(
                "result_mode='full' did not return the full message list"
            )

    print(f"Authenticated principal: {account['principal']}")
    print(f"Token display prefix: {account['token_prefix']}")
    print(f"Root key at /mcp: {root_attempt.status_code}")
    print(f"Untrusted Host at /mcp: {bad_host_attempt.status_code}")
    print(f"Scoped MCP tools: {sorted(tool_names)}")
    print(f"Full run result: {payload['run_id']} -> {payload['status']}")


# ---------------------------------------------------------------------------
# Run Secure MCP AgentOS or its client
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client",
        action="store_true",
        help="Mint a service account and drive the secured MCP server.",
    )
    args = parser.parse_args()

    if args.client:
        asyncio.run(run_authenticated_client())
    else:
        agent_os.serve(app=app)
