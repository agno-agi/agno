from unittest.mock import MagicMock

from agno.knowledge.embedder.nebius import NebiusEmbedder


def test_default_config_uses_active_catalog_model():
    embedder = NebiusEmbedder(api_key="test-api-key")

    assert embedder.id == "Qwen/Qwen3-Embedding-8B"
    assert embedder.dimensions == 4096
    assert embedder.base_url == "https://api.tokenfactory.nebius.com/v1/"


def test_embedding_request_uses_token_factory_model_and_dimensions():
    client = MagicMock()
    expected_response = MagicMock()
    client.embeddings.create.return_value = expected_response
    embedder = NebiusEmbedder(
        api_key="test-api-key",
        openai_client=client,
    )

    result = embedder.response("hello")

    assert result is expected_response
    client.embeddings.create.assert_called_once_with(
        input="hello",
        model="Qwen/Qwen3-Embedding-8B",
        encoding_format="float",
        dimensions=4096,
    )
