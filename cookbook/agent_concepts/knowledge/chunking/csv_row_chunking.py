from pathlib import Path

from agno.agent import Agent
from agno.knowledge.chunking.row import RowChunking
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge_base = Knowledge(
    vector_db=PgVector(
        table_name="imdb_movies_row_chunking",
        db_url=db_url,
    ),
    chunking_strategy=RowChunking(),
)

knowledge_base.add_content(
    url="https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
)

# Initialize the Agent with the knowledge_base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

# Use the agent
agent.print_response("Tell me about the movie Guardians of the Galaxy", markdown=True)
