import asyncio
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters

async def run_agent(message: str) -> None:
    """Run the filesystem agent with the given message."""

    # MCP server to access the filesystem (via `npx`)
    async with MCPTools("http://0.0.0.0:7071/runtime/webhooks/mcp/sse", transport="sse") as mcp_tools:
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            tools=[mcp_tools],
            instructions=dedent("""\
            You are a financial analysis agent.

            Analyze a company's income statement, balance sheet, cash flow, and earnings.
            Generate a concise report summarizing the company's financial overview.
            """),
            markdown=True,
            show_tool_calls=True,
        )

        # Run the agent
        await agent.aprint_response(message, stream=True)

if __name__ == "__main__":
    asyncio.run(run_agent("Create a financial overview of the following company just with cash flow and balance sheet: IBM."))