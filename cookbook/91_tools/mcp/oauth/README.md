# mcp/oauth

Native OAuth2.1 `client_credentials` authentication for `MCPTools` against a
real OAuth-protected MCP server.

## How it works

- **`server.py`** — FastMCP server protected by `RemoteAuthProvider` +
  `JWTVerifier`. It validates incoming bearer tokens against an external OIDC
  provider's JWKS endpoint and advertises that provider via
  protected-resource metadata.
- **`client.py`** — Agno agent using `MCPTools(oauth=OAuthConfig(...))`. The
  MCP SDK's `ClientCredentialsOAuthProvider` discovers the authorization
  server from the protected-resource metadata, fetches an access token via
  `client_credentials`, and injects `Authorization: Bearer <token>` on every
  request.

## Requirements

Any standards-compliant OIDC provider (Keycloak, Auth0, Okta, Authentik,
Zitadel, ...) configured with:

- A `client_credentials`-capable client (confidential client with service
  accounts / machine-to-machine grant enabled).
- An `aud` claim on issued access tokens that the MCP server can validate
  against (configure via an audience mapper or scope on most providers).
- A publicly reachable JWKS endpoint (`/.well-known/jwks.json` or the
  provider-specific equivalent) and discovery document.

You will need:

- Issuer URL (e.g. `https://auth.example.com` or `https://.../realms/<name>`)
- JWKS URI
- Expected audience value
- Client ID and client secret

> **Why `RemoteAuthProvider` and not `OIDCProxy`?** FastMCP's `OIDCProxy` is a
> Dynamic Client Registration (DCR) shim in front of providers that don't
> support DCR (Auth0, Okta, Google, Azure) and is designed for the interactive
> `authorization_code` flow. The `client_credentials` grant uses
> pre-registered credentials and never performs DCR, so the lighter
> `RemoteAuthProvider` (JWT validation + protected-resource metadata) is the
> right fit for M2M scenarios regardless of whether the upstream provider
> supports DCR.

## Running

Configure both pieces via environment variables and run them in separate
terminals.

```bash
# server.py — what the MCP server expects
export OIDC_ISSUER="https://auth.example.com"
export OIDC_JWKS_URI="https://auth.example.com/.well-known/jwks.json"
export OIDC_AUDIENCE="mcp-server"
export MCP_BASE_URL="http://localhost:9000"

.venvs/demo/bin/python cookbook/91_tools/mcp/oauth/server.py
```

```bash
# client.py — what the Agno agent uses
export MCP_URL="http://localhost:9000/mcp"
export OAUTH_CLIENT_ID="your-client-id"
export OAUTH_CLIENT_SECRET="your-client-secret"
export OPENAI_API_KEY="sk-..."  # used by the agent's model

.venvs/demo/bin/python cookbook/91_tools/mcp/oauth/client.py
```

## Using it in your own code

```python
from agno.tools.mcp import MCPTools, OAuthConfig

async with MCPTools(
    url="https://your-mcp-server/mcp",
    transport="streamable-http",
    oauth=OAuthConfig(
        client_id="your-client-id",
        client_secret="your-client-secret",
        # scopes="read write",  # optional
    ),
) as mcp_tools:
    agent = Agent(tools=[mcp_tools], ...)
```

> **Note:** `OAuthConfig` currently supports only the `client_credentials`
> (M2M) grant with in-memory token storage. Other grants
> (e.g. `authorization_code`, `private_key_jwt`) and persistent storage may
> be added in future versions.
