"""
Agent using an MCP tool whose inputSchema contains $defs/$ref.

Before the fix in PR #6085, the $defs container was silently dropped
by format_tools_for_model(), leaving dangling $ref pointers. Claude
would fall back to the wrong anyOf branch or produce malformed args.

Run:
    .venvs/demo/bin/python cookbook/91_tools/mcp/complex_schema/client.py
"""

import asyncio
import sys
from pathlib import Path

from mcp import StdioServerParameters

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools


async def run_agent(message: str) -> None:
    server_script = str(Path(__file__).parent / "server.py")
    # fastmcp CLI lives next to the Python binary in the venv
    fastmcp_bin = str(Path(sys.executable).parent / "fastmcp")
    server_params = StdioServerParameters(
        command=fastmcp_bin,
        args=["run", server_script],
    )
    async with MCPTools(server_params=server_params) as mcp_tools:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-6"),
            tools=[mcp_tools],
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


if __name__ == "__main__":
    asyncio.run(
        run_agent("Get telemetry for device sensor-42 from 2024-01-01 to 2024-01-31")
    )
