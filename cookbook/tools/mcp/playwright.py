import asyncio
import os

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters


async def run_agent(message: str) -> None:
    server_params = StdioServerParameters(
        command="npx",
        args=[
            "@playwright/mcp@latest",
        ],
    )

    async with MCPTools(
        server_params=server_params, include_tools=["browser_navigate", "browser_click"]
    ) as mcp_tools:
        agent = Agent(
            model=Claude(id="claude-3-7-sonnet-latest"),
            tools=[mcp_tools],
            role="Your task is to use your web browsing capabilities to find information and take actions on the web.",
            markdown=True,
            exponential_backoff=True,
            compress_context=True,
            tool_calls_compression_threshold=3,
            debug_mode=True,
        )

        await agent.aprint_response(input=message, stream=True)


if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "Look for a personality test with less than 10 questions on the web and take it. Summarize the results of the test and provide a link to the test you took.",
        )
    )
