from pathlib import Path

from agno.agent import Agent
from agno.knowledge.chunking.field_labeled import FieldLabeledChunking
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.csv_reader import CSVReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

chunker = FieldLabeledChunking(
    chunk_title="🎬 Movie Information",
    field_names=["Movie Rank", "Movie Title", "Genre", "Description"],
)

knowledge_base = Knowledge(
 
    vector_db=PgVector(
        table_name="imdb_movies_field_labeled_chunking",
        db_url=db_url,
    ),
)

reader = CSVReader(
    chunking_strategy=chunker,
)

knowledge_base.add_content(
    url="https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
    # reader=reader,
)

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
