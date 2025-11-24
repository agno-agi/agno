import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

vector_db = PgVector(table_name="recipes", db_url=db_url)

knowledge_base = Knowledge(
    vector_db=vector_db,
)

agent = Agent(knowledge=knowledge_base)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(
        knowledge_base.add_content_async(
            url="https://docs.agno.com/basics/agents/overview.md"
        )
    )

    # Create and use the agent
    asyncio.run(
        agent.aprint_response("What is the purpose of an Agno Agent?", markdown=True)
    )
