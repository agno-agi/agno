import asyncio

from agno.agent import Agent
from agno.knowledge.s3.text import S3TextKnowledgeBase
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge_base = S3TextKnowledgeBase(
    bucket_name="agno-public",
    key="recipes/recipes.docx",
    vector_db=PgVector(table_name="recipes", db_url=db_url),
)


agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(agent.knowledge.aload(recreate=True))

    asyncio.run(agent.aprint_response("How to make Hummus?", markdown=True))
