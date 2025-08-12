from agno.agent import Agent
from agno.knowledge.csv_url import CSVUrlKnowledgeBase
from agno.vectordb.lancedb import LanceDb

# Initialize LanceDB
# By default, it stores data in /tmp/lancedb
vector_db = LanceDb(
    table_name="recipes",
    uri="tmp/lancedb",  # You can change this path to store data elsewhere
)

# Step 1: Initialize knowledge base with documents and metadata
# ------------------------------------------------------------------------------
# When loading the knowledge base, we can attach metadata that will be used for filtering
# This metadata can include user IDs, document types, dates, or any other attributes

# Initialize knowledge base
knowledge_base = CSVUrlKnowledgeBase(
    vector_db=vector_db,
)

knowledge_base.load_document(
    url="https://agno-public.s3.us-east-1.amazonaws.com/demo_data/filters/filters_1.csv",
    metadata={
        "data_type": "sales",
        "quarter": "Q1",
        "year": 2024,
        "region": "north_america",
        "currency": "USD",
    },
    recreate=False,  # only use at the first run, True/False
)

knowledge_base.load_document(
    url="https://agno-public.s3.us-east-1.amazonaws.com/demo_data/filters/filters_2.csv",
    metadata={
        "data_type": "sales",
        "year": 2024,
        "region": "europe",
        "currency": "EUR",
    },
)


agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
    knowledge_filters={"region": "north_america", "data_type": "sales"},
)
agent.print_response(
    "Revenue performance and top selling products",
    markdown=True,
)
