from unittest.mock import AsyncMock, Mock

import pytest

from agno.knowledge.embedder.databricks import DatabricksEmbedder


def _embedding_response():
    return {
        "data": [
            {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            {"index": 0, "embedding": [0.1, 0.2, 0.3]},
        ],
        "usage": {
            "prompt_tokens": 5,
            "total_tokens": 5,
        },
    }


def test_post_init_uses_id_as_endpoint():
    embedder = DatabricksEmbedder(id="my-endpoint")

    assert embedder.endpoint == "my-endpoint"
    assert embedder.dimensions is None


def test_build_request_params_omits_dimensions_by_default():
    embedder = DatabricksEmbedder(endpoint="my-endpoint")

    request_params = embedder._build_request_params("hello")

    assert request_params["model"] == "my-endpoint"
    assert request_params["input"] == ["hello"]
    assert "dimensions" not in request_params


def test_build_request_params_includes_explicit_dimensions_and_user():
    embedder = DatabricksEmbedder(endpoint="my-endpoint", dimensions=1024, user="user-1")

    request_params = embedder._build_request_params("hello")

    assert request_params["dimensions"] == 1024
    assert request_params["user"] == "user-1"


def test_get_client_loads_host_and_token_from_env(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://env.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "env-token")

    embedder = DatabricksEmbedder(endpoint="my-endpoint")

    client = embedder.get_client()

    assert client.settings.host == "https://env.cloud.databricks.com"
    assert client.settings.workspace_url == "https://env.cloud.databricks.com"
    assert client.settings.token == "env-token"


def test_explicit_embedder_settings_override_env(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://env.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "env-token")

    embedder = DatabricksEmbedder(
        endpoint="my-endpoint",
        host="https://explicit.cloud.databricks.com",
        token="explicit-token",
        default_headers={"X-Test": "1"},
    )

    client = embedder.get_client()

    assert client.settings.host == "https://explicit.cloud.databricks.com"
    assert client.settings.workspace_url == "https://explicit.cloud.databricks.com"
    assert client.settings.token == "explicit-token"
    assert client.settings.default_headers["X-Test"] == "1"


def test_explicit_embedder_settings_are_revalidated():
    embedder = DatabricksEmbedder(
        endpoint="my-endpoint",
        host="explicit.cloud.databricks.com/",
    )

    client = embedder.get_client()

    assert client.settings.host == "https://explicit.cloud.databricks.com"
    assert client.settings.workspace_url == "https://explicit.cloud.databricks.com"


def test_invalid_explicit_embedder_timeout_raises():
    embedder = DatabricksEmbedder(endpoint="my-endpoint", timeout=0)

    with pytest.raises(ValueError):
        embedder.get_client()


def test_get_embedding_uses_native_client_and_sorts_by_index():
    mock_client = Mock()
    mock_client.request_json.return_value = _embedding_response()

    embedder = DatabricksEmbedder(endpoint="my-endpoint", host="https://example.cloud.databricks.com")
    embedder.client = mock_client

    embedding = embedder.get_embedding("hello")

    assert embedding == [0.1, 0.2, 0.3]
    assert embedder.dimensions == 3
    mock_client.request_json.assert_called_once_with(
        "POST",
        "/serving-endpoints/embeddings",
        json={"model": "my-endpoint", "input": ["hello"]},
    )


def test_get_embedding_and_usage_returns_usage():
    mock_client = Mock()
    mock_client.request_json.return_value = _embedding_response()

    embedder = DatabricksEmbedder(endpoint="my-endpoint", host="https://example.cloud.databricks.com")
    embedder.client = mock_client

    embedding, usage = embedder.get_embedding_and_usage("hello")

    assert embedding == [0.1, 0.2, 0.3]
    assert usage == {"prompt_tokens": 5, "total_tokens": 5}


@pytest.mark.asyncio
async def test_async_get_embedding_uses_native_async_client():
    mock_client = Mock()
    mock_client.request_json = AsyncMock(return_value=_embedding_response())

    embedder = DatabricksEmbedder(endpoint="my-endpoint", host="https://example.cloud.databricks.com")
    embedder.async_client = mock_client

    embedding = await embedder.async_get_embedding("hello")

    assert embedding == [0.1, 0.2, 0.3]
    mock_client.request_json.assert_awaited_once_with(
        "POST",
        "/serving-endpoints/embeddings",
        json={"model": "my-endpoint", "input": ["hello"]},
    )


@pytest.mark.asyncio
async def test_async_get_embedding_and_usage_returns_usage():
    mock_client = Mock()
    mock_client.request_json = AsyncMock(return_value=_embedding_response())

    embedder = DatabricksEmbedder(endpoint="my-endpoint", host="https://example.cloud.databricks.com")
    embedder.async_client = mock_client

    embedding, usage = await embedder.async_get_embedding_and_usage("hello")

    assert embedding == [0.1, 0.2, 0.3]
    assert usage == {"prompt_tokens": 5, "total_tokens": 5}


def test_batch_embedding_falls_back_to_individual_requests():
    mock_client = Mock()
    mock_client.request_json.side_effect = [
        RuntimeError("batch failed"),
        {
            "data": [{"index": 0, "embedding": [0.1, 0.2]}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        },
        {
            "data": [{"index": 0, "embedding": [0.3, 0.4]}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        },
    ]

    embedder = DatabricksEmbedder(
        endpoint="my-endpoint",
        host="https://example.cloud.databricks.com",
        batch_size=10,
    )
    embedder.client = mock_client

    embeddings, usages = embedder.get_embeddings_batch_and_usage(["first", "second"])

    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert usages == [
        {"prompt_tokens": 1, "total_tokens": 1},
        {"prompt_tokens": 1, "total_tokens": 1},
    ]


@pytest.mark.asyncio
async def test_async_batch_embedding_falls_back_to_individual_requests():
    mock_client = Mock()
    mock_client.request_json = AsyncMock(
        side_effect=[
            RuntimeError("batch failed"),
            {
                "data": [{"index": 0, "embedding": [0.1, 0.2]}],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
            {
                "data": [{"index": 0, "embedding": [0.3, 0.4]}],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        ]
    )

    embedder = DatabricksEmbedder(
        endpoint="my-endpoint",
        host="https://example.cloud.databricks.com",
        batch_size=10,
    )
    embedder.async_client = mock_client

    embeddings, usages = await embedder.async_get_embeddings_batch_and_usage(["first", "second"])

    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert usages == [
        {"prompt_tokens": 1, "total_tokens": 1},
        {"prompt_tokens": 1, "total_tokens": 1},
    ]
