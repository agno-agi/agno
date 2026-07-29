"""
Drive the AgentOS MCP run lifecycle
===================================

Use a protocol-level FastMCP client to discover the eight built-in tools,
pause and continue one agent run, cancel a second paused run, and read the
continued session back.

Prerequisites: basic.py must be listening on http://localhost:7777
Run: .venvs/demo/bin/python cookbook/05_agent_os/14_mcp/mcp_client.py
Try: set AGENTOS_MCP_URL when the server uses another origin
"""

import asyncio
import os
from typing import Any

from fastmcp import Client

# ---------------------------------------------------------------------------
# Create the MCP client flow
# ---------------------------------------------------------------------------

MCP_URL = os.getenv("AGENTOS_MCP_URL", "http://localhost:7777/mcp")
AGENT_ID = "operations-agent"
EXPECTED_TOOLS = {
    "get_agentos_config",
    "run_agent",
    "run_team",
    "run_workflow",
    "continue_run",
    "cancel_run",
    "get_sessions",
    "get_session_runs",
}


def result_payload(result: Any) -> Any:
    """Return a FastMCP result's structured payload."""
    structured = result.structured_content or {}
    return structured.get("result", structured)


def confirmed(requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve every confirmation requirement returned by a paused run."""
    for requirement in requirements:
        requirement["confirmation"] = True
        tool_execution = requirement.get("tool_execution")
        if isinstance(tool_execution, dict):
            tool_execution["confirmed"] = True
    return requirements


async def pause_run(client: Client, service: str) -> dict[str, Any]:
    result = await client.call_tool(
        "run_agent",
        {
            "agent_id": AGENT_ID,
            "message": f"Restart the {service} service.",
        },
    )
    payload = result_payload(result)
    if payload.get("status") != "PAUSED":
        raise RuntimeError(f"Expected a PAUSED run, got {payload.get('status')}")
    if not payload.get("requirements"):
        raise RuntimeError("The paused run returned no requirements")
    return payload


async def main() -> None:
    async with Client(MCP_URL, timeout=120) as client:
        tools = {tool.name for tool in await client.list_tools()}
        if tools != EXPECTED_TOOLS:
            raise RuntimeError(f"Unexpected MCP tool surface: {sorted(tools)}")

        config = result_payload(await client.call_tool("get_agentos_config", {}))
        agent_ids = {agent["id"] for agent in config["agents"]}
        if AGENT_ID not in agent_ids:
            raise RuntimeError(f"{AGENT_ID} is missing from get_agentos_config")

        paused = await pause_run(client, "billing")
        continued_result = await client.call_tool(
            "continue_run",
            {
                "run_id": paused["run_id"],
                "session_id": paused["session_id"],
                "agent_id": AGENT_ID,
                "requirements": confirmed(paused["requirements"]),
            },
        )
        continued = result_payload(continued_result)
        if continued.get("status") != "COMPLETED":
            raise RuntimeError(
                f"Expected a COMPLETED run, got {continued.get('status')}"
            )
        continued_text = str(continued_result.content).lower()
        if "restarted" not in continued_text or "rejected" in continued_text:
            raise RuntimeError("continue_run did not execute the confirmed tool")

        cancelled = await pause_run(client, "inventory")
        cancel_result = await client.call_tool(
            "cancel_run",
            {
                "run_id": cancelled["run_id"],
                "session_id": cancelled["session_id"],
                "agent_id": AGENT_ID,
            },
        )
        if "cancellation requested" not in str(cancel_result.content).lower():
            raise RuntimeError("cancel_run did not acknowledge the request")

        history = result_payload(
            await client.call_tool(
                "get_session_runs",
                {"session_id": continued["session_id"]},
            )
        )
        if not history:
            raise RuntimeError("get_session_runs returned no persisted history")

    print(f"Discovered tools: {len(tools)}")
    print(f"Continued run: {continued['run_id']} -> {continued['status']}")
    print(f"Cancelled run: {cancelled['run_id']}")
    print(f"Persisted runs in continued session: {len(history)}")


# ---------------------------------------------------------------------------
# Run the MCP client
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())
