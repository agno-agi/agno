"""
Regression tests for GitHub Issue #7427:
Gemini client thread-safety fix.

The fix removes per-response cleanup blocks in base.py that were
closing and nulling self.client, causing race conditions under
concurrent load.

Tests verify:
1. Shared client is reused (not recreated per request)
2. User-injected clients are preserved unchanged
3. No cleanup/close after each response
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest


class TestGeminiSharedClient:
    """Test that Gemini uses a shared client across requests."""

    def test_same_client_reused_across_calls(self):
        """Same Gemini instance returns the same client on repeated calls."""
        from agno.models.google import Gemini

        model = Gemini(api_key="test-key")

        with patch("agno.models.google.gemini.genai.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            first = model.get_client()
            second = model.get_client()
            third = model.get_client()

            assert first is second is third
            mock_cls.assert_called_once()

    def test_client_shared_across_threads(self):
        """All threads get the same client instance (SDK is thread-safe)."""
        from agno.models.google import Gemini

        model = Gemini(api_key="test-key")

        with patch("agno.models.google.gemini.genai.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            def get_client_id(_):
                return id(model.get_client())

            with ThreadPoolExecutor(max_workers=4) as pool:
                client_ids = set(pool.map(get_client_id, range(8)))

            # All threads should get the same client
            assert len(client_ids) == 1
            mock_cls.assert_called_once()


class TestGeminiUserInjectedClient:
    """Test that user-injected clients are preserved."""

    def test_user_injected_client_is_preserved(self):
        """User-provided client= is returned unchanged."""
        from agno.models.google import Gemini

        injected = MagicMock()
        model = Gemini(client=injected)

        with patch("agno.models.google.gemini.genai.Client") as mock_cls:
            result = model.get_client()

            assert result is injected
            mock_cls.assert_not_called()

    def test_user_injected_client_shared_across_threads(self):
        """User-injected client is shared (user's responsibility)."""
        from agno.models.google import Gemini

        injected = MagicMock()
        model = Gemini(client=injected)

        def get_client_id(_):
            return id(model.get_client())

        with ThreadPoolExecutor(max_workers=4) as pool:
            client_ids = set(pool.map(get_client_id, range(4)))

        assert len(client_ids) == 1
        assert client_ids.pop() == id(injected)


class TestGeminiNoCleanupAfterResponse:
    """Test that clients are not closed after responses.

    The bug was that base.py had `finally` blocks that called
    self.client.close() and set self.client = None after each
    Gemini response, causing race conditions.
    """

    def test_client_persists_after_get_client(self):
        """Client should persist on self.client after creation."""
        from agno.models.google import Gemini

        model = Gemini(api_key="test-key")

        with patch("agno.models.google.gemini.genai.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            model.get_client()

            # Client should be cached on self.client
            assert model.client is mock_client
