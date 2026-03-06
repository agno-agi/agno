"""
Multi-Source RAG: Combining Different Content Types
====================================================
In production, agents often need knowledge from multiple sources:
PDFs, web pages, text snippets, and databases.

This example loads content from different source types into the same
knowledge base, demonstrating insert_many with mixed sources.

See also: 02_knowledge_lifecycle.py for managing content over time.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="multi_source_rag",
        url=qdrant_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # Load multiple sources in a single batch call
        await knowledge.ainsert_many(
            [
                {
                    "name": "Candidate Resume",
                    "path": "cookbook/07_knowledge/testing_resources/cv_1.pdf",
                    "metadata": {"source": "resume", "department": "engineering"},
                },
                {
                    "name": "Thai Recipes",
                    "url": "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
                    "metadata": {"source": "web", "topic": "cooking"},
                },
                {
                    "name": "Company Policy",
                    "text_content": "All employees must complete security training annually. "
                    "Remote work requires VPN access. Expenses over $500 need manager approval.",
                    "metadata": {"source": "internal", "topic": "policy"},
                },
            ]
        )

        print("\n" + "=" * 60)
        print("Query across multiple sources")
        print("=" * 60 + "\n")

        agent.print_response("What skills does Jordan Mitchell have?", stream=True)

        print("\n" + "=" * 60)
        print("Agent searches the same knowledge base for different topics")
        print("=" * 60 + "\n")

        agent.print_response("What is the expense approval policy?", stream=True)

    asyncio.run(main())
