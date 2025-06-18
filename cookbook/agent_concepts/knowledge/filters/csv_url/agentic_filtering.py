from agno.agent import Agent
from agno.knowledge.csv_url import CSVUrlKnowledgeBase
from agno.vectordb.lancedb import LanceDb

# Initialize LanceDB
# By default, it stores data in /tmp/lancedb
vector_db = LanceDb(
    table_name="recipes",
    uri="tmp/lancedb",  # You can change this path to store data elsewhere
)

# Step 1: Initialize knowledge base with URLs and metadata
# ------------------------------------------------------------------------------
# When initializing the knowledge base, we can attach metadata that will be used for filtering
# This metadata can include cuisine type, source, region, or any other attributes

knowledge_base = CSVUrlKnowledgeBase(
    urls=[
        {
            "url": "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/filters/filters_1.csv",
            "metadata": {
                "data_type": "sales",
                "quarter": "Q1",
                "year": 2024,
                "region": "north_america",
                "currency": "USD",
            },
        },
        {
            "url": "https://agno-public.s3.us-east-1.amazonaws.com/demo_data/filters/filters_2.csv",
            "metadata": {
                "data_type": "sales",
                "year": 2024,
                "region": "europe",
                "currency": "EUR",
            },
        },
    ],
    vector_db=vector_db,
)

# Load all documents into the vector database
knowledge_base.load(recreate=True)

# Step 2: Query the knowledge base with different filter combinations
# ------------------------------------------------------------------------------

agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
    enable_agentic_knowledge_filters=True,
)

agent.print_response(
    "Tell me about revenue performance and top selling products for region 'north_america' and data_type 'sales'",
    markdown=True,
)
