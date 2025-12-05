from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.utils.media import (
    SampleDataFileExtension,
    download_knowledge_filters_sample_data,
)
from agno.vectordb.pgvector import PgVector

# Download all sample sales files and get their paths
downloaded_csv_paths = download_knowledge_filters_sample_data(
    num_files=4, file_extension=SampleDataFileExtension.CSV
)

# Initialize LanceDB
# By default, it stores data in /tmp/lancedb
vector_db = PgVector(
    table_name="recipes",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Step 1: Initialize knowledge base with documents and metadata
# ------------------------------------------------------------------------------
# When loading the knowledge base, we can attach metadata that will be used for filtering

# Initialize Knowledge
knowledge = Knowledge(
    vector_db=vector_db,
    contents_db=PostgresDb(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        knowledge_table="knowledge_contents",
    ),
    max_results=5,
)

knowledge.add_content(
    path=downloaded_csv_paths[0],
    metadata={
        "data_type": "sales",
        "quarter": "Q1",
        "year": 2024,
        "region": "north_america",
        "currency": "USD",
    },
)

knowledge.add_content(
    path=downloaded_csv_paths[1],
    metadata={
        "data_type": "sales",
        "year": 2024,
        "region": "europe",
        "currency": "EUR",
    },
)

knowledge.add_content(
    path=downloaded_csv_paths[2],
    metadata={
        "data_type": "survey",
        "survey_type": "customer_satisfaction",
        "year": 2024,
        "target_demographic": "mixed",
    },
)

knowledge.add_content(
    path=downloaded_csv_paths[3],
    metadata={
        "data_type": "financial",
        "sector": "technology",
        "year": 2024,
        "report_type": "quarterly_earnings",
    },
)

# Step 2: Query the knowledge base with different filter combinations
# ------------------------------------------------------------------------------
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
    knowledge_filters={"region": "north_america", "data_type": "sales"},
)
agent.print_response(
    "Revenue performance and top selling products",
    markdown=True,
)
