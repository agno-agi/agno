"""
Field Labeled CSV Reader
========================

Demonstrates field-labeled CSV ingestion for movie metadata.
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.field_labeled_csv_reader import FieldLabeledCSVReader
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

reader = FieldLabeledCSVReader(
    chunk_title="Movie Information",
    field_names=[
        "Movie Rank",
        "Movie Title",
        "Genre",
        "Description",
        "Director",
        "Actors",
        "Year",
        "Runtime (Minutes)",
        "Rating",
        "Votes",
        "Revenue (Millions)",
        "Metascore",
    ],
    format_headers=True,
    skip_empty_fields=True,
)


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
knowledge_base = Knowledge(
    vector_db=PgVector(
        table_name="imdb_movies_field_labeled_readr",
        db_url=db_url,
    ),
)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
    instructions=[
        "You are a movie expert assistant.",
        "Use the search_knowledge_base tool to find detailed information about movies.",
        "The movie data is formatted in a field-labeled, human-readable way with clear field labels.",
        "Each movie entry starts with 'Movie Information' followed by labeled fields.",
        "Provide comprehensive answers based on the movie information available.",
    ],
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def main() -> None:
    knowledge_base.insert(
        url="https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
        reader=reader,
    )
    agent.print_response(
        "which movies are directed by Christopher Nolan",
        markdown=True,
        stream=True,
    )


if __name__ == "__main__":
    main()
