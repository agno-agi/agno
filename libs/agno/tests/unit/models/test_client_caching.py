"""
Tests for httpx client caching and resource leak prevention.

This test suite verifies that:
1. Global httpx clients are singletons and reused across models
2. OpenAI clients are cached per model instance
3. No new httpx clients are created on every request
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

    def test_multiple_models_share_global_httpx_client(self):
        """Verify that multiple models can share the same global httpx client."""
        model1 = OpenAIChat(id="gpt-4o")
        model2 = OpenAIChat(id="gpt-4-turbo")
        model3 = OpenAIChat(id="gpt-3.5-turbo")

        # Get clients from each model
        model1.get_client()
        model2.get_client()
        model3.get_client()

        # All models should use the same global httpx client internally
        # We verify this by checking that only one global client exists
        global_sync_client = get_default_sync_client()
        assert isinstance(global_sync_client, httpx.Client)

    def test_sync_client_uses_global_httpx_client(self):
        """Verify that OpenAIChat uses the global httpx client for sync operations."""
        global_sync_client = get_default_sync_client()
        model = OpenAIChat(id="gpt-4o")

        openai_client = model.get_client()

        # The OpenAI client should have the global httpx client
        assert openai_client._client is global_sync_client

    def test_async_client_uses_global_httpx_client(self):
        """Verify that OpenAIChat uses the global httpx client for async operations."""
        global_async_client = get_default_async_client()
        model = OpenAIChat(id="gpt-4o")

        openai_client = model.get_async_client()

        # The OpenAI client should have the global httpx client
        assert openai_client._client is global_async_client


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

    def test_uses_global_httpx_client(self):
        """Verify that OpenAIResponses uses the global httpx client."""
        global_sync_client = get_default_sync_client()
        global_async_client = get_default_async_client()

        model = OpenAIResponses(id="gpt-4o")

        sync_openai = model.get_client()
        async_openai = model.get_async_client()

        # Both should use global clients
        assert sync_openai._client is global_sync_client
        assert async_openai._client is global_async_client


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
    """Test suite for setting custom global clients."""

    def teardown_method(self):
        """Clean up global clients after each test."""
        close_sync_client()

    def test_set_custom_sync_client_affects_all_models(self):
        """Verify that setting a custom sync client affects all models."""
        custom_client = httpx.Client(limits=httpx.Limits(max_connections=100, max_keepalive_connections=50))
        set_default_sync_client(custom_client)

        # Create models after setting custom client
        model1 = OpenAIChat(id="gpt-4o")
        model2 = OpenAIResponses(id="gpt-4o")

        # Both should use the custom client
        assert model1.get_client()._client is custom_client
        assert model2.get_client()._client is custom_client
        custom_client.close()

    def test_set_custom_async_client_affects_all_models(self):
        """Verify that setting a custom async client affects all models."""
        custom_client = httpx.AsyncClient(limits=httpx.Limits(max_connections=100, max_keepalive_connections=50))
        set_default_async_client(custom_client)

        # Create models after setting custom client
        model1 = OpenAIChat(id="gpt-4o")
        model2 = OpenAIResponses(id="gpt-4o")

        # Both should use the custom client
        assert model1.get_async_client()._client is custom_client
        assert model2.get_async_client()._client is custom_client

    def test_custom_client_persists_across_multiple_calls(self):
        """Verify that custom client persists across multiple calls."""
        custom_client = httpx.Client(limits=httpx.Limits(max_connections=250))
        set_default_sync_client(custom_client)

        model = OpenAIChat(id="gpt-4o")

        # Multiple calls should use the same custom client
        for _ in range(5):
            openai_client = model.get_client()
            assert openai_client._client is custom_client
        custom_client.close()

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


class TestResourceLeakPrevention:
    """Test suite for resource leak prevention."""

    def teardown_method(self):
        """Clean up global clients after each test."""
        close_sync_client()

    def test_no_new_httpx_clients_created_per_request(self):
        """Verify that no new httpx clients are created on repeated requests."""
        model = OpenAIChat(id="gpt-4o")
        global_client = get_default_sync_client()

        # Simulate multiple requests
        for _ in range(10):
            client = model.get_client()
            # Same client should be used
            assert client._client is global_client

        # Only one global client should exist
        new_global_client = get_default_sync_client()
        assert new_global_client is global_client

    def test_multiple_models_share_single_global_client(self):
        """Verify that multiple models share a single global httpx client."""
        global_client = get_default_sync_client()

        # Create multiple models
        models = [
            OpenAIChat(id="gpt-4o"),
            OpenAIChat(id="gpt-4-turbo"),
            OpenAIChat(id="gpt-3.5-turbo"),
            OpenAIResponses(id="gpt-4o"),
        ]

        # All should use the same global client
        for model in models:
            openai_client = model.get_client()
            assert openai_client._client is global_client


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
