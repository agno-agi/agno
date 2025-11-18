"""
This example demonstrates how to use knowledge filter expressions with agents.

Knowledge filters allow you to restrict knowledge searches to specific documents
or metadata criteria, enabling personalized and contextual responses.
"""

from agno.agent import Agent
from agno.filters import AND, EQ, IN, NOT
from agno.knowledge.knowledge import Knowledge
from agno.utils.media import (
    SampleDataFileExtension,
    download_knowledge_filters_sample_data,
)
from agno.vectordb.pgvector import PgVector

# Download all sample sales documents and get their paths
downloaded_csv_paths = download_knowledge_filters_sample_data(
    num_files=4, file_extension=SampleDataFileExtension.CSV
)

# Initialize PGVector
vector_db = PgVector(
    table_name="recipes",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Step 1: Initialize knowledge with documents and metadata
# -----------------------------------------------------------------------------
knowledge = Knowledge(
    name="CSV Knowledge Base",
    description="A knowledge base for CSV files",
    vector_db=vector_db,
)

# Load all documents into the vector database
knowledge.add_contents(
    [
        {
            "path": downloaded_csv_paths[0],
            "metadata": {
                "data_type": "sales",
                "quarter": "Q1",
                "year": 2024,
                "region": "north_america",
                "currency": "USD",
            },
        },
        {
            "path": downloaded_csv_paths[1],
            "metadata": {
                "data_type": "sales",
                "year": 2024,
                "region": "europe",
                "currency": "EUR",
            },
        },
        {
            "path": downloaded_csv_paths[2],
            "metadata": {
                "data_type": "survey",
                "survey_type": "customer_satisfaction",
                "year": 2024,
                "target_demographic": "mixed",
            },
        },
        {
            "path": downloaded_csv_paths[3],
            "metadata": {
                "data_type": "financial",
                "sector": "technology",
                "year": 2024,
                "report_type": "quarterly_earnings",
            },
        },
    ],
)

# Step 2: Query the knowledge base with different filter combinations
# ------------------------------------------------------------------------------
sales_agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

print("--------------------------------")
print("Using IN operator")
sales_agent.print_response(
    "Describe revenue performance for the region",
    knowledge_filters=[(IN("region", ["north_america"]))],
    markdown=True,
)

print("--------------------------------")
print("Using NOT operator")
sales_agent.print_response(
    "Describe revenue performance for the region",
    knowledge_filters=[NOT(IN("region", ["north_america"]))],
    markdown=True,
)

print("--------------------------------")
print("Using AND operator")
sales_agent.print_response(
    "Describe revenue performance for the region",
    knowledge_filters=[
        AND(EQ("data_type", "sales"), NOT(EQ("region", "north_america")))
    ],
    markdown=True,
)
