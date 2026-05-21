# mcp/oauth

Demonstrates native OAuth2.1 `client_credentials` authentication for `MCPTools`.

## Overview

`MCPTools` now accepts an `oauth` parameter. When provided, it internally creates
a `ClientCredentialsOAuthProvider` (from the MCP Python SDK) and handles OIDC
discovery, token acquisition, caching, and refresh automatically.

## Usage

```python
from agno.tools.mcp import MCPTools, OAuthConfig

async with MCPTools(
    url="http://your-mcp-server/mcp",
    transport="streamable-http",
    oauth=OAuthConfig(
        client_id="your-client-id",
        client_secret="your-client-secret",
        # scopes="read write",  # optional
    ),
) as mcp_tools:
    agent = Agent(tools=[mcp_tools], ...)
```

## Running the example

```bash
# Terminal 1 — start the mock server
.venvs/demo/bin/python cookbook/91_tools/mcp/oauth/server.py

# Terminal 2 — run the agent
.venvs/demo/bin/python cookbook/91_tools/mcp/oauth/client.py
```
