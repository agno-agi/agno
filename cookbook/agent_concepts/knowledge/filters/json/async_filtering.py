import asyncio

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

# Step 2: Query the knowledge base with different filter combinations
# ------------------------------------------------------------------------------

# Option 1: Filters on the Agent
# Initialize the Agent with the knowledge base and filters
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

if __name__ == "__main__":
    # Load all documents into the vector database
    asyncio.run(knowledge_base.aload(recreate=True))

    # Query for Alex Rivera's experience and skills
    asyncio.run(
        agent.aprint_response(
            "Tell me about Jordan Mitchell's experience and skills",
            knowledge_filters={"user_id": "jordan_mitchell"},
            markdown=True,
        )
    )
