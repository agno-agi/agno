"""
Valkey Metadata Filtering
=========================

Demonstrates Valkey metadata filtering on indexed TAG fields.

To get started, start local Valkey with:
`docker run --name my-valkey -p 6379:6379 -d valkey/valkey-bundle`

Install dependency:
`uv pip install valkey-glide-sync`
"""

import os

from agno.knowledge.knowledge import Knowledge
from agno.vectordb.search import SearchType
from agno.vectordb.valkey import ValkeyVectorDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
INDEX_NAME = os.getenv("VALKEY_INDEX", "agno_cookbook_filtering")

vector_db = ValkeyVectorDb(
    index_name=INDEX_NAME,
    search_type=SearchType.vector,
)


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
knowledge = Knowledge(
    name="Valkey Filtering Knowledge Base",
    vector_db=vector_db,
)


# ---------------------------------------------------------------------------
# Metadata filtering
# ---------------------------------------------------------------------------
# Only fields indexed as TAG fields in the schema can be filtered server-side
# (id, name, status, category, tag, source, mode, content_id, linked_to);
# other keys are stored but skipped with a warning.
def main() -> None:
    knowledge.insert(
        text_content="Tom Kha Gai is a Thai coconut soup",
        metadata={"category": "recipes"},
    )
    knowledge.insert(
        text_content="The stock market rose today",
        metadata={"category": "finance"},
    )

    results = knowledge.search("soup", filters={"category": "recipes"})
    top_match = results[0].content[:40] if results else "none"
    print(f"category=recipes: {len(results)} result(s), top match: {top_match}")

    results = knowledge.search("soup", filters={"category": "finance"})
    top_match = results[0].content[:40] if results else "none"
    print(f"category=finance: {len(results)} result(s), top match: {top_match}")


if __name__ == "__main__":
    main()
