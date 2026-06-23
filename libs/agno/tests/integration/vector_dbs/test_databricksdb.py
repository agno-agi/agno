import os

import pytest

from agno.knowledge.embedder.databricks import DatabricksEmbedder
from agno.vectordb.databricks import DatabricksVectorDb


@pytest.fixture
def vector_db():
    host = os.environ.get("DATABRICKS_HOST")
    token = os.environ.get("DATABRICKS_TOKEN")

    embedder = DatabricksEmbedder(
        host=host,
        token=token,
        endpoint=os.environ.get("DATABRICKS_EMBEDDING_ENDPOINT"),
    )

    return DatabricksVectorDb(
        host=host,
        token=token,
        endpoint_name=os.environ.get("DATABRICKS_VECTOR_SEARCH_ENDPOINT", ""),
        index_name=os.environ.get("DATABRICKS_VECTOR_SEARCH_INDEX", ""),
        embedder=embedder,
    )


@pytest.mark.skipif(
    not os.environ.get("DATABRICKS_HOST")
    or not os.environ.get("DATABRICKS_TOKEN")
    or not os.environ.get("DATABRICKS_EMBEDDING_ENDPOINT")
    or not os.environ.get("DATABRICKS_VECTOR_SEARCH_ENDPOINT")
    or not os.environ.get("DATABRICKS_VECTOR_SEARCH_INDEX"),
    reason="Databricks vector search credentials not set",
)
def test_exists(vector_db):
    assert vector_db.exists() is True


@pytest.mark.skipif(
    not os.environ.get("DATABRICKS_HOST")
    or not os.environ.get("DATABRICKS_TOKEN")
    or not os.environ.get("DATABRICKS_EMBEDDING_ENDPOINT")
    or not os.environ.get("DATABRICKS_VECTOR_SEARCH_ENDPOINT")
    or not os.environ.get("DATABRICKS_VECTOR_SEARCH_INDEX"),
    reason="Databricks vector search credentials not set",
)
def test_search(vector_db):
    results = vector_db.search("Databricks vector search", limit=2)

    assert isinstance(results, list)
