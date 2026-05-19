import pytest


# ---------------------------------------------------------------------------
# InMemoryTokenStorage tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_in_memory_token_storage_tokens_start_none():
    from agno.tools.mcp.oauth import InMemoryTokenStorage
    storage = InMemoryTokenStorage()
    assert await storage.get_tokens() is None


@pytest.mark.asyncio
async def test_in_memory_token_storage_roundtrip_tokens():
    from agno.tools.mcp.oauth import InMemoryTokenStorage
    from mcp.shared.auth import OAuthToken
    storage = InMemoryTokenStorage()
    token = OAuthToken(access_token="tok", token_type="bearer")
    await storage.set_tokens(token)
    result = await storage.get_tokens()
    assert result is not None
    assert result.access_token == "tok"


@pytest.mark.asyncio
async def test_in_memory_token_storage_client_info_starts_none():
    from agno.tools.mcp.oauth import InMemoryTokenStorage
    storage = InMemoryTokenStorage()
    assert await storage.get_client_info() is None


@pytest.mark.asyncio
async def test_in_memory_token_storage_roundtrip_client_info():
    from agno.tools.mcp.oauth import InMemoryTokenStorage
    from mcp.shared.auth import OAuthClientInformationFull
    storage = InMemoryTokenStorage()
    info = OAuthClientInformationFull(client_id="cid", client_secret="sec", redirect_uris=None)
    await storage.set_client_info(info)
    result = await storage.get_client_info()
    assert result is not None
    assert result.client_id == "cid"


# ---------------------------------------------------------------------------
# OAuthConfig tests
# ---------------------------------------------------------------------------

def test_oauth_config_defaults():
    from agno.tools.mcp.oauth import OAuthConfig
    cfg = OAuthConfig(client_id="id", client_secret="secret")
    assert cfg.client_id == "id"
    assert cfg.client_secret == "secret"
    assert cfg.scopes is None
    assert cfg.token_endpoint_auth_method == "client_secret_basic"


def test_oauth_config_custom_values():
    from agno.tools.mcp.oauth import OAuthConfig
    cfg = OAuthConfig(
        client_id="id",
        client_secret="secret",
        scopes="read write",
        token_endpoint_auth_method="client_secret_post",
    )
    assert cfg.scopes == "read write"
    assert cfg.token_endpoint_auth_method == "client_secret_post"


# ---------------------------------------------------------------------------
# create_oauth_provider tests
# ---------------------------------------------------------------------------

def test_create_oauth_provider_returns_provider():
    from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
    from agno.tools.mcp.oauth import OAuthConfig, create_oauth_provider
    cfg = OAuthConfig(client_id="cid", client_secret="secret")
    provider = create_oauth_provider(cfg, "http://localhost:8000/mcp")
    assert isinstance(provider, ClientCredentialsOAuthProvider)
