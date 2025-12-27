"""
🔒 Using Pipedream MCP servers with authentication

This is an example of how to use Pipedream MCP servers with authentication.
This is useful if your app is interfacing with the MCP servers in behalf of your users.

1. Get your access token. You can check how in Pipedream's docs: https://pipedream.com/docs/connect/mcp/developers/
2. Get the URL of the MCP server. It will look like this: https://remote.mcp.pipedream.net/<External user id>/<MCP app slug>
3. Set the environment variables:
    - MCP_SERVER_URL: The URL of the MCP server you previously got
    - MCP_ACCESS_TOKEN: The access token you previously got
    - PIPEDREAM_PROJECT_ID: The project id of the Pipedream project you want to use
    - PIPEDREAM_ENVIRONMENT: The environment of the Pipedream project you want to use
3. Install dependencies: pip install agno mcp
"""

import asyncio
from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools, StreamableHTTPClientParams
from agno.utils.log import log_exception

mcp_server_url = getenv("MCP_SERVER_URL")
mcp_access_token = getenv("MCP_ACCESS_TOKEN")
pipedream_project_id = getenv("PIPEDREAM_PROJECT_ID")
pipedream_environment = getenv("PIPEDREAM_ENVIRONMENT")


server_params = StreamableHTTPClientParams(
    url=mcp_server_url,
    headers={
        "Authorization": f"Bearer {mcp_access_token}",
        "x-pd-project-id": pipedream_project_id,
        "x-pd-environment": pipedream_environment,
    },
)


async def run_agent(task: str) -> None:
    try:
        async with MCPTools(
            server_params=server_params, transport="streamable-http", timeout_seconds=20
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
