from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture()
def _mock_openai_client():
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    mock_response.usage = None

    mock_client = MagicMock()
    mock_client.embeddings.create.return_value = mock_response

    return mock_client, mock_response


@pytest.fixture()
def _mock_async_openai_client():
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    mock_response.usage = None

    mock_client = MagicMock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)

    return mock_client, mock_response


class TestOpenAIEmbedderDimensions:
    def test_dimensions_passed_for_text_embedding_3_models(self, _mock_openai_client):
        mock_client, _ = _mock_openai_client

        from agno.knowledge.embedder.openai import OpenAIEmbedder

        embedder = OpenAIEmbedder(id="text-embedding-3-small", dimensions=512)
        embedder.openai_client = mock_client

        embedder.get_embedding("test")

        call_kwargs = mock_client.embeddings.create.call_args[1]
        assert call_kwargs.get("dimensions") == 512

    def test_dimensions_passed_with_custom_base_url(self, _mock_openai_client):
        mock_client, _ = _mock_openai_client

        from agno.knowledge.embedder.openai import OpenAIEmbedder

        embedder = OpenAIEmbedder(
            id="text-embedding-v4",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            dimensions=1024,
        )
        embedder.openai_client = mock_client

        embedder.get_embedding("test")

        call_kwargs = mock_client.embeddings.create.call_args[1]
        assert call_kwargs.get("dimensions") == 1024

    def test_dimensions_not_passed_for_legacy_openai_models(self, _mock_openai_client):
        mock_client, _ = _mock_openai_client

        from agno.knowledge.embedder.openai import OpenAIEmbedder

        embedder = OpenAIEmbedder(id="text-embedding-ada-002", dimensions=256)
        embedder.openai_client = mock_client

        embedder.get_embedding("test")

        call_kwargs = mock_client.embeddings.create.call_args[1]
        assert "dimensions" not in call_kwargs

    @pytest.mark.asyncio
    async def test_async_dimensions_passed_with_custom_base_url(self, _mock_async_openai_client):
        mock_client, _ = _mock_async_openai_client

        from agno.knowledge.embedder.openai import OpenAIEmbedder

        embedder = OpenAIEmbedder(
            id="text-embedding-v4",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            dimensions=768,
        )
        embedder.async_client = mock_client

        await embedder.async_get_embedding("test")

        call_kwargs = mock_client.embeddings.create.call_args[1]
        assert call_kwargs.get("dimensions") == 768

    @pytest.mark.asyncio
    async def test_async_dimensions_not_passed_for_legacy_models(self, _mock_async_openai_client):
        mock_client, _ = _mock_async_openai_client

        from agno.knowledge.embedder.openai import OpenAIEmbedder

        embedder = OpenAIEmbedder(id="text-embedding-ada-002", dimensions=256)
        embedder.async_client = mock_client

        await embedder.async_get_embedding("test")

        call_kwargs = mock_client.embeddings.create.call_args[1]
        assert "dimensions" not in call_kwargs
