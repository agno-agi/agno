"""
LiteLLM Embedder and Reranker
==============================
LiteLLM provides a unified interface to 100+ embedding and reranking providers.
Use any supported provider with a single configuration surface.

Supported embedding providers (sample):
- openai/text-embedding-3-small
- openai/text-embedding-3-large
- cohere/embed-english-v3.0
- jina/jina-embeddings-v2-base-en
- voyage/voyage-3

Supported reranking providers (sample):
- cohere/rerank-multilingual-v3.0
- cohere/rerank-english-v3.0
- jina/jina-reranker-v2-base-en
- voyageai/voyage-rerank-2

Requirements:
    pip install litellm

Set the relevant API key(s) as environment variables, e.g.:
    export OPENAI_API_KEY=...
    export COHERE_API_KEY=...
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.litellm import LiteLLMEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.litellm import LiteLLMReranker
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
        # --- 1. LiteLLM embedder (OpenAI via LiteLLM) ---
        print("\n" + "=" * 60)
        print("LiteLLM Embedder: openai/text-embedding-3-small")
        print("=" * 60 + "\n")

        knowledge_litellm = Knowledge(
            vector_db=Qdrant(
                collection="litellm_embedder_demo",
                url=qdrant_url,
                search_type=SearchType.hybrid,
                embedder=LiteLLMEmbedder(
                    id="openai/text-embedding-3-small",
                    dimensions=1536,
                ),
            ),
        )
        await knowledge_litellm.ainsert(url=pdf_url, skip_if_exists=True)

        agent_embed = Agent(
            model=OpenAIResponses(id="gpt-5.5"),
            knowledge=knowledge_litellm,
            search_knowledge=True,
            markdown=True,
        )
        agent_embed.print_response("What are some Thai dessert recipes?", stream=True)

        # --- 2. LiteLLM embedder + LiteLLM reranker ---
        print("\n" + "=" * 60)
        print("LiteLLM Embedder + LiteLLM Reranker (Cohere)")
        print("=" * 60 + "\n")

        knowledge_reranked = Knowledge(
            vector_db=Qdrant(
                collection="litellm_reranker_demo",
                url=qdrant_url,
                search_type=SearchType.hybrid,
                embedder=LiteLLMEmbedder(
                    id="openai/text-embedding-3-small",
                    dimensions=1536,
                ),
                reranker=LiteLLMReranker(
                    model="cohere/rerank-multilingual-v3.0",
                    top_n=5,
                ),
            ),
        )
        await knowledge_reranked.ainsert(url=pdf_url, skip_if_exists=True)

        agent_reranked = Agent(
            model=OpenAIResponses(id="gpt-5.5"),
            knowledge=knowledge_reranked,
            search_knowledge=True,
            instructions=[
                "Always search your knowledge base before answering.",
                "Include sources in your response.",
            ],
            markdown=True,
        )
        agent_reranked.print_response("How do I make pad thai?", stream=True)

    asyncio.run(main())
