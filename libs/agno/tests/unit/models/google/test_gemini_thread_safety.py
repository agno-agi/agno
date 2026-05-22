from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from agno.models.google import Gemini


class TestGeminiSharedClient:
    """Tests verifying Gemini client is shared and reused across calls."""

    def test_same_client_reused_across_calls(self):
        """Verify the same client instance is returned on repeated get_client() calls."""
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
        """Verify concurrent threads receive the same client instance."""
        model = Gemini(api_key="test-key")

        with patch("agno.models.google.gemini.genai.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            def get_client_id(_):
                return id(model.get_client())

            with ThreadPoolExecutor(max_workers=4) as pool:
                client_ids = set(pool.map(get_client_id, range(8)))

            assert len(client_ids) == 1
            mock_cls.assert_called_once()


class TestGeminiUserInjectedClient:
    """Tests verifying user-injected clients are preserved and not overwritten."""

    def test_user_injected_client_is_preserved(self):
        """Verify a user-provided client is used instead of creating a new one."""
        injected = MagicMock()
        model = Gemini(client=injected)

        with patch("agno.models.google.gemini.genai.Client") as mock_cls:
            result = model.get_client()

            assert result is injected
            mock_cls.assert_not_called()

    def test_user_injected_client_shared_across_threads(self):
        """Verify user-injected client is shared across concurrent threads."""
        injected = MagicMock()
        model = Gemini(client=injected)

        def get_client_id(_):
            return id(model.get_client())

        with ThreadPoolExecutor(max_workers=4) as pool:
            client_ids = set(pool.map(get_client_id, range(4)))

        assert len(client_ids) == 1
        assert client_ids.pop() == id(injected)


class TestGeminiNoCleanupAfterResponse:
    """Tests verifying client is not closed/cleared after responses."""

    def test_client_persists_after_get_client(self):
        """Verify client remains set on model after get_client() call."""
        model = Gemini(api_key="test-key")

        with patch("agno.models.google.gemini.genai.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            model.get_client()

            assert model.client is mock_client
