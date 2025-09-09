"""
Notion MCP Agent - Manages your documents

This example shows how to use the Agno MCP tools to interact with your Notion workspace.

1. Start by setting up a new internal integration in Notion: https://www.notion.so/profile/integrations
2. Export your new Notion key: `export NOTION_API_KEY=ntn_****`
3. Connect your relevant Notion pages to the integration. To do this, you'll need to visit that page, and click on the 3 dots, and select "Connect to integration".

Dependencies: pip install agno mcp openai

Usage:
  python cookbook/tools/mcp/notion_mcp_agent.py
"""

import asyncio
import json
import os
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters


async def run_agent():
    token = os.getenv("NOTION_API_KEY")
    if not token:
        raise ValueError(
            "Missing Notion API key: provide --NOTION_API_KEY or set NOTION_API_KEY environment variable"
        )

    command = "npx"
    args = ["-y", "@notionhq/notion-mcp-server"]
    env = {
        "OPENAPI_MCP_HEADERS": json.dumps(
            {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"}
        )
    }
    server_params = StdioServerParameters(command=command, args=args, env=env)

    async with MCPTools(server_params=server_params) as mcp_tools:
        agent = Agent(
            name="NotionDocsAgent",
            model=OpenAIChat(id="gpt-4o"),
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


if __name__ == "__main__":
    asyncio.run(run_agent())
