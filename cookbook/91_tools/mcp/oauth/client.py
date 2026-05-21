"""Agent with MCPTools using native OAuth2.1 client_credentials flow.

This example shows how to connect an Agno agent to an OAuth-protected MCP server
without any manual token management.

Prerequisites:
    1. Start the server:   .venvs/demo/bin/python cookbook/91_tools/mcp/oauth/server.py
    2. Run this client:    .venvs/demo/bin/python cookbook/91_tools/mcp/oauth/client.py

The OAuthConfig instructs MCPTools to:
    1. Perform OIDC discovery on the MCP server URL
    2. Acquire a client_credentials access token
    3. Inject Authorization: Bearer <token> on every request
    4. Refresh the token transparently when it expires
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools, OAuthConfig


async def main():
    oauth_config = OAuthConfig(
        client_id="demo-client-id",
        client_secret="demo-client-secret",
    )

    async with MCPTools(
        url="http://localhost:8000/mcp",
        transport="streamable-http",
        oauth=oauth_config,
    ) as mcp_tools:
        print(f"Connected. Available tools: {list(mcp_tools.functions.keys())}")

        agent = Agent(
            model=OpenAIResponses(id="gpt-5.4"),
            tools=[mcp_tools],
            markdown=False,
        )

        await agent.aprint_response("Fetch the secret data using the get_secret_data tool.")


if __name__ == "__main__":
    asyncio.run(main())
