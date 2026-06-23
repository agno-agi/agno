"""
Databricks Vector DB
====================

Demonstrates DatabricksVectorDb with a Databricks embedding endpoint.
"""

import os

from agno.knowledge.embedder.databricks import DatabricksEmbedder
from agno.vectordb.databricks import DatabricksVectorDb


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


if __name__ == "__main__":
    embedder = DatabricksEmbedder(
        host=_require_env("DATABRICKS_HOST"),
        token=_require_env("DATABRICKS_TOKEN"),
        endpoint=_require_env("DATABRICKS_EMBEDDING_ENDPOINT"),
    )

    vector_db = DatabricksVectorDb(
        host=_require_env("DATABRICKS_HOST"),
        token=_require_env("DATABRICKS_TOKEN"),
        endpoint_name=_require_env("DATABRICKS_VECTOR_SEARCH_ENDPOINT"),
        index_name=_require_env("DATABRICKS_VECTOR_SEARCH_INDEX"),
        embedder=embedder,
    )

    results = vector_db.search("Databricks vector search", limit=2)
    for document in results:
        print(
            {
                "id": document.id,
                "content_preview": document.content[:160] if document.content else "",
                "content_id": document.content_id,
                "metadata": document.meta_data,
                "score": document.reranking_score,
            }
        )
