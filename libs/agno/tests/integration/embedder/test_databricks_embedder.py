import os

import pytest

from agno.knowledge.embedder.databricks import DatabricksEmbedder


@pytest.fixture
def embedder():
    return DatabricksEmbedder(
        host=os.environ.get("DATABRICKS_HOST"),
        token=os.environ.get("DATABRICKS_TOKEN"),
        endpoint=os.environ.get("DATABRICKS_EMBEDDING_ENDPOINT"),
    )


@pytest.mark.skipif(
    not os.environ.get("DATABRICKS_HOST")
    or not os.environ.get("DATABRICKS_TOKEN")
    or not os.environ.get("DATABRICKS_EMBEDDING_ENDPOINT"),
    reason="Databricks embedding credentials not set",
)
def test_get_embedding(embedder):
    embedding = embedder.get_embedding("The quick brown fox jumps over the lazy dog.")

    assert isinstance(embedding, list)
    assert len(embedding) > 0


@pytest.mark.skipif(
    not os.environ.get("DATABRICKS_HOST")
    or not os.environ.get("DATABRICKS_TOKEN")
    or not os.environ.get("DATABRICKS_EMBEDDING_ENDPOINT"),
    reason="Databricks embedding credentials not set",
)
@pytest.mark.asyncio
async def test_async_get_embedding(embedder):
    embedding = await embedder.async_get_embedding("Async embedding test")

    assert isinstance(embedding, list)
    assert len(embedding) > 0
