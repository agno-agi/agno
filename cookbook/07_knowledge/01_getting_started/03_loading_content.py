"""
Loading Content: All Source Types
==================================
Knowledge supports loading content from many sources: local files, URLs,
raw text, topics (Wikipedia/ArXiv), and batch operations.

This example demonstrates each source type. In production, you'll typically
use one or two of these patterns.

Steps:
1. From a local file path
2. From a URL
3. From raw text
4. From topics (Wikipedia, ArXiv)
5. Batch loading from multiple sources

Note: All examples use async methods (ainsert, ainsert_many).
Sync equivalents (insert, insert_many) are also available.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.wikipedia_reader import WikipediaReader

# Also available: from agno.knowledge.reader.arxiv_reader import ArxivReader
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="loading_content",
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
        # --- 1. From a local file path ---
        print("\n" + "=" * 60)
        print("SOURCE 1: Local file")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="CV",
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
            metadata={"source": "local_file"},
        )

        agent.print_response("What skills does Jordan Mitchell have?", stream=True)

        # --- 2. From a URL ---
        print("\n" + "=" * 60)
        print("SOURCE 2: URL")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Recipes",
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            metadata={"source": "url"},
        )
        agent.print_response("What Thai recipes do you know about?", stream=True)

        # --- 3. From raw text ---
        print("\n" + "=" * 60)
        print("SOURCE 3: Raw text")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Company Info",
            text_content="Acme Corp was founded in 2020. They build AI tools for developers.",
            metadata={"source": "text"},
        )
        agent.print_response("What does Acme Corp do?", stream=True)

        # --- 4. From topics (Wikipedia + ArXiv) ---
        print("\n" + "=" * 60)
        print("SOURCE 4: Topics (Wikipedia)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            topics=["Retrieval-Augmented Generation"],
            reader=WikipediaReader(),
        )
        agent.print_response("What is RAG?", stream=True)

        # --- 5. Batch loading from multiple sources ---
        print("\n" + "=" * 60)
        print("SOURCE 5: Batch loading (insert_many)")
        print("=" * 60 + "\n")

        await knowledge.ainsert_many(
            [
                {
                    "name": "Doc 1",
                    "text_content": "Python is a programming language.",
                    "metadata": {"topic": "programming"},
                },
                {
                    "name": "Doc 2",
                    "text_content": "TypeScript adds types to JavaScript.",
                    "metadata": {"topic": "programming"},
                },
            ]
        )
        agent.print_response("Compare Python and TypeScript", stream=True)

    asyncio.run(main())
