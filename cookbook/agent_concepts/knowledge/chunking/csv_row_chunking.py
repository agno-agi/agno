from pathlib import Path

from agno.agent import Agent
from agno.document.chunking.row import RowChunking
from agno.knowledge.csv_url import CSVUrlKnowledgeBase
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge_base = CSVUrlKnowledgeBase(
    urls=[
        "https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
    ],
    vector_db=PgVector(
        table_name="imdb_movies_row_chunking",
        db_url=db_url,
    ),
    chunking_strategy=RowChunking(),
)
# Load the knowledge base
knowledge_base.load(recreate=False)

# Initialize the Agent with the knowledge_base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

# Use the agent
agent.print_response("Tell me about the movie Guardians of the Galaxy", markdown=True)
