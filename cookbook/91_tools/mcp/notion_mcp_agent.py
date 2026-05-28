"""
Notion MCP Agent - Manages your documents

This example uses the official Notion MCP server (`@notionhq/notion-mcp-server`)
over stdio with an integration token.

Setup:
1. Create an internal integration in Notion: https://www.notion.so/profile/integrations
2. Export the integration token: `export NOTION_TOKEN=ntn_****`
3. Connect the pages you want the agent to access: open each page, click the "..." menu,
   and select "Connect to integration".

Dependencies: uv pip install agno mcp openai

Usage:
  python cookbook/91_tools/mcp/notion_mcp_agent.py
"""

import asyncio
import os
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


async def run_agent():
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("Missing Notion integration token: set NOTION_TOKEN=ntn_****")

    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@notionhq/notion-mcp-server"],
        env={"NOTION_TOKEN": token},
    )

    async with MCPTools(server_params=server_params) as mcp_tools:
        agent = Agent(
            name="NotionDocsAgent",
            model=OpenAIResponses(id="gpt-5.4"),
            tools=[mcp_tools],
            description="Agent to query and modify Notion docs via MCP",
            instructions=dedent("""\
                You have access to Notion documents through MCP tools.
                - Use tools to read, search, or update pages.
                - Confirm with the user before making modifications.
            """),
            markdown=True,
        )

        await agent.acli_app(
            input="You are a helpful assistant that can access Notion workspaces and pages.",
            stream=True,
            markdown=True,
            exit_on=["exit", "quit"],
        )


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_agent())
