"""
Multiple Knowledge Instances in AgentOS
============================================================

This cookbook demonstrates how to configure multiple Knowledge instances
in AgentOS, each with isolated content.

Key Concepts:
- Multiple Knowledge instances can share the same vector_db and contents_db
- Each instance is identified by its `name` property
- Content is isolated per instance via the `linked_to` field
- Instances with the same name but different databases are treated as separate
- The /knowledge/config endpoint returns all registered instances
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

# Database connections
contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents",
)
vector_db = PgVector(
    table_name="knowledge_vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Create Knowledge instances
company_knowledge = Knowledge(
    name="Company Knowledge Base",
    description="Unified knowledge from multiple sources",
    contents_db=contents_db,
    vector_db=vector_db,
    # content_sources=[sharepoint, github_docs, azure_blob],
)

personal_knowledge = Knowledge(
    name="Personal Knowledge Base",
    description="Unified knowledge from multiple sources",
    contents_db=contents_db,
    vector_db=vector_db,
    # content_sources=[sharepoint, github_docs, azure_blob],
)

company_knowledge_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents2",
)

company_knowledge_additional = Knowledge(
    name="Company Knowledge Base",
    description="Unified knowledge from multiple sources",
    contents_db=company_knowledge_db,
    vector_db=vector_db,
    # content_sources=[sharepoint, github_docs, azure_blob],
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=company_knowledge,
    search_knowledge=True,
)

agent_os = AgentOS(
    knowledge=[company_knowledge, company_knowledge_additional, personal_knowledge],
    agents=[agent],
)
app = agent_os.get_app()

# ============================================================================
# Run AgentOS
# ============================================================================
if __name__ == "__main__":
    # Serves a FastAPI app exposed by AgentOS. Use reload=True for local dev.
    agent_os.serve(app="multiple_knowledge_instances:app", reload=True)
