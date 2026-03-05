"""
LightRAG: Graph-Based External Provider
=========================================
LightRAG is an external knowledge provider that manages its own
graph-based indexing pipeline. Unlike vector databases where Agno
handles chunking, embedding, and storage, LightRAG runs its own
server and handles everything internally.

How it works:
- Documents are sent to LightRAG's HTTP API
- LightRAG extracts entities and relationships
- Queries traverse the knowledge graph for multi-hop reasoning

This is useful when you want graph-based RAG without managing
the graph construction yourself.

Requirements:
- LightRAG server running (default: http://localhost:9621)
- pip install lightrag-agno
"""

import asyncio
from os import getenv

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

try:
    from agno.knowledge.external_provider import LightRagProvider

    # LightRagProvider implements the ExternalKnowledgeProvider protocol.
    # It handles ingestion, querying, and deletion via LightRAG's HTTP API.
    provider = LightRagProvider(
        server_url=getenv("LIGHTRAG_SERVER_URL", "http://localhost:9621"),
        api_key=getenv("LIGHTRAG_API_KEY"),
    )

    # Pass the provider directly — no vector_db needed.
    knowledge = Knowledge(
        name="lightrag-demo",
        external_provider=provider,
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o"),
        knowledge=knowledge,
        search_knowledge=True,
        markdown=True,
    )

except ImportError:
    provider = None
    knowledge = None
    agent = None
    print("LightRAG not installed. Run: pip install lightrag-agno")


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        if not knowledge or not agent:
            print("Skipping demo: LightRAG not installed.")
            return

        # 1. Ingest a document — LightRAG builds a knowledge graph from it
        print("\n--- Ingesting document into LightRAG ---\n")
        await knowledge.ainsert(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )

        # 2. Query via the agent — retrieval goes through LightRAG's graph
        print("\n" + "=" * 60)
        print("LightRAG: graph-based knowledge retrieval")
        print("=" * 60 + "\n")

        agent.print_response(
            "What ingredients are commonly shared across Thai recipes?",
            stream=True,
        )

        # 3. You can also query the provider directly for raw results
        print("\n--- Direct provider query ---\n")
        results = await provider.aquery("What Thai dishes use coconut milk?")
        if results:
            print(f"Got {len(results)} result(s)")
            print(f"References: {results[0].meta_data.get('references', [])}")

    asyncio.run(main())
