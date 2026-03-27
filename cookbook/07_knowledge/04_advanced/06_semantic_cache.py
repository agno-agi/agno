"""
Semantic Cache for Knowledge Search
===================================
This example demonstrates semantic caching at the Knowledge layer.

What it shows:
- First query performs a normal vector search (cache miss)
- Semantically similar second query reuses cached retrieval results (cache hit)
- Works transparently with standard Knowledge.search()

Prerequisites:
- Qdrant running on http://localhost:6333
- OPENAI_API_KEY set
"""

from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="semantic_cache_demo",
        url=qdrant_url,
        search_type=SearchType.vector,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    enable_semantic_cache=True,
    semantic_cache_similarity_threshold=0.88,
    semantic_cache_ttl=300,
    semantic_cache_max_entries=256,
)


def main() -> None:
    knowledge.insert(url="https://docs.agno.com/introduction.md")

    # Wrap vector search so we can observe whether the second query hits cache.
    vector_search_calls = {"count": 0}
    original_search = knowledge.vector_db.search  # type: ignore[union-attr]

    def counted_search(*args, **kwargs):
        vector_search_calls["count"] += 1
        return original_search(*args, **kwargs)

    knowledge.vector_db.search = counted_search  # type: ignore[union-attr, method-assign]

    query_one = "What are Agno key features?"
    query_two = "What are Agno's key features?"

    docs_one = knowledge.search(query_one, max_results=5)
    print("First query documents:", len(docs_one))
    print("Vector search calls after first query:", vector_search_calls["count"])

    docs_two = knowledge.search(query_two, max_results=5)
    print("Second query documents:", len(docs_two))
    print("Vector search calls after second query:", vector_search_calls["count"])

    if vector_search_calls["count"] == 1:
        print("Semantic cache hit detected on second query.")
    else:
        print("Semantic cache miss on second query.")


if __name__ == "__main__":
    main()
