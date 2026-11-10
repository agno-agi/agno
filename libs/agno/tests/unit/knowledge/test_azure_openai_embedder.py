"""Unit tests for AzureOpenAIEmbedder input formatting.

Validates that the embedder always sends input as a list to the Azure
OpenAI API, which is required by non-default deployed models (e.g.
Cohere-embed-v3-multilingual).  See: https://github.com/agno-agi/agno/issues/6759
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture()
def _mock_openai():
    """Create and return mocked OpenAI client and response objects for testing AzureOpenAIEmbedder without real credentials."""
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    mock_response.usage = MagicMock()
    mock_response.usage.model_dump.return_value = {"prompt_tokens": 5, "total_tokens": 5}

    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_response

    return mock_client, mock_response


class TestAzureOpenAIEmbedderInputFormat:
    """Ensure input is always sent as a list, not a bare string."""

    def test_response_wraps_input_as_list(self, _mock_openai):
        mock_client, _ = _mock_openai

        from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder

        embedder = AzureOpenAIEmbedder(
            id="text-embedding-3-small",
            api_key="test-key",
            azure_endpoint="https://test.openai.azure.com/",
            openai_client=mock_client,
        )

        embedder.get_embedding("hello world")

        call_kwargs = mock_client.embeddings.create.call_args[1]
        assert isinstance(call_kwargs["input"], list), "input must be a list for Azure API compatibility"
        assert call_kwargs["input"] == ["hello world"]

    def test_response_wraps_input_for_non_default_model(self, _mock_openai):
        mock_client, _ = _mock_openai

        from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder

        embedder = AzureOpenAIEmbedder(
            id="Cohere-embed-v3-multilingual",
            dimensions=1024,
            api_key="test-key",
            azure_endpoint="https://test.openai.azure.com/",
            azure_deployment="Cohere-embed-v3-multilingual",
            openai_client=mock_client,
        )

        embedder.get_embedding("The quick brown fox")

        call_kwargs = mock_client.embeddings.create.call_args[1]
        assert isinstance(call_kwargs["input"], list)
        assert call_kwargs["input"] == ["The quick brown fox"]

    def test_dimensions_passed_for_custom_azure_deployment(self, _mock_openai):
        """When azure_deployment is set, dimensions should be forwarded."""
        mock_client, _ = _mock_openai

        from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder

        embedder = AzureOpenAIEmbedder(
            id="Cohere-embed-v3-multilingual",
            dimensions=1024,
            api_key="test-key",
            azure_endpoint="https://test.openai.azure.com/",
            azure_deployment="Cohere-embed-v3-multilingual",
            openai_client=mock_client,
        )

        embedder.get_embedding("test")

        call_kwargs = mock_client.embeddings.create.call_args[1]
        assert call_kwargs["dimensions"] == 1024

    def test_dimensions_not_sent_for_custom_model_without_explicit_dimensions(self, _mock_openai):
        """When using a custom model without setting dimensions, dimensions should NOT be in the request."""
        mock_client, _ = _mock_openai

        from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder

        embedder = AzureOpenAIEmbedder(
            id="Cohere-embed-v3-multilingual",
            api_key="test-key",
            azure_endpoint="https://test.openai.azure.com/",
            azure_deployment="Cohere-embed-v3-multilingual",
            openai_client=mock_client,
        )

        embedder.get_embedding("test")

        call_kwargs = mock_client.embeddings.create.call_args[1]
        assert "dimensions" not in call_kwargs

    @pytest.mark.asyncio()
    async def test_aresponse_wraps_input_as_list(self, _mock_openai):
        _, mock_response = _mock_openai

        from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder

        async_mock = MagicMock()
        async_mock.embeddings.create = AsyncMock(return_value=mock_response)

        embedder = AzureOpenAIEmbedder(
            id="Cohere-embed-v3-multilingual",
            dimensions=1024,
            api_key="test-key",
            azure_endpoint="https://test.openai.azure.com/",
            azure_deployment="Cohere-embed-v3-multilingual",
            async_client=async_mock,
        )

        await embedder.async_get_embedding("test async input")

        call_kwargs = async_mock.embeddings.create.call_args[1]
        assert isinstance(call_kwargs["input"], list)
        assert call_kwargs["input"] == ["test async input"]
