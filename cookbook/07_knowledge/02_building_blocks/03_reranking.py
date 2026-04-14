"""
Reranking: Improving Search Quality
=====================================
Reranking is a two-stage retrieval process:
1. First, retrieve candidate results using vector/hybrid search
2. Then, a reranker model scores and reorders results by relevance

This dramatically improves result quality, especially for complex queries.

Supported rerankers:
- CohereReranker: Cohere's rerank models (recommended)
- SentenceTransformerReranker: Local reranking with BAAI/bge models
- InfinityReranker: Self-hosted reranking
- BedrockReranker: AWS Bedrock reranking

See also: 02_hybrid_search.py for search type options.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.cohere import CohereReranker
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

# Knowledge with hybrid search + Cohere reranking
knowledge = Knowledge(
    vector_db=Qdrant(
        collection="reranking_demo",
        url=qdrant_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        reranker=CohereReranker(model="rerank-multilingual-v3.0"),
    ),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    instructions=[
        "Always search your knowledge base before answering.",
        "Include sources in your response.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        await knowledge.ainsert(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )

        print("\n" + "=" * 60)
        print("Hybrid search + Cohere reranking")
        print("=" * 60 + "\n")

        agent.print_response(
            "What are some good Thai dessert recipes?",
            stream=True,
        )

    asyncio.run(main())
