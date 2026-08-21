"""OAuth-protected MCP server using FastMCP's RemoteAuthProvider + JWTVerifier.

This is the canonical FastMCP pattern: an external OIDC provider (Keycloak,
Auth0, Okta, Authentik, ...) issues access tokens, and the MCP server validates
each incoming bearer token against the provider's JWKS endpoint. The server
publishes protected-resource metadata pointing at the provider, which is what
the MCP client uses to discover the token endpoint.

Configuration is taken from environment variables so the same script works
against any provider. Defaults match the preconfigured Keycloak realm at
`~/code/tools/keycloak`:

    OIDC_ISSUER     authorization-server issuer URL
    OIDC_JWKS_URI   JWKS endpoint (defaults to issuer + Keycloak path)
    OIDC_AUDIENCE   expected `aud` claim in access tokens
    MCP_BASE_URL    public base URL of this MCP server

Run:
    .venvs/demo/bin/python cookbook/91_tools/mcp/oauth/server.py
"""

import os

from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from pydantic import AnyHttpUrl

ISSUER = os.environ.get("OIDC_ISSUER", "http://localhost:8080/realms/mcp-demo")
JWKS_URI = os.environ.get("OIDC_JWKS_URI", f"{ISSUER}/protocol/openid-connect/certs")
AUDIENCE = os.environ.get("OIDC_AUDIENCE", "mcp-server")
BASE_URL = os.environ.get("MCP_BASE_URL", "http://localhost:9000")

token_verifier = JWTVerifier(
    jwks_uri=JWKS_URI,
    issuer=ISSUER,
    audience=AUDIENCE,
)

auth = RemoteAuthProvider(
    token_verifier=token_verifier,
    authorization_servers=[AnyHttpUrl(ISSUER)],
    base_url=BASE_URL,
)

mcp = FastMCP(name="OAuth Protected Server", auth=auth)


@mcp.tool
async def get_secret_data() -> str:
    """Return sensitive data. Only reachable with a valid bearer token."""
    return "Secret data: the answer is 42"


@mcp.tool
async def ping() -> str:
    """Health check."""
    return "pong"


if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=9000)
