"""
📔 MCP Graphiti Agent - A personal diary assistant

This example demonstrates how to use Agno's MCP integration together with Graphiti, to build a personal diary assistant.

- Run your Graphiti MCP server. Full instructions: https://github.com/getzep/graphiti/tree/main/mcp_server
- Run: `pip install agno mcp openai` to install the dependencies
"""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools

mcp_server_url = "http://localhost:8000/sse"


async def run_agent(message: str) -> None:
    async with MCPTools(url=mcp_server_url, transport="sse") as mcp_tools:
        agent = Agent(
            tools=[mcp_tools],
            model=OpenAIChat(id="o3-mini"),
            instructions=dedent(
                """
                You are an assistant with access to tools related to Graphiti's knowledge graph capabilities.
                You maintain a diary for the user.
                Your job is to help them add new entries and use the diary data to answer their questions.
                """
            ),
        )
        await agent.aprint_response(message, stream=True)


if __name__ == "__main__":
    asyncio.run(
        # Using the agent to add new entries to the diary
        run_agent(
            "Add the following entry to the diary: 'Today I spent some time building agents with Agno'"
        )
    )

    asyncio.run(
        # Using the agent to answer questions about the diary
        run_agent("What have I been building recently?")
    )
