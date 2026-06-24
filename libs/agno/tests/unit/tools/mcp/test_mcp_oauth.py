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
    from mcp.shared.auth import OAuthToken

    from agno.tools.mcp.oauth import InMemoryTokenStorage

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
    from mcp.shared.auth import OAuthClientInformationFull

    from agno.tools.mcp.oauth import InMemoryTokenStorage

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


# ---------------------------------------------------------------------------
# MCPTools oauth parameter tests
# ---------------------------------------------------------------------------


def test_mcptools_oauth_raises_for_stdio():
    import pytest

    from agno.tools.mcp import MCPTools
    from agno.tools.mcp.oauth import OAuthConfig

    with pytest.raises(ValueError, match="oauth.*stdio"):
        MCPTools(
            command="npx -y @modelcontextprotocol/server-everything",
            transport="stdio",
            oauth=OAuthConfig(client_id="id", client_secret="secret"),
        )


def test_mcptools_oauth_warns_when_session_provided(caplog):
    import logging
    from unittest.mock import MagicMock

    from agno.tools.mcp import MCPTools
    from agno.tools.mcp.oauth import OAuthConfig

    # Agno's logger has propagate=False, so pytest's caplog cannot see its
    # records. Capture warnings via a dedicated handler attached to "agno".
    records: list[logging.LogRecord] = []

    class _Recorder(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    # Other tests may switch the active agno logger via use_team_logger /
    # use_workflow_logger. Attach to every known agno logger to be safe.
    agno_loggers = [
        logging.getLogger("agno"),
        logging.getLogger("agno-team"),
        logging.getLogger("agno-workflow"),
    ]
    handler = _Recorder(level=logging.WARNING)
    for lg in agno_loggers:
        lg.addHandler(handler)
    try:
        mock_session = MagicMock()
        mcp = MCPTools(
            url="http://localhost:8000/mcp",
            transport="streamable-http",
            session=mock_session,
            oauth=OAuthConfig(client_id="id", client_secret="secret"),
        )
    finally:
        for lg in agno_loggers:
            lg.removeHandler(handler)

    assert mcp._oauth_provider is None
    assert any("oauth" in r.getMessage().lower() for r in records)


@pytest.mark.asyncio
async def test_mcptools_connect_passes_auth_to_streamable_http():
    from unittest.mock import AsyncMock, patch

    from agno.tools.mcp import MCPTools
    from agno.tools.mcp.oauth import OAuthConfig

    mcp = MCPTools(
        url="http://localhost:8000/mcp",
        transport="streamable-http",
        oauth=OAuthConfig(client_id="id", client_secret="secret"),
    )

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()

    mock_read = AsyncMock()
    mock_write = AsyncMock()

    mock_transport_ctx = AsyncMock()
    mock_transport_ctx.__aenter__ = AsyncMock(return_value=(mock_read, mock_write, None))
    mock_transport_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("agno.tools.mcp.mcp.streamablehttp_client", return_value=mock_transport_ctx) as mock_http,
        patch("agno.tools.mcp.mcp.ClientSession", return_value=mock_session_ctx),
        patch.object(mcp, "initialize", new_callable=AsyncMock),
    ):
        await mcp._connect()

    call_kwargs = mock_http.call_args.kwargs
    assert "auth" in call_kwargs
    assert call_kwargs["auth"] is not None


@pytest.mark.asyncio
async def test_mcptools_connect_passes_auth_to_sse():
    from unittest.mock import AsyncMock, patch

    from agno.tools.mcp import MCPTools
    from agno.tools.mcp.oauth import OAuthConfig

    mcp = MCPTools(
        url="http://localhost:8000/mcp",
        transport="sse",
        oauth=OAuthConfig(client_id="id", client_secret="secret"),
    )

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()

    mock_read = AsyncMock()
    mock_write = AsyncMock()

    mock_transport_ctx = AsyncMock()
    mock_transport_ctx.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
    mock_transport_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("agno.tools.mcp.mcp.sse_client", return_value=mock_transport_ctx) as mock_sse,
        patch("agno.tools.mcp.mcp.ClientSession", return_value=mock_session_ctx),
        patch.object(mcp, "initialize", new_callable=AsyncMock),
    ):
        await mcp._connect()

    call_kwargs = mock_sse.call_args.kwargs
    assert "auth" in call_kwargs
    assert call_kwargs["auth"] is not None


@pytest.mark.asyncio
async def test_mcptools_get_session_for_run_passes_auth_with_header_provider():
    """Coexistence: when both oauth and header_provider are configured,
    the per-run session creation in get_session_for_run() must still pass
    auth=self._oauth_provider to the transport client."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from agno.tools.mcp import MCPTools
    from agno.tools.mcp.oauth import OAuthConfig

    def headers():
        return {"X-Custom": "value"}

    mcp = MCPTools(
        url="http://localhost:8000/mcp",
        transport="streamable-http",
        oauth=OAuthConfig(client_id="id", client_secret="secret"),
        header_provider=headers,
    )
    # Pre-seed the provider as _connect would have done
    sentinel = MagicMock(name="oauth_provider_sentinel")
    mcp._oauth_provider = sentinel

    # Build a mocked transport context
    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session.list_tools = AsyncMock(return_value=MagicMock(tools=[]))

    mock_read = AsyncMock()
    mock_write = AsyncMock()

    mock_transport_ctx = AsyncMock()
    mock_transport_ctx.__aenter__ = AsyncMock(return_value=(mock_read, mock_write, None))
    mock_transport_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    run_context = MagicMock()
    run_context.run_id = "test-run-id"

    with (
        patch("agno.tools.mcp.mcp.streamablehttp_client", return_value=mock_transport_ctx) as mock_http,
        patch("agno.tools.mcp.mcp.ClientSession", return_value=mock_session_ctx),
    ):
        try:
            await mcp.get_session_for_run(run_context=run_context, agent=MagicMock())
        except Exception:
            # We only care that the transport was called with auth=
            pass

    assert mock_http.called, "streamablehttp_client should have been called"
    call_kwargs = mock_http.call_args.kwargs
    assert "auth" in call_kwargs
    assert call_kwargs["auth"] is sentinel
