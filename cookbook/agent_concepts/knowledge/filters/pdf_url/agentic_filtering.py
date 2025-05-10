from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.lancedb import LanceDb

# Initialize LanceDB
# By default, it stores data in /tmp/lancedb
vector_db = LanceDb(
    table_name="recipes",
    uri="tmp/lancedb",  # You can change this path to store data elsewhere
)

# Step 1: Initialize knowledge base with documents and metadata
# ------------------------------------------------------------------------------
# When initializing the knowledge base, we can attach metadata that will be used for filtering
# This metadata can include user IDs, document types, dates, or any other attributes

knowledge_base = PDFUrlKnowledgeBase(
    urls=[
        {
            "url": "https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
            "metadata": {
                "cuisine": "Thai",
                "source": "Thai Cookbook",
                "region": "Southeast Asia",
            },
        },
        {
            "url": "https://agno-public.s3.amazonaws.com/recipes/cape_recipes_short_2.pdf",
            "metadata": {
                "cuisine": "Cape",
                "source": "Cape Cookbook",
                "region": "South Africa",
            },
        },
    ],
    vector_db=vector_db,
)

# Load all documents into the vector database
knowledge_base.load(recreate=True)

# Step 2: Query the knowledge base with Agent using filters from query automatically
# -----------------------------------------------------------------------------------

# Enable agentic filtering
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
    enable_agentic_knowledge_filters=True,
)

# Query for Jordan Mitchell's experience and skills with filters in query so that Agent can automatically pick them up
agent.print_response(
    "How to make Pad Thai, refer from document with cuisine Thai and source Thai Cookbook",
    markdown=True,
)
