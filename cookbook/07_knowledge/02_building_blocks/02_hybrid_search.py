"""
Search Types: Vector, Keyword, and Hybrid
===========================================
Knowledge supports three search types. Each has different strengths:

- Vector: Semantic similarity search. Finds conceptually related content
  even when exact words don't match.
- Keyword: Full-text search. Fast and precise for exact term matching.
- Hybrid: Combines vector + keyword. Best of both worlds. Recommended default.

See also: 03_reranking.py for improving search results with reranking.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
pdf_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"


def create_knowledge(search_type: SearchType) -> Knowledge:
    return Knowledge(
        vector_db=PgVector(
            table_name="search_types_%s" % search_type.value,
            db_url=db_url,
            search_type=search_type,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    search_types = [
        (SearchType.vector, "Vector (semantic similarity)"),
        (SearchType.keyword, "Keyword (full-text search)"),
        (SearchType.hybrid, "Hybrid (vector + keyword)"),
    ]

    for search_type, description in search_types:
        print("\n" + "=" * 60)
        print("SEARCH TYPE: %s" % description)
        print("=" * 60 + "\n")

        knowledge = create_knowledge(search_type)
        knowledge.insert(url=pdf_url)

        agent = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            knowledge=knowledge,
            search_knowledge=True,
            markdown=True,
        )
        agent.print_response(
            "How do I make pad thai?",
            stream=True,
        )
