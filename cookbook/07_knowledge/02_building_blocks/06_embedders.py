"""
Embedders: Choosing and Configuring Embedding Models
=====================================================
Embedders convert text into vectors for semantic search. The choice of
embedder affects search quality, cost, and privacy.

This example shows two common configurations:
1. OpenAI (cloud, recommended default)
2. Ollama (local, private, no API calls)

For a full comparison of all 17+ supported providers, see:
    ../reference/embedder_comparison.md
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
pdf_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # --- 1. OpenAI embedder (cloud, recommended default) ---
        print("\n" + "=" * 60)
        print("EMBEDDER 1: OpenAI text-embedding-3-small")
        print("=" * 60 + "\n")

        knowledge_openai = Knowledge(
            vector_db=Qdrant(
                collection="embedder_openai",
                url=qdrant_url,
                search_type=SearchType.hybrid,
                embedder=OpenAIEmbedder(id="text-embedding-3-small"),
            ),
        )
        await knowledge_openai.ainsert(url=pdf_url, skip_if_exists=True)

        agent_openai = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            knowledge=knowledge_openai,
            search_knowledge=True,
            markdown=True,
        )
        agent_openai.print_response("How do I make pad thai?", stream=True)

        # --- 2. Ollama embedder (local, private) ---
        # Requires: ollama pull nomic-embed-text
        print("\n" + "=" * 60)
        print("EMBEDDER 2: Ollama nomic-embed-text (local)")
        print("=" * 60 + "\n")

        try:
            from agno.knowledge.embedder.ollama import OllamaEmbedder

            knowledge_ollama = Knowledge(
                vector_db=Qdrant(
                    collection="embedder_ollama",
                    url=qdrant_url,
                    search_type=SearchType.hybrid,
                    embedder=OllamaEmbedder(
                        id="nomic-embed-text",
                        dimensions=768,
                    ),
                ),
            )
            await knowledge_ollama.ainsert(url=pdf_url, skip_if_exists=True)

            agent_ollama = Agent(
                model=OpenAIResponses(id="gpt-5.2"),
                knowledge=knowledge_ollama,
                search_knowledge=True,
                markdown=True,
            )
            agent_ollama.print_response("How do I make pad thai?", stream=True)

        except ImportError:
            print("Ollama not installed. Run: pip install ollama")
        except Exception as e:
            print("Ollama embedder failed (is Ollama running?): %s" % e)

    asyncio.run(main())
