"""
ChromaDB with Hybrid Search using Reciprocal Rank Fusion (RRF)

This example demonstrates how to use ChromaDB with hybrid search,
which combines dense vector similarity search (semantic) with
full-text search (keyword/lexical) using RRF fusion.

Hybrid search is useful when you want to:
- Combine semantic understanding with exact keyword matching
- Improve retrieval accuracy for queries with specific terms
- Handle both conceptual and lexical search needs

The RRF algorithm fuses rankings from both search methods using:
    RRF(d) = sum(1 / (k + rank_i(d))) for each ranking i
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.search import SearchType

# Create Knowledge Instance with ChromaDB using Hybrid Search
knowledge = Knowledge(
    name="Thai Recipes Knowledge Base",
    description="Knowledge base for Thai recipes with hybrid search (RRF fusion)",
    vector_db=ChromaDb(
        collection="thai_recipes_hybrid",
        path="tmp/chromadb_hybrid",
        persistent_client=True,
        # Enable hybrid search - combines vector similarity with keyword matching using RRF
        search_type=SearchType.hybrid,
        # RRF (Reciprocal Rank Fusion) constant - controls ranking smoothness.
        # Higher values (e.g., 60) give more weight to lower-ranked results,
        # Lower values make top results more dominant. Default is 60 (per original RRF paper).
        hybrid_rrf_k=60,
    ),
)

# Load content into the knowledge base
asyncio.run(
    knowledge.add_content_async(
        name="Thai Recipes",
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        metadata={"doc_type": "recipe_book", "cuisine": "thai"},
    )
)

# Create an agent with the hybrid search knowledge base
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
    instructions="You are a helpful Thai cooking assistant. Use the knowledge base to answer questions about Thai recipes.",
)

# Hybrid search will:
# 1. Find semantically similar documents (via dense embeddings)
# 2. Find documents containing query keywords (via FTS)
# 3. Fuse results using RRF for optimal ranking
agent.print_response("What are the ingredients for Massaman curry?", markdown=True)

agent.print_response("How do I make Thai basil chicken?", markdown=True)