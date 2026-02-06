"""This cookbook shows how to isolate content between knowledge instances sharing the same database.

When multiple Knowledge instances share the same contents_db or vector_db, you can isolate their
content so each instance only sees its own data.

1. Run: `python cookbook/07_knowledge/basic_operations/async/16_knowledge_isolation.py`
"""

import asyncio

from agno.agent import Agent
from agno.db.postgres.async_postgres import AsyncPostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


async def main():
    # Shared database for content tracking
    shared_contents_db = AsyncPostgresDb(
        db_url=db_url,
        knowledge_table="knowledge_contents",
    )

    # Company Knowledge Base
    # Content listing is automatically isolated by knowledge instance name
    company_kb = Knowledge(
        name="Company Knowledge Base",  # Unique name required for isolation
        vector_db=PgVector(table_name="company_vectors", db_url=db_url),
        contents_db=shared_contents_db,
    )

    # Personal Knowledge Base
    personal_kb = Knowledge(
        name="Personal Knowledge Base",  # Different unique name
        vector_db=PgVector(table_name="personal_vectors", db_url=db_url),
        contents_db=shared_contents_db,
    )

    # Add content to each knowledge base
    await company_kb.ainsert(
        name="Company Handbook",
        path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
        metadata={"type": "company"},
    )

    await personal_kb.ainsert(
        name="Personal Notes",
        path="cookbook/07_knowledge/testing_resources/cv_2.pdf",
        metadata={"type": "personal"},
    )

    # Each instance only sees its own content
    company_contents, company_count = await company_kb.aget_content()
    personal_contents, personal_count = await personal_kb.aget_content()

    print(f"Company KB has {company_count} items")
    print(f"Personal KB has {personal_count} items")

    # Create agents with isolated knowledge
    company_agent = Agent(
        name="Company Agent",
        knowledge=company_kb,
        search_knowledge=True,
    )

    personal_agent = Agent(
        name="Personal Agent",
        knowledge=personal_kb,
        search_knowledge=True,
    )

    # Each agent only searches its own knowledge base
    await company_agent.aprint_response("What skills are listed for the candidates in your knowledge base?", markdown=True)
    await personal_agent.aprint_response("What skills are listed for the candidates in your knowledge base?", markdown=True)


if __name__ == "__main__":
    asyncio.run(main())
