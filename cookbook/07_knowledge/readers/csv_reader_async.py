import asyncio
from pathlib import Path

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="csv_documents",
        db_url=db_url,
    ),
    max_results=5,  # Number of results to return on search
)

# Initialize the Agent with the knowledge
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)


if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(knowledge.add_content_async(path=Path("data/csv")))

    # Create and use the agent
    asyncio.run(agent.aprint_response("What is the csv file about", markdown=True))
