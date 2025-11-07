import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.csv_reader import CSVReader
from agno.models.openai import OpenAIChat
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
    model=OpenAIChat(id="gpt-4.1-mini"),
    knowledge=knowledge,
    search_knowledge=True,
)


if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(
        knowledge.add_content_async(
            url="https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
            reader=CSVReader(encoding="gb2312"),
        )
    )

    # Create and use the agent
    asyncio.run(agent.aprint_response("What is the csv file about", markdown=True))
