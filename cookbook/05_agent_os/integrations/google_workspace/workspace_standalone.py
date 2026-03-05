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
        export GOOGLE_WORKSPACE_CLI_CLIENT_ID=your-client-id
        export GOOGLE_WORKSPACE_CLI_CLIENT_SECRET=your-client-secret

Usage:
    .venvs/demo/bin/python cookbook/05_agent_os/integrations/google_workspace/workspace_standalone.py
"""

import asyncio
import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools

# Pass relevant env vars to the gws MCP subprocess.
# GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE lets gws find stored OAuth tokens.
GWS_ENV = {
    k: v
    for k, v in os.environ.items()
    if k.startswith("GOOGLE_WORKSPACE_CLI_") or k in ("HOME", "PATH", "USER")
}

# Common instructions for all gws-based agents.
# gws tools accept a 'params' object for path and query parameters.
GWS_INSTRUCTIONS = [
    "All gws tools accept a 'params' object for path/query parameters.",
    "For Gmail, always pass params={'userId': 'me'} to refer to the authenticated user.",
    "For Calendar, always pass params={'calendarId': 'primary'} for the main calendar.",
    "To list messages: gmail_users_messages_list(params={'userId': 'me', 'maxResults': 5})",
    "To get a message: gmail_users_messages_get(params={'userId': 'me', 'id': '<messageId>', 'format': 'metadata', 'metadataHeaders': ['From', 'Subject', 'Date']})",
    "Always use format='metadata' when reading messages to keep responses small.",
]


async def main():
    # MCPTools requires async context management for stdio transport.
    # Use include_tools to limit which tools are registered (keeps context small).
    async with MCPTools(
        command="gws mcp -s gmail",
        env=GWS_ENV,
        include_tools=[
            "gmail_users_messages_list",
            "gmail_users_messages_get",
            "gmail_users_labels_list",
        ],
    ) as tools:
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            tools=[tools],
            instructions=[
                "You are a helpful Workspace assistant.",
                *GWS_INSTRUCTIONS,
                "Summarize results clearly and concisely.",
            ],
            add_datetime_to_context=True,
            markdown=True,
        )

        # Example queries — uncomment the one you want to try
        await agent.aprint_response("What are my latest 5 emails?")
        # await agent.aprint_response("What meetings do I have today?")
        # await agent.aprint_response("Find documents shared with me this week")


if __name__ == "__main__":
    asyncio.run(main())
