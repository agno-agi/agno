"""This cookbook shows how to enable vector search isolation for knowledge instances.

By default, vector search returns results from all documents in the vector database.
When `isolate_vector_search=True`, search results are filtered to only include documents
from the specific knowledge instance.

Note: This only works for content added AFTER enabling the flag. Existing content must be
re-indexed for vector search isolation to work.

1. Run: `python cookbook/07_knowledge/basic_operations/sync/18_isolated_vector_search.py`
"""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Shared vector database for both knowledge instances
shared_vector_db = PgVector(
    table_name="shared_vectors",
    db_url=db_url,
)

# Engineering Knowledge Base with isolated vector search
engineering_kb = Knowledge(
    name="Engineering KB",
    vector_db=shared_vector_db,
    contents_db=PostgresDb(db_url=db_url, knowledge_table="engineering_contents"),
    isolate_vector_search=True,  # Enable vector search filtering
)

# Sales Knowledge Base with isolated vector search
sales_kb = Knowledge(
    name="Sales KB",
    vector_db=shared_vector_db,
    contents_db=PostgresDb(db_url=db_url, knowledge_table="sales_contents"),
    isolate_vector_search=True,  # Enable vector search filtering
)

# Add content to each knowledge base
# The linked_to metadata is automatically added for filtering
engineering_kb.insert(
    name="Engineering CV",
    path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
    metadata={"department": "engineering"},
)

sales_kb.insert(
    name="Sales CV",
    path="cookbook/07_knowledge/testing_resources/cv_2.pdf",
    metadata={"department": "sales"},
)

# Search results are now isolated to each knowledge instance
# Even though they share the same vector database
engineering_results = engineering_kb.search("skills")
sales_results = sales_kb.search("skills")

print(f"Engineering KB found {len(engineering_results)} results")
print(f"Sales KB found {len(sales_results)} results")

# Create agents with isolated knowledge
engineering_agent = Agent(
    name="Engineering Agent",
    knowledge=engineering_kb,
    search_knowledge=True,
)

sales_agent = Agent(
    name="Sales Agent",
    knowledge=sales_kb,
    search_knowledge=True,
)

# Each agent only retrieves from its own knowledge
engineering_agent.print_response("What skills are listed?", markdown=True)
sales_agent.print_response("What skills are listed?", markdown=True)
