"""
User-Level Knowledge Filtering Example

This cookbook demonstrates how to use knowledge filters to restrict knowledge base searches to specific users, document types, or any other metadata attributes.

Key concepts demonstrated:
1. Loading documents with user-specific metadata
2. Filtering knowledge base searches by user ID
3. Combining multiple filter criteria
4. Comparing results across different filter combinations

You can pass filters in the following ways:
1. If you pass on Agent only, we use that for all runs
2. If you pass on run/print_response only, we use that for that run
3. If you pass on both, we override with the filters passed on run/print_response for that run
"""

from agno.agent import Agent
from agno.knowledge.json import JSONKnowledgeBase
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

knowledge_base = JSONKnowledgeBase(
    path=[
        {
            "path": "cookbook/agent_concepts/knowledge/filters/data/cv_1.json",
            "metadata": {
                "user_id": "jordan_mitchell",
                "document_type": "cv",
                "year": 2025,
            },
        },
        {
            "path": "cookbook/agent_concepts/knowledge/filters/data/cv_2.json",
            "metadata": {
                "user_id": "taylor_brooks",
                "document_type": "cv",
                "year": 2025,
            },
        },
        {
            "path": "cookbook/agent_concepts/knowledge/filters/data/cv_3.json",
            "metadata": {
                "user_id": "morgan_lee",
                "document_type": "cv",
                "year": 2025,
            },
        },
        {
            "path": "cookbook/agent_concepts/knowledge/filters/data/cv_4.json",
            "metadata": {
                "user_id": "casey_jordan",
                "document_type": "cv",
                "year": 2025,
            },
        },
        {
            "path": "cookbook/agent_concepts/knowledge/filters/data/cv_5.json",
            "metadata": {
                "user_id": "alex_rivera",
                "document_type": "cv",
                "year": 2025,
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
    knowledge_filters={"user_id": "jordan_mitchell"},
)

# Query for Jordan Mitchell' experience and skills
agent.print_response(
    "Tell me about Jordan Mitchell's experience and skills",
    markdown=True,
)

# # Option 2: Filters on the run/print_response
# agent = Agent(
#     knowledge=knowledge_base,
#     search_knowledge=True,
# )

# # Query for Taylor Brooks as a candidate
# agent.print_response(
#     "Tell me about Taylor Brooks as a candidate",
#     knowledge_filters={"user_id": "taylor_brooks"},
#     markdown=True,
# )
