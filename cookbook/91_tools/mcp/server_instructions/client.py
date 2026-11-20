"""
MCP Server Instructions
=============================

An MCP server can return `instructions` in its handshake: guidance on how its
tools fit together. MCPTools loads them by default and adds them to the agent's
system prompt, exactly as `instructions` on any other toolkit.

Pass `load_server_instructions=False` to ignore them, or pass your own
`instructions=` to the toolkit, which always takes precedence.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools

SERVER_COMMAND = "python cookbook/91_tools/mcp/server_instructions/server.py"

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent(message: str, load_server_instructions: bool) -> None:
    async with MCPTools(
        SERVER_COMMAND,
        load_server_instructions=load_server_instructions,
    ) as mcp_tools:
        print(f"--- load_server_instructions={load_server_instructions} ---")
        print(f"toolkit instructions: {mcp_tools.instructions!r}")

        agent = Agent(
            model=OpenAIResponses(id="gpt-5.6-luna"),
            tools=[mcp_tools],
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Default: the server's instructions reach the agent, which looks the station up first.
    asyncio.run(
        run_agent("What is the forecast for London?", load_server_instructions=True)
    )

    # Opt out: the agent only sees the tool descriptions.
    asyncio.run(
        run_agent("What is the forecast for London?", load_server_instructions=False)
    )
