"""
Google Workspace Agent — Standalone (No AgentOS)
=================================================

Use gws MCP tools with a plain Agent, no server required.
Good for scripts, notebooks, and quick experiments.

Prerequisites:
    1. Install gws CLI:
        npm install -g @googleworkspace/cli

    2. Authenticate:
        gws auth setup

    3. Set environment variables:
        export OPENAI_API_KEY=your-openai-api-key

Usage:
    .venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_standalone.py
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools


async def main():
    # MCPTools requires async context management for stdio transport
    async with MCPTools(
        command="gws", args=["mcp", "-s", "gmail,drive,calendar"]
    ) as tools:
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            tools=[tools],
            instructions=[
                "You are a helpful Workspace assistant.",
                "Summarize results clearly and concisely.",
            ],
            add_datetime_to_context=True,
            markdown=True,
        )

        # Example queries — uncomment the one you want to try
        agent.print_response("What are my latest 5 emails?")
        # agent.print_response("What meetings do I have today?")
        # agent.print_response("Find documents shared with me this week")


if __name__ == "__main__":
    asyncio.run(main())
