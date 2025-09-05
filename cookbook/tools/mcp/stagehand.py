"""
🤖 Stagehand MCP Agent - Hacker News Reader's Digest

This example demonstrates how to use Agno's agent to create a Hacker News content using the Stagehand MCP server.

Features:
- Scrapes current Hacker News headlines and metadata
- Extracts top comments from popular stories
- Creates a structured digest with key insights
- Respects rate limits and community guidelines

Prerequisites:
- Clone the Stagehand MCP server: git clone https://github.com/browserbase/mcp-server-browserbase
- Build the Stagehand MCP server: cd mcp-server-browserbase/stagehand && npm install && npm run build
  - This will create a dist/index.js file in the location where you cloned the repository
- Install dependencies: pip install agno mcp
- Set environment variables: BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID, OPENAI_API_KEY
- Run this example: python cookbook/tools/mcp/stagehand.py
"""

import asyncio
from os import environ
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters


async def run_agent(message: str) -> None:
    server_params = StdioServerParameters(
        command="node",
        # Update this path to the location where you cloned the repository
        args=["mcp-server-browserbase/stagehand/dist/index.js"],
        env=environ.copy(),
    )

    async with MCPTools(server_params=server_params, timeout_seconds=60) as mcp_tools:
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            tools=[mcp_tools],
            instructions=dedent("""\
                You are a web scraping assistant that creates concise reader's digests from Hacker News.

                CRITICAL INITIALIZATION RULES - FOLLOW EXACTLY:
                1. NEVER use screenshot tool until AFTER successful navigation
                2. ALWAYS start with stagehand_navigate first
                3. Wait for navigation success message before any other actions
                4. If you see initialization errors, restart with navigation only
                5. Use stagehand_observe and stagehand_extract to explore pages safely

                Available tools and safe usage order:
                - stagehand_navigate: Use FIRST to initialize browser
                - stagehand_extract: Use to extract structured data from pages
                - stagehand_observe: Use to find elements and understand page structure
                - stagehand_act: Use to click links and navigate to comments
                - screenshot: Use ONLY after navigation succeeds and page loads

                Your goal is to create a comprehensive but concise digest that includes:
                - Top headlines with brief summaries
                - Key themes and trends
                - Notable comments and insights
                - Overall tech news landscape overview

                Be methodical, extract structured data, and provide valuable insights.
            """),
            markdown=True,
        )
        await agent.aprint_response(message, stream=True)


if __name__ == "__main__":
    asyncio.run(
        run_agent(
            "Create a comprehensive Hacker News Reader's Digest from https://news.ycombinator.com"
        )
    )
