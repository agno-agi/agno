"""
User-Level Knowledge Filtering Example with PDF URLs

This cookbook demonstrates how to use knowledge filters with PDF documents accessed via URLs,
showing how to restrict knowledge base searches to specific cuisines, sources, or any other metadata attributes.

Key concepts demonstrated:
1. Loading PDF documents from URLs with specific metadata
2. Filtering knowledge base searches by cuisine type
3. Combining multiple filter criteria
4. Comparing results across different filter combinations

You can pass filters in the following ways:
1. If you pass on Agent only, we use that for all runs
2. If you pass on run/print_response only, we use that for that run
3. If you pass on both, we override with the filters passed on run/print_response for that run
"""

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
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

# Step 2: Query the knowledge base with different filter combinations
# ------------------------------------------------------------------------------

# Option 1: Filters on the Agent
# Initialize the Agent with the knowledge base and filters
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
    # This will only return information from documents with Thai cuisine
    knowledge_filters={"cuisine": "Thai"},
)

# Query for Thai recipes
agent.print_response(
    "Tell me how to make Pad Thai",
    markdown=True,
)

# # Option 2: Filters on the run/print_response
# agent = Agent(
#     knowledge=knowledge_base,
#     search_knowledge=True,
# )

# # Query for Cape Malay recipes
# agent.print_response(
#     "Tell me how to make Cape Malay Curry",
#     knowledge_filters={"cuisine": "Cape"},
#     markdown=True,
# )
