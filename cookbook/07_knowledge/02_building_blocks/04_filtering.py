"""
Filtering: Metadata-Based Search Refinement
=============================================
Filters let you narrow search results based on document metadata.
This is essential for multi-user, multi-topic, or access-controlled systems.

Two stages of filtering:
1. On load: Tag documents with metadata at insert time
2. On search: Apply filters when the agent searches

Filter approaches:
- Dict filters: Simple key-value matching {"category": "recipes"}
- FilterExpr: Powerful expressions with AND, OR, NOT, EQ, IN, GT, LT

See also: 05_agentic_filtering.py for agent-driven filter selection.
"""

import asyncio

from agno.agent import Agent
from agno.filters import AND, EQ, GT, IN, NOT, OR
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
        collection="filtering_demo",
        url=qdrant_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # --- Stage 1: On load - tag documents with metadata ---
        print("\n" + "=" * 60)
        print("STAGE 1: Insert with metadata (on-load filtering)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Thai Recipes",
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            metadata={"cuisine": "thai", "category": "recipes", "difficulty": 3},
        )

        await knowledge.ainsert(
            name="Company Info",
            text_content="Agno is an AI framework for building agents with knowledge.",
            metadata={"category": "docs", "topic": "agno", "difficulty": 1},
        )

        # --- Stage 2: On search - filter at query time ---

        # 2a. Dict filters: simple key-value matching
        print("\n" + "=" * 60)
        print("STAGE 2a: Dict filters (simple key-value)")
        print("=" * 60 + "\n")

        agent_dict = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            knowledge=knowledge,
            search_knowledge=True,
            knowledge_filters={"cuisine": "thai"},
            markdown=True,
        )
        agent_dict.print_response("What recipes do you know?", stream=True)

        # 2b. FilterExpr with AND + EQ + IN
        print("\n" + "=" * 60)
        print("STAGE 2b: FilterExpr (AND, EQ, IN)")
        print("=" * 60 + "\n")

        agent_expr = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            knowledge=knowledge,
            search_knowledge=True,
            knowledge_filters=[
                AND(EQ("category", "recipes"), IN("cuisine", ["thai", "indian"]))
            ],
            markdown=True,
        )
        agent_expr.print_response("What recipes do you know?", stream=True)

        # 2c. FilterExpr with OR
        print("\n" + "=" * 60)
        print("STAGE 2c: FilterExpr (OR)")
        print("=" * 60 + "\n")

        agent_or = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            knowledge=knowledge,
            search_knowledge=True,
            knowledge_filters=[OR(EQ("category", "recipes"), EQ("category", "docs"))],
            markdown=True,
        )
        agent_or.print_response("What do you know?", stream=True)

        # 2d. FilterExpr with GT (greater than)
        print("\n" + "=" * 60)
        print("STAGE 2d: FilterExpr (GT - difficulty > 2)")
        print("=" * 60 + "\n")

        agent_gt = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            knowledge=knowledge,
            search_knowledge=True,
            knowledge_filters=[GT("difficulty", 2)],
            markdown=True,
        )
        agent_gt.print_response("What do you know?", stream=True)

        # 2e. FilterExpr with NOT
        print("\n" + "=" * 60)
        print("STAGE 2e: FilterExpr (NOT - exclude docs)")
        print("=" * 60 + "\n")

        agent_not = Agent(
            model=OpenAIResponses(id="gpt-5.2"),
            knowledge=knowledge,
            search_knowledge=True,
            knowledge_filters=[NOT(EQ("category", "docs"))],
            markdown=True,
        )
        agent_not.print_response("What do you know?", stream=True)

    asyncio.run(main())
