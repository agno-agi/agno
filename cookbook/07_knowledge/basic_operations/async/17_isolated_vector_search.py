"""This cookbook shows how to enable vector search isolation for knowledge instances.

By default, vector search returns results from all documents in the vector database.
When `isolate_vector_search=True`, search results are filtered to only include documents
from the specific knowledge instance.

Note: This only works for content added AFTER enabling the flag. Existing content must be
re-indexed for vector search isolation to work.

1. Run: `python cookbook/07_knowledge/basic_operations/async/17_isolated_vector_search.py`
"""

import asyncio

from agno.agent import Agent
from agno.db.postgres.async_postgres import AsyncPostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


async def main():
    # Shared vector database for both knowledge instances
    shared_vector_db = PgVector(
        table_name="shared_vectors",
        db_url=db_url,
    )

    # Engineering Knowledge Base with isolated vector search
    engineering_kb = Knowledge(
        name="Engineering KB",
        vector_db=shared_vector_db,
        contents_db=AsyncPostgresDb(
            db_url=db_url, knowledge_table="engineering_contents"
        ),
        isolate_vector_search=True,  # Enable vector search filtering
    )

    # Sales Knowledge Base with isolated vector search
    sales_kb = Knowledge(
        name="Sales KB",
        vector_db=shared_vector_db,
        contents_db=AsyncPostgresDb(db_url=db_url, knowledge_table="sales_contents"),
        isolate_vector_search=True,  # Enable vector search filtering
    )

    # Add content to each knowledge base
    # The linked_to metadata is automatically added for filtering
    await engineering_kb.ainsert(
        name="Engineering CV",
        path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
        metadata={"department": "engineering"},
    )

    await sales_kb.ainsert(
        name="Sales CV",
        path="cookbook/07_knowledge/testing_resources/cv_2.pdf",
        metadata={"department": "sales"},
    )

    # Search results are now isolated to each knowledge instance
    # Even though they share the same vector database
    engineering_results = await engineering_kb.asearch("skills")
    sales_results = await sales_kb.asearch("skills")

    print(f"Engineering KB found {len(engineering_results)} results")
    print(f"Sales KB found {len(sales_results)} results")

    # Create agents with isolated knowledge
    engineering_agent = Agent(
        name="Engineering Agent",
        knowledge=engineering_kb,
        search_knowledge=True,
    )

    sales_agent = Agent(
        name="Sales Agent",
        knowledge=sales_kb,
        search_knowledge=True,
    )

    # Each agent only retrieves from its own knowledge
    await engineering_agent.aprint_response("What skills are listed?", markdown=True)
    await sales_agent.aprint_response("What skills are listed?", markdown=True)


if __name__ == "__main__":
    asyncio.run(main())
