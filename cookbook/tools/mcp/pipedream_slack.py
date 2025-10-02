"""
💬 Pipedream Slack MCP

This example shows how to use Pipedream MCP servers (in this case the Slack one) with Agno Agents.

1. Connect your Pipedream and Slack accounts: https://mcp.pipedream.com/app/slack
2. Get your Pipedream MCP server url: https://mcp.pipedream.com/app/slack
3. Set the MCP_SERVER_URL environment variable to the MCP server url you got above
4. Install dependencies: pip install agno mcp

"""

import asyncio
import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools
from agno.utils.log import log_exception

mcp_server_url = os.getenv("MCP_SERVER_URL")


async def run_agent(task: str) -> None:
    try:
        async with MCPTools(
            url=mcp_server_url, transport="sse", timeout_seconds=20
        ) as mcp:
            agent = Agent(
                model=OpenAIChat(id="gpt-4o-mini"),
                tools=[mcp],
                markdown=True,
            )
            await agent.aprint_response(input=task, stream=True)
    except Exception as e:
        log_exception(f"Unexpected error: {e}")


if __name__ == "__main__":
    # The agent can read channels, users, messages, etc.
    asyncio.run(run_agent("Show me the latest message in the channel #general"))

    # Use your real Slack name for this one to work!
    asyncio.run(
        run_agent("Send a message to <YOUR_NAME> saying 'Hello, I'm your Agno Agent!'")
    )
