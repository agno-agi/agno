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
# When loading the knowledge base, we can attach metadata that will be used for filtering
# This metadata can include user IDs, document types, dates, or any other attributes

# Initialize the JSONKnowledgeBase
knowledge_base = JSONKnowledgeBase(
    vector_db=vector_db,
    num_documents=5,
)

knowledge_base.load_document(
    path="cookbook/agent_concepts/knowledge/filters/data/cv_1.json",
    metadata={"user_id": "jordan_mitchell", "document_type": "cv", "year": 2025},
    recreate=True,  # Set to True only for the first run, then set to False
)

# Load second document with user_2 metadata
knowledge_base.load_document(
    path="cookbook/agent_concepts/knowledge/filters/data/cv_2.json",
    metadata={"user_id": "taylor_brooks", "document_type": "cv", "year": 2025},
)

# Load second document with user_3 metadata
knowledge_base.load_document(
    path="cookbook/agent_concepts/knowledge/filters/data/cv_3.json",
    metadata={"user_id": "morgan_lee", "document_type": "cv", "year": 2025},
)

# Load second document with user_4 metadata
knowledge_base.load_document(
    path="cookbook/agent_concepts/knowledge/filters/data/cv_4.json",
    metadata={"user_id": "casey_jordan", "document_type": "cv", "year": 2025},
)

# Load second document with user_5 metadata
knowledge_base.load_document(
    path="cookbook/agent_concepts/knowledge/filters/data/cv_5.json",
    metadata={"user_id": "alex_rivera", "document_type": "cv", "year": 2025},
)

# Step 2: Query the knowledge base with different filter combinations
# ------------------------------------------------------------------------------
# Uncomment the example you want to run

# Option 1: Filters on the Agent
# Initialize the Agent with the knowledge base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
    knowledge_filters={"user_id": "jordan_mitchell"},
)
agent.print_response(
    "Tell me about Jordan Mitchell's experience and skills",
    markdown=True,
)

# agent = Agent(
#     knowledge=knowledge_base,
#     search_knowledge=True,
# )
# agent.print_response(
#     "Tell me about Jordan Mitchell's experience and skills",
#     knowledge_filters = {"user_id": "jordan_mitchell"},
#     markdown=True,
# )
