import asyncio

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    # Table name: ai.arxiv_documents
    vector_db=PgVector(
        table_name="csv_documents",
        db_url=db_url,
    ),
    contents_db=PostgresDb(db_url=db_url),
)

# Initialize the Agent with the knowledge
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(
        knowledge.add_content_async(
            url="https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv"
        )
    )

    # Create and use the agent
    asyncio.run(
        agent.aprint_response("What genre of movies are present here?", markdown=True)
    )
