from pathlib import Path

from agno.agent import Agent
from agno.document.chunking.field_labeled_csv import FieldLabeledCSVChunking
from agno.knowledge.csv_url import CSVUrlKnowledgeBase
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a field-labeled CSV chunking strategy
# When title_template is provided, the first row is automatically treated as headers
field_labeled_chunking = FieldLabeledCSVChunking(
    chunk_title="🎬 Movie Information",
    field_names=["Movie Rank", "Movie Title", "Genre", "Description"],
)

knowledge_base = CSVUrlKnowledgeBase(
    urls=[
        "https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
    ],
    vector_db=PgVector(
        table_name="imdb_movies_field_labeled_chunking",
        db_url=db_url,
    ),
    chunking_strategy=field_labeled_chunking,  # Use the chunking strategy instead of custom reader
)

# Load the knowledge base
knowledge_base.load(recreate=False)

# Initialize the Agent with the knowledge_base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
    instructions=[
        "You are a movie expert assistant.",
        "Use the search_knowledge_base tool to find detailed information about movies.",
        "The movie data is formatted in a field-labeled, human-readable way with clear field labels.",
        "Each movie entry starts with '🎬 Movie Information' followed by labeled fields.",
        "Provide comprehensive answers based on the movie information available.",
    ],
)

agent.print_response(
    "which movies are directed by Christopher Nolan", markdown=True, stream=True
)
