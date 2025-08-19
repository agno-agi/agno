import asyncio

import agno_os
from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.mcp import MCPTools


async def run_agent_prompt():
    async with MCPTools(
        command="uvx oxylabs-mcp",
        env={
            "OXYLABS_USERNAME": agno_os.getenv("OXYLABS_USERNAME"),
            "OXYLABS_PASSWORD": agno_os.getenv("OXYLABS_PASSWORD"),
        },
    ) as server:
        agent = Agent(
            model=Gemini(api_key=agno_os.getenv("GEMINI_API_KEY")),
            tools=[server],
            instructions=["Use MCP tools to fulfill the requests"],
            markdown=True,
        )
        await agent.aprint_response(
            "Go to oxylabs.io, look for career page, "
            "go to it and return all job titles in markdown format. "
            "Don't invent URLs, start from one provided."
        )


if __name__ == "__main__":
    asyncio.run(run_agent_prompt())
