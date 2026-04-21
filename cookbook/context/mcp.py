"""
MCP Context Provider
====================

Wrap any MCP server as a context provider. This example uses the public
`sequential-thinking` MCP server over stdio.

Run: pip install openai mcp
Requires: `npx` on PATH (Node.js)
Env: OPENAI_API_KEY
"""

import asyncio

from agno.agent import Agent
from agno.context.mcp import MCPContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Build Provider
# ---------------------------------------------------------------------------
provider = MCPContextProvider(
    id="sequential-thinking",
    name="Sequential Thinking",
    command="npx -y @modelcontextprotocol/server-sequential-thinking",
)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
async def main() -> None:
    print("Status:", provider.status())

    tools = provider.get_tools()
    mcp_tools = tools[0]

    async with mcp_tools:
        agent = Agent(
            model=OpenAIResponses(id="gpt-5.4"),
            tools=[mcp_tools],
            instructions=[
                "You reason step by step using the sequential-thinking MCP server.",
                provider.instructions(),
            ],
            markdown=True,
        )
        await agent.aprint_response(
            "Plan a one-week roadmap for rolling out a new feature flag.",
            stream=True,
        )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
