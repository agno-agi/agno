"""
Web Context Provider — keyless Exa MCP backend
==============================================

Expose the web as a queryable context via Exa's public MCP server.
No Exa key required (rate-limited); passing `api_key` raises the ceiling.

Run: pip install openai mcp
Env: OPENAI_API_KEY
"""

import asyncio

from agno.agent import Agent
from agno.context.web import WebContextProvider
from agno.context.web.exa_mcp import ExaMCPBackend
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Build Provider
# ---------------------------------------------------------------------------
backend = ExaMCPBackend()  # Optional: ExaMCPBackend(api_key="...")
provider = WebContextProvider(backend=backend)


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
                "You are a research agent.",
                provider.instructions(),
            ],
            markdown=True,
        )
        await agent.aprint_response(
            "What is the Model Context Protocol? Cite one source URL.",
            stream=True,
        )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
