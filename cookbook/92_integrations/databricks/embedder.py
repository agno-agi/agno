"""
Databricks Embedder
===================

Demonstrates the Databricks native embedding endpoint integration.
"""

import os

from agno.knowledge.embedder.databricks import DatabricksEmbedder


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

    embedding = embedder.get_embedding("Databricks vector search integration")
    print({"dimensions": embedder.dimensions, "vector_length": len(embedding), "preview": embedding[:5]})
