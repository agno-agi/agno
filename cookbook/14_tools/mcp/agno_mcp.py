import asyncio

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools


async def run_agent(message: str) -> None:
    async with MCPTools(
        transport="streamable-http", url="https://docs.agno.com/mcp"
    ) as agno_mcp_server:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-0"),
            tools=[agno_mcp_server],
            markdown=True,
        )
        await agent.aprint_response(input=message, stream=True)


if __name__ == "__main__":
    asyncio.run(run_agent("What is Agno?"))
