from agno.agent import Agent
from agno.knowledge.csv import CSVKnowledgeBase
from agno.utils.media import (
    SampleDataFileExtension,
    download_knowledge_filters_sample_data,
)
from agno.vectordb.lancedb import LanceDb

# Download all sample sales files and get their paths
downloaded_csv_paths = download_knowledge_filters_sample_data(
    num_files=4, file_extension=SampleDataFileExtension.CSV
)

# Initialize LanceDB
# By default, it stores data in /tmp/lancedb
vector_db = LanceDb(
    table_name="recipes",
    uri="tmp/lancedb",  # You can change this path to store data elsewhere
)

# Step 1: Initialize knowledge base with documents and metadata
# ------------------------------------------------------------------------------
# When loading the knowledge base, we can attach metadata that will be used for filtering

# Initialize the PDFKnowledgeBase
knowledge_base = CSVKnowledgeBase(
    vector_db=vector_db,
    num_documents=5,
)

knowledge_base.load_document(
    path=downloaded_csv_paths[0],
    metadata={
        "data_type": "sales",
        "quarter": "Q1",
        "year": 2024,
        "region": "north_america",
        "currency": "USD",
    },
    recreate=True,  # Set to True only for the first run, then set to False
)

knowledge_base.load_document(
    path=downloaded_csv_paths[1],
    metadata={
        "data_type": "sales",
        "year": 2024,
        "region": "europe",
        "currency": "EUR",
    },
)

knowledge_base.load_document(
    path=downloaded_csv_paths[2],
    metadata={
        "data_type": "survey",
        "survey_type": "customer_satisfaction",
        "year": 2024,
        "target_demographic": "mixed",
    },
)

knowledge_base.load_document(
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
    knowledge=knowledge_base,
    search_knowledge=True,
    knowledge_filters={"region": "north_america", "data_type": "sales"},
)
agent.print_response(
    "Revenue performance and top selling products",
    markdown=True,
)
