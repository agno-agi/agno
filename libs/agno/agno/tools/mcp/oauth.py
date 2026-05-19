from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


@dataclass
class OAuthConfig:
    """OAuth2.1 client credentials configuration for MCPTools.

    Enables native M2M authentication against OAuth-protected MCP servers
    without external token management.
    """

    client_id: str
    client_secret: str
    scopes: Optional[str] = None
    token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = field(
        default="client_secret_basic"
    )


class InMemoryTokenStorage:
    """In-memory implementation of the MCP SDK TokenStorage protocol.

    Tokens are cached for the lifetime of the MCPTools instance.
    The ClientCredentialsOAuthProvider handles refresh automatically.
    """

    def __init__(self) -> None:
        self._tokens: Optional["OAuthToken"] = None
        self._client_info: Optional["OAuthClientInformationFull"] = None

    async def get_tokens(self) -> Optional["OAuthToken"]:
        return self._tokens

    async def set_tokens(self, tokens: "OAuthToken") -> None:
        self._tokens = tokens

    async def get_client_info(self) -> Optional["OAuthClientInformationFull"]:
        return self._client_info

    async def set_client_info(self, client_info: "OAuthClientInformationFull") -> None:
        self._client_info = client_info


def create_oauth_provider(config: OAuthConfig, server_url: str) -> "ClientCredentialsOAuthProvider":
    """Create a ClientCredentialsOAuthProvider from an OAuthConfig.

    Internal factory — not part of the public API.
    """
    from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider

    storage = InMemoryTokenStorage()
    return ClientCredentialsOAuthProvider(
        server_url=server_url,
        storage=storage,
        client_id=config.client_id,
        client_secret=config.client_secret,
        token_endpoint_auth_method=config.token_endpoint_auth_method,
        scopes=config.scopes,
    )
