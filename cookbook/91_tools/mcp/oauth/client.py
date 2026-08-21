"""Agno agent connecting to an OAuth-protected MCP server via OAuthConfig.

`MCPTools(oauth=...)` performs OIDC discovery from the MCP server's
protected-resource metadata, fetches a `client_credentials` access token, and
injects `Authorization: Bearer <token>` on every request — all transparently.

Defaults match the preconfigured client (`mcp-client` / `mcp-client-secret`) in
the Keycloak realm at `~/code/tools/keycloak`. Override via env vars to point
at any other OIDC provider:

    MCP_URL              MCP server URL (e.g. https://api.example.com/mcp)
    OAUTH_CLIENT_ID      client_credentials client ID
    OAUTH_CLIENT_SECRET  client_credentials client secret

Prerequisites:
    1. OIDC provider running and reachable
    2. Protected MCP server running:
         .venvs/demo/bin/python cookbook/91_tools/mcp/oauth/server.py
    3. OPENAI_API_KEY set (the agent uses an OpenAI model)
"""

import asyncio
import os

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools, OAuthConfig

MCP_URL = os.environ.get("MCP_URL", "http://localhost:9000/mcp")
CLIENT_ID = os.environ.get("OAUTH_CLIENT_ID", "mcp-client")
CLIENT_SECRET = os.environ.get("OAUTH_CLIENT_SECRET", "mcp-client-secret")


async def main():
    async with MCPTools(
        url=MCP_URL,
        transport="streamable-http",
        oauth=OAuthConfig(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        ),
    ) as mcp_tools:
        agent = Agent(
            model=OpenAIResponses(id="gpt-5.4"),
            tools=[mcp_tools],
            markdown=False,
        )
        await agent.aprint_response(
            "Fetch the secret data using the get_secret_data tool."
        )


if __name__ == "__main__":
    asyncio.run(main())
