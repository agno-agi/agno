"""Demonstrates knowledge isolation with isolate_vector_search flag.

When multiple Knowledge instances share the same vector database, you can use
the `isolate_vector_search` flag to ensure each instance only searches its own data.

Behavior:
- isolate_vector_search=False (default): Searches ALL vectors in the database.
  This is backwards-compatible with existing data that doesn't have linked_to metadata.

- isolate_vector_search=True: Only searches vectors that have matching linked_to metadata.
  Documents inserted with this flag will have linked_to set to the Knowledge instance name.
  Searches will filter to only return documents with matching linked_to.

IMPORTANT: If you have existing production data and want to enable isolation, you will
need to re-index your data with isolate_vector_search=True to add the linked_to metadata.
Existing documents without linked_to metadata will NOT be found when isolation is enabled.

Run: `python cookbook/07_knowledge/basic_operations/async/05_isolate_vector_search.py`
"""

import asyncio

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# Shared database connections
contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents",
)

vector_db = PgVector(
    table_name="vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# -----------------------------------------------------------------------------
# Example 1: Default behavior (isolate_vector_search=False)
# Searches across ALL vectors in the database, regardless of which Knowledge
# instance inserted them. This is the default for backwards compatibility.
# -----------------------------------------------------------------------------

knowledge_shared = Knowledge(
    name="Shared Knowledge",
    description="This knowledge instance searches all vectors",
    vector_db=vector_db,
    contents_db=contents_db,
    # isolate_vector_search=False is the default
)

# -----------------------------------------------------------------------------
# Example 2: Isolated behavior (isolate_vector_search=True)
# Only searches vectors that were inserted by this Knowledge instance.
# Documents are tagged with linked_to metadata during insert.
# -----------------------------------------------------------------------------

knowledge_isolated = Knowledge(
    name="Isolated Knowledge",
    description="This knowledge instance only searches its own vectors",
    vector_db=vector_db,
    contents_db=contents_db,
    isolate_vector_search=True,  # Enable isolation
)


async def main():
    # Insert a document with isolation enabled
    # This document will have linked_to="Isolated Knowledge" in its metadata
    await knowledge_isolated.ainsert(
        name="CV",
        path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
        metadata={"user_tag": "Engineering Candidates"},
    )

    # Agent using isolated knowledge - only finds documents from this instance
    agent_isolated = Agent(
        name="Isolated Agent",
        knowledge=knowledge_isolated,
        search_knowledge=True,
        debug_mode=True,
    )

    print("--- Agent with isolate_vector_search=True ---")
    print("Only searches vectors with linked_to='Isolated Knowledge'")
    agent_isolated.print_response(
        "What skills does Jordan Mitchell have?",
        markdown=True,
    )

    # Agent using shared knowledge - finds ALL documents in the vector db
    agent_shared = Agent(
        name="Shared Agent",
        knowledge=knowledge_shared,
        search_knowledge=True,
        debug_mode=True,
    )

    print("--- Agent with isolate_vector_search=False (default) ---")
    print("Searches all vectors in the database")
    agent_shared.print_response(
        "What skills does Jordan Mitchell have?",
        markdown=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
