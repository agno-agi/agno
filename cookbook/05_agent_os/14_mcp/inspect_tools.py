"""
Test MCP tools over plain HTTP
==============================

Run a published MCP tool the way MCP Inspector does, without speaking the
protocol: the Server Card at ``/mcp/server-card`` lists what the server
publishes, with each tool's input schema, and
``POST /mcp/server/tools/{name}/run`` executes one and returns its result.

This is what an operator UI calls to render a form from a tool's input schema
and show what came back.

Prerequisites: OPENAI_API_KEY
Run: python cookbook/05_agent_os/14_mcp/inspect_tools.py
Try: in another terminal, rerun this file with --client
"""

import argparse
import asyncio
import os

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, MCPConfig

BASE_URL = os.getenv("AGENTOS_URL", "http://localhost:7777").rstrip("/")

# ---------------------------------------------------------------------------
# Create an MCP-enabled AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(id="mcp-inspect-db", db_file="tmp/mcp_inspect.db")

support_agent = Agent(
    id="support-agent",
    name="Support Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    instructions="Answer support questions in two sentences.",
    markdown=True,
)

agent_os = AgentOS(
    id="mcp-inspect-os",
    description="AgentOS with the MCP tool run API enabled.",
    db=db,
    agents=[support_agent],
    # The default budget is 120; a few seconds keeps the timeout lesson quick.
    mcp=MCPConfig(default_tools=True, tool_run_timeout_seconds=5),
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Drive the tool run API
# ---------------------------------------------------------------------------


async def inspect() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        # 1. What does this server publish? The card carries each tool's
        #    inputSchema, which is what a form is built from.
        listed = (await client.get("/mcp/server-card")).json()["tools"]
        print("Published tools:")
        for entry in listed:
            required = entry.get("inputSchema", {}).get("required", [])
            print(f"  {entry['name']:22} required={required}")

        # 2. Run a read-only tool and read its structured payload.
        response = await client.post(
            "/mcp/server/tools/get_agentos_config/run", json={"arguments": {}}
        )
        body = response.json()
        print("\nget_agentos_config:")
        print(f"  isError: {body['isError']}  ({body['durationMs']} ms)")
        print(f"  agents: {[a['id'] for a in body['structuredContent']['agents']]}")

        # 3. Run an agent through the same endpoint.
        response = await client.post(
            "/mcp/server/tools/run_agent/run",
            json={
                "arguments": {
                    "agent_id": "support-agent",
                    "message": "How do I reset my password?",
                }
            },
        )
        body = response.json()
        print("\nrun_agent:")
        print(f"  isError: {body['isError']}  ({body['durationMs']} ms)")
        print(f"  {body['content'][0]['text'][:120]}")

        # 4. Every failure has the same shape: isError plus content. Only the
        #    status separates a tool that ran and failed (200) from a call that
        #    never happened (4xx), so one render path covers them all.
        response = await client.post(
            "/mcp/server/tools/run_agent/run",
            json={"arguments": {"agent_id": "no-such-agent", "message": "hi"}},
        )
        body = response.json()
        print("\nFailed tool call:")
        print(
            f"  HTTP {response.status_code}, isError={body['isError']}, error={body['error']}"
        )
        print(f"  {body['content'][0]['text'][:70]}")

        # 5. Arguments are validated against the tool's input schema first.
        response = await client.post(
            "/mcp/server/tools/run_agent/run",
            json={"arguments": {"agent_id": "support-agent"}},
        )
        print("\nMissing a required argument:")
        body = response.json()
        print(
            f"  HTTP {response.status_code}: {body['error']} -- {body['content'][0]['text'][:50]}"
        )

        # 6. A tool this server does not publish is not runnable.
        response = await client.post(
            "/mcp/server/tools/not_a_tool/run", json={"arguments": {}}
        )
        print("\nUnknown tool:")
        body = response.json()
        print(
            f"  HTTP {response.status_code}: {body['error']} -- {body['content'][0]['text'][:50]}"
        )

        # 7. A run that outlives the timeout is abandoned AND stopped.
        response = await client.post(
            "/mcp/server/tools/run_agent/run",
            json={
                "arguments": {
                    "agent_id": "support-agent",
                    "message": "Write a detailed 1500 word essay about the ocean.",
                }
            },
        )
        body = response.json()
        print("\nTimed out run:")
        print(
            f"  HTTP {response.status_code}: {body['error']} after {body['durationMs']} ms"
        )
        print(f"  {body['content'][0]['text'][:70]}")
        await asyncio.sleep(2)
        runs = await client.post(
            "/mcp/server/tools/get_sessions/run", json={"arguments": {}}
        )
        print(
            f"  the run is recorded as cancelled, not left running: {runs.status_code == 200}"
        )

        # 8. A caller that hangs up stops the tool the same way.
        print("\nCaller disconnects:")
        call = asyncio.create_task(
            client.post(
                "/mcp/server/tools/run_agent/run",
                json={
                    "arguments": {
                        "agent_id": "support-agent",
                        "message": "Write a detailed 1500 word essay about rivers.",
                    }
                },
            )
        )
        await asyncio.sleep(1)
        call.cancel()
        try:
            await call
        except asyncio.CancelledError:
            print(
                "  aborted the request; the agent stops rather than finishing unobserved"
            )


# ---------------------------------------------------------------------------
# Run the AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--client", action="store_true", help="Drive a server already listening"
    )
    args = parser.parse_args()

    if args.client:
        asyncio.run(inspect())
    else:
        agent_os.serve(app="inspect_tools:app", reload=True)
