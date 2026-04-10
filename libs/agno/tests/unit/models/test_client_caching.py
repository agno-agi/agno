"""
Tests for httpx client caching and resource leak prevention.

This test suite verifies that:
1. Global httpx clients are singletons and reused across non-OpenAI models
2. OpenAI models do NOT use the global httpx client (they use the SDK's own HTTP/1.1 default)
3. OpenAI clients are cached per model instance to prevent resource leaks
4. Custom http_client is respected when explicitly provided
"""

import os

import httpx
import pytest

# Set test API key to avoid env var lookup errors
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.models.openai.chat import OpenAIChat
from agno.models.openai.responses import OpenAIResponses
from agno.utils.http import (
    aclose_default_clients,
    close_sync_client,
    get_default_async_client,
    get_default_sync_client,
    set_default_async_client,
    set_default_sync_client,
)


class TestGlobalHttpxClients:
    """Test suite for global httpx client singleton pattern."""

    def teardown_method(self):
        """Clean up global clients after each test."""
        close_sync_client()

    @pytest.mark.asyncio
    async def test_sync_client_is_singleton(self):
        """Verify that the global sync httpx client is a singleton."""
        client1 = get_default_sync_client()
        client2 = get_default_sync_client()

        assert client1 is client2, "Sync clients should be the same instance"
        assert isinstance(client1, httpx.Client)

    @pytest.mark.asyncio
    async def test_async_client_is_singleton(self):
        """Verify that the global async httpx client is a singleton."""
        client1 = get_default_async_client()
        client2 = get_default_async_client()

        assert client1 is client2, "Async clients should be the same instance"
        assert isinstance(client1, httpx.AsyncClient)

    def test_sync_and_async_clients_are_different(self):
        """Verify that sync and async clients are different instances."""
        sync_client = get_default_sync_client()
        async_client = get_default_async_client()

        assert sync_client is not async_client, "Sync and async clients should be different"

    def test_closed_sync_client_gets_recreated(self):
        """Verify that closed sync client gets recreated."""
        client1 = get_default_sync_client()
        client1.close()

        client2 = get_default_sync_client()

        # Should create a new client when the previous one is closed
        assert client1 is not client2
        assert isinstance(client2, httpx.Client)

    @pytest.mark.asyncio
    async def test_closed_async_client_gets_recreated(self):
        """Verify that closed async client gets recreated."""
        client1 = get_default_async_client()
        await client1.aclose()

        client2 = get_default_async_client()

        # Should create a new client when the previous one is closed
        assert client1 is not client2
        assert isinstance(client2, httpx.AsyncClient)


class TestOpenAIChatClientCaching:
    """Test suite for OpenAIChat client caching."""

    def teardown_method(self):
        """Clean up global clients after each test."""
        close_sync_client()

    def test_sync_client_is_cached(self):
        """Verify that OpenAIChat caches the sync client."""
        model = OpenAIChat(id="gpt-4o")

        client1 = model.get_client()
        client2 = model.get_client()

        assert client1 is client2, "OpenAI sync clients should be cached"
        assert model.client is not None
        assert model.client is client1

    def test_async_client_is_cached(self):
        """Verify that OpenAIChat caches the async client."""
        model = OpenAIChat(id="gpt-4o")

        client1 = model.get_async_client()
        client2 = model.get_async_client()

        assert client1 is client2, "OpenAI async clients should be cached"
        assert model.async_client is not None
        assert model.async_client is client1

    def test_sync_client_does_not_use_global_httpx_client(self):
        """Verify that OpenAIChat does NOT use the global shared httpx client.

        OpenAI's infrastructure has issues with HTTP/2. The SDK intentionally defaults
        to HTTP/1.1. We must not inject the shared HTTP/2 client.
        """
        global_sync_client = get_default_sync_client()
        model = OpenAIChat(id="gpt-4o")

        openai_client = model.get_client()

        # The OpenAI client must NOT have the global httpx client
        assert openai_client._client is not global_sync_client

    def test_async_client_does_not_use_global_httpx_client(self):
        """Verify that OpenAIChat does NOT use the global shared httpx client for async.

        The global async client uses HTTP/2 which causes transient 400 errors with OpenAI.
        """
        global_async_client = get_default_async_client()
        model = OpenAIChat(id="gpt-4o")

        openai_client = model.get_async_client()

        # The OpenAI client must NOT have the global httpx client
        assert openai_client._client is not global_async_client

    def test_each_model_instance_has_own_cached_client(self):
        """Verify that each OpenAIChat instance caches its own client independently."""
        model1 = OpenAIChat(id="gpt-4o")
        model2 = OpenAIChat(id="gpt-4-turbo")

        client1 = model1.get_client()
        client2 = model2.get_client()

        # Each model has its own cached OpenAI client
        assert model1.client is client1
        assert model2.client is client2
        # But they are different OpenAI client instances
        assert client1 is not client2


