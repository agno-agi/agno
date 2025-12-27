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
from textwrap import dedent

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.chroma import ChromaDb, SearchType

# ============================================================================
# Setup knowledge base with ChromaDB for storing Agno documentation
# ============================================================================
knowledge = Knowledge(
    name="Agno Documentation",
    description="Knowledge base for Agno framework documentation",
    vector_db=ChromaDb(
        name="agno_docs",
        path="tmp/chromadb_hybrid",
        persistent_client=True,
        # Enable hybrid search - combines vector similarity with keyword matching using RRF
        search_type=SearchType.hybrid,
        # RRF (Reciprocal Rank Fusion) constant - controls ranking smoothness.
        # Higher values (e.g., 60) give more weight to lower-ranked results,
        # Lower values make top results more dominant. Default is 60 (per original RRF paper).
        hybrid_rrf_k=60,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    max_results=10,
)

# ============================================================================
# Description & Instructions for the agent
# ============================================================================
description = dedent(
    """\
    You are AgnoAssist — an AI Agent built to help developers learn and master the Agno framework.
    Your goal is to provide clear explanations and complete, working code examples to help users understand and effectively use Agno and AgentOS.\
    """
)

instructions = dedent(
    """\
    Your mission is to provide comprehensive, developer-focused support for the Agno ecosystem.

    Follow this structured process to ensure accurate and actionable responses:

    1. **Analyze the request**
        - Determine whether the query requires a knowledge lookup, code generation, or both.
        - All concepts are within the context of Agno - you don't need to clarify this.

    After analysis, immediately begin the search process (no need to ask for confirmation).

    2. **Search Process**
        - Use the `search_knowledge` tool to retrieve relevant concepts, code examples, and implementation details.
        - Perform iterative searches until you've gathered enough information or exhausted relevant terms.

    Once your research is complete, decide whether code creation is required.
    If it is, ask the user if they'd like you to generate an Agent for them.

    3. **Code Creation**
        - Provide fully working code examples that can be run as-is.
        - Always use `agent.run()` (not `agent.print_response()`).
        - Include all imports, setup, and dependencies.
        - Add clear comments, type hints, and docstrings.
        - Demonstrate usage with example queries.

        Example:
        ```python
        from agno.agent import Agent
        from agno.tools.duckduckgo import DuckDuckGoTools

        agent = Agent(tools=[DuckDuckGoTools()])

        response = agent.run("What's happening in France?")
        print(response)
        ```
    """
)

# Create an agent with the hybrid search knowledge base
agent = Agent(
    name="Agno Knowledge Agent",
    model=OpenAIChat(id="gpt-5-mini"),
    knowledge=knowledge,
    instructions=instructions,
    description=description,
)


if __name__ == "__main__":
    # Load Agno documentation into the knowledge base
    asyncio.run(
        knowledge.add_content_async(
            name="Agno Documentation",
            url="https://docs.agno.com/llms-full.txt",
        )
    )

    # Hybrid search will:
    # 1. Find semantically similar documents (via dense embeddings)
    # 2. Find documents containing query keywords (via FTS)
    # 3. Fuse results using RRF for optimal ranking
    agent.print_response("How do I create an agent with tools?", markdown=True)
