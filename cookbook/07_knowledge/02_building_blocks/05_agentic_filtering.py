"""
Agentic Filtering: Agent-Driven Search Refinement
===================================================
With agentic filtering enabled, the agent inspects available metadata keys
in the knowledge base and dynamically builds filters from the user query.

This is powerful for multi-topic knowledge bases where the user's intent
determines which subset of data to search.

Steps:
1. Load documents with metadata tags
2. Enable agentic filtering on the agent
3. The agent automatically builds filters from user queries

See also: 04_filtering.py for static (predefined) filters.
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
        collection="agentic_filtering_demo",
        url=qdrant_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Enable agentic filtering: the agent inspects metadata keys and dynamically
# builds filters based on the user's query.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    enable_agentic_knowledge_filters=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # Load documents with rich metadata
        await knowledge.ainsert(
            name="Thai Recipes",
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            metadata={"cuisine": "thai", "category": "recipes"},
        )
        await knowledge.ainsert(
            name="CV",
            path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
            metadata={"category": "resume", "department": "engineering"},
        )

        print("\n" + "=" * 60)
        print("Agentic filtering: agent builds filters from query")
        print("=" * 60 + "\n")

        # The agent will automatically filter by cuisine=thai
        agent.print_response("What Thai recipes do you have?", stream=True)

        print("\n" + "=" * 60)
        print("Different query triggers different filters")
        print("=" * 60 + "\n")

        # The agent will automatically filter by category=resume
        agent.print_response("What engineering candidates do you have?", stream=True)

    asyncio.run(main())