class TestOpenAIResponsesClientCaching:
    """Test suite for OpenAIResponses client caching."""

    def teardown_method(self):
        """Clean up global clients after each test."""
        close_sync_client()

    def test_sync_client_is_cached(self):
        """Verify that OpenAIResponses caches the sync client."""
        model = OpenAIResponses(id="gpt-4o")

        client1 = model.get_client()
        client2 = model.get_client()

        assert client1 is client2, "OpenAI sync clients should be cached"
        assert model.client is not None
        assert model.client is client1

    def test_async_client_is_cached(self):
        """Verify that OpenAIResponses caches the async client."""
        model = OpenAIResponses(id="gpt-4o")

        client1 = model.get_async_client()
        client2 = model.get_async_client()

        assert client1 is client2, "OpenAI async clients should be cached"
        assert model.async_client is not None
        assert model.async_client is client1

    def test_does_not_use_global_httpx_client(self):
        """Verify that OpenAIResponses does NOT use the global shared httpx client."""
        global_sync_client = get_default_sync_client()
        global_async_client = get_default_async_client()

        model = OpenAIResponses(id="gpt-4o")

        sync_openai = model.get_client()
        async_openai = model.get_async_client()

        # Neither should use global clients
        assert sync_openai._client is not global_sync_client
        assert async_openai._client is not global_async_client


class TestCustomHttpClient:
    """Test suite for custom httpx client support."""

    def teardown_method(self):
        """Clean up global clients after each test."""
        close_sync_client()

    def test_custom_sync_client_is_respected(self):
        """Verify that custom sync httpx client is used when provided."""
        custom_client = httpx.Client()
        model = OpenAIChat(id="gpt-4o", http_client=custom_client)

        openai_client = model.get_client()

        # Should use the custom client
        assert openai_client._client is custom_client
        custom_client.close()

    def test_custom_async_client_is_respected(self):
        """Verify that custom async httpx client is used when provided."""
        custom_client = httpx.AsyncClient()
        model = OpenAIChat(id="gpt-4o", http_client=custom_client)

        openai_client = model.get_async_client()

        # Should use the custom client
        assert openai_client._client is custom_client

    def test_custom_sync_client_respected_on_responses(self):
        """Verify that custom sync httpx client is used on OpenAIResponses."""
        custom_client = httpx.Client()
        model = OpenAIResponses(id="gpt-4o", http_client=custom_client)

        openai_client = model.get_client()

        assert openai_client._client is custom_client
        custom_client.close()

    def test_custom_async_client_respected_on_responses(self):
        """Verify that custom async httpx client is used on OpenAIResponses."""
        custom_client = httpx.AsyncClient()
        model = OpenAIResponses(id="gpt-4o", http_client=custom_client)

        openai_client = model.get_async_client()

        assert openai_client._client is custom_client


class TestAsyncCleanup:
    """Test suite for async cleanup functionality."""

    @pytest.mark.asyncio
    async def test_aclose_default_clients_closes_both(self):
        """Verify that aclose_default_clients closes both sync and async clients."""
        sync_client = get_default_sync_client()
        async_client = get_default_async_client()

        assert not sync_client.is_closed
        assert not async_client.is_closed

        # Close both clients
        await aclose_default_clients()

        assert sync_client.is_closed
        assert async_client.is_closed

    @pytest.mark.asyncio
    async def test_clients_recreated_after_async_close(self):
        """Verify that clients are recreated after async close."""
        sync_client1 = get_default_sync_client()
        async_client1 = get_default_async_client()

        await aclose_default_clients()

        # Should get new clients
        sync_client2 = get_default_sync_client()
        async_client2 = get_default_async_client()

        assert sync_client1 is not sync_client2
        assert async_client1 is not async_client2


