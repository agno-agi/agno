"""Distinguish search failures from empty results, synchronously and asynchronously.

Uses an in-memory Qdrant collection and an embedder that deliberately fails.
No API credentials, external services, or model downloads are required.
Install the optional dependency with: uv pip install qdrant-client
"""

import asyncio
from typing import List

from agno.exceptions import EmbeddingError
from agno.knowledge.embedder.base import Embedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.qdrant import Qdrant


class UnavailableEmbedder(Embedder):
    """Simulate an embedding provider outage without making a network request."""

    def get_embedding(self, text: str) -> List[float]:
        raise EmbeddingError("Embedding service unavailable", status_code=503)

    async def async_get_embedding(self, text: str) -> List[float]:
        return self.get_embedding(text)


async def main() -> None:
    vector_db = Qdrant(
        collection="search_errors",
        location=":memory:",
        embedder=UnavailableEmbedder(dimensions=3),
    )
    default_knowledge = Knowledge(vector_db=vector_db)
    print("Default behavior:", default_knowledge.search("query"))

    knowledge = Knowledge(vector_db=vector_db, raise_on_search_error=True)
    try:
        knowledge.search("query")
    except EmbeddingError as error:
        print("Sync caller can report or retry:", error.safe_message)

    try:
        await knowledge.asearch("query")
    except EmbeddingError as error:
        print("Async caller can report or retry:", error.safe_message)

    # Agent search tools report the exception type instead of "No documents found".
    tool = knowledge.get_tools()[0]
    print("Agent tool:", tool.entrypoint(query="query"))
    vector_db.client.close()


if __name__ == "__main__":
    asyncio.run(main())
