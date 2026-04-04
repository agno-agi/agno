"""
MCP tools example with GitHub Copilot.

This example uses Agno's MCPTools to connect to MCP servers.
For a simple local test, you can use the filesystem MCP server.

Prerequisites:
1. Install SDK: pip install github-copilot-sdk
2. Install Copilot CLI (separate installation)
3. Authenticate: copilot auth login
4. Install Node.js for npx-based MCP servers

Run: .venvs/demo/bin/python cookbook/90_models/copilot/mcp_tools.py
"""

import asyncio

from agno.agent import Agent
from agno.models.copilot_sdk import CopilotChat
from agno.tools.mcp import MCPTools


async def run_agent():
    # Connect to a local filesystem MCP server
    # This gives the agent access to read files in the /tmp directory
    async with MCPTools(
        transport="stdio",
        command="npx",
        args=[
            "-y",
            "@modelcontextprotocol/server-filesystem",
            "/tmp",
        ],
    ) as mcp_tools:
        agent = Agent(
            model=CopilotChat(id="claude-sonnet-4-5"),
            tools=[mcp_tools],
            markdown=True,
        )

        await agent.aprint_response(
            "List the files in the /tmp directory and tell me about any interesting ones",
            stream=True,
        )


if __name__ == "__main__":
    asyncio.run(run_agent())