class TestSetGlobalClients:
    """Test suite for setting custom global clients.

    Note: set_default_sync_client/set_default_async_client affect non-OpenAI providers
    (Anthropic, Groq, etc.) that use the global shared httpx client. OpenAI models
    do not use the global client, so these settings do not affect them.
    """

    def teardown_method(self):
        """Clean up global clients after each test."""
        close_sync_client()

    def test_set_client_overrides_previous_default(self):
        """Verify that setting a new client replaces the previous default."""
        # Get default client
        default_client = get_default_sync_client()

        # Set custom client
        custom_client = httpx.Client(limits=httpx.Limits(max_connections=100))
        set_default_sync_client(custom_client)

        # New calls should get custom client
        new_client = get_default_sync_client()
        assert new_client is custom_client
        assert new_client is not default_client

        custom_client.close()

    def test_set_custom_sync_client_retrievable(self):
        """Verify that a custom sync client set globally is returned by get_default_sync_client."""
        custom_client = httpx.Client(limits=httpx.Limits(max_connections=100, max_keepalive_connections=50))
        set_default_sync_client(custom_client)

        retrieved = get_default_sync_client()
        assert retrieved is custom_client
        custom_client.close()

    def test_set_custom_async_client_retrievable(self):
        """Verify that a custom async client set globally is returned by get_default_async_client."""
        custom_client = httpx.AsyncClient(limits=httpx.Limits(max_connections=100, max_keepalive_connections=50))
        set_default_async_client(custom_client)

        retrieved = get_default_async_client()
        assert retrieved is custom_client

    def test_openai_models_ignore_global_client_override(self):
        """Verify that OpenAI models do NOT pick up globally set httpx clients.

        This is the key behavioral change: OpenAI models let the SDK manage its own
        HTTP client to avoid HTTP/2-related transient errors.
        """
        custom_sync = httpx.Client(limits=httpx.Limits(max_connections=100))
        custom_async = httpx.AsyncClient(limits=httpx.Limits(max_connections=100))
        set_default_sync_client(custom_sync)
        set_default_async_client(custom_async)

        model = OpenAIChat(id="gpt-4o")

        # OpenAI models should NOT use the global client
        assert model.get_client()._client is not custom_sync
        assert model.get_async_client()._client is not custom_async

        custom_sync.close()


class TestResourceLeakPrevention:
    """Test suite for resource leak prevention."""

    def teardown_method(self):
        """Clean up global clients after each test."""
        close_sync_client()

    def test_no_new_openai_clients_created_per_request(self):
        """Verify that repeated get_client() calls return the same cached OpenAI client."""
        model = OpenAIChat(id="gpt-4o")

        first_client = model.get_client()
        # Simulate multiple requests
        for _ in range(10):
            client = model.get_client()
            assert client is first_client, "Same cached OpenAI client should be returned"

    def test_no_new_openai_async_clients_created_per_request(self):
        """Verify that repeated get_async_client() calls return the same cached OpenAI client."""
        model = OpenAIChat(id="gpt-4o")

        first_client = model.get_async_client()
        for _ in range(10):
            client = model.get_async_client()
            assert client is first_client, "Same cached async OpenAI client should be returned"

    def test_responses_model_caches_across_calls(self):
        """Verify that OpenAIResponses also caches clients across repeated calls."""
        model = OpenAIResponses(id="gpt-4o")

        first_sync = model.get_client()
        first_async = model.get_async_client()

        for _ in range(10):
            assert model.get_client() is first_sync
            assert model.get_async_client() is first_async

    def test_global_httpx_client_singleton_unchanged(self):
        """Verify the global httpx client remains a singleton for non-OpenAI providers."""
        global_client = get_default_sync_client()

        # Multiple retrievals return the same instance
        for _ in range(10):
            assert get_default_sync_client() is global_client


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
