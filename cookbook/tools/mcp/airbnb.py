import asyncio
from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.mcp import MCPTools


async def run_agent(message: str) -> None:
    async with MCPTools(f"npx -y @openbnb/mcp-server-airbnb --ignore-robots-txt") as mcp_tools:
        agent = Agent(
            model=Gemini(id="gemini-2.5-pro-exp-03-25"),
            tools=[mcp_tools],
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)

if __name__ == "__main__":
    asyncio.run(run_agent("What listings are available in San Francisco for 2 people for 3 nights from 1 to 4 August 2025?"))
