"""This cookbook shows how to add content from a local file to the knowledge base.
1. Run: `python cookbook/agent_concepts/knowledge/01_from_path.py` to run the cookbook
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_store=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

knowledge.add_content(
    name="CV",
    path="cookbook/agent_concepts/knowledge/testing_resources/",
    metadata={"user_tag": "Engineering Candidates"},
)


knowledge.remove_vectors_by_metadata({"user_tag": "Engineering Candidates"})

# Add from local file to the knowledge base
knowledge.add_content(
    name="CV",
    path="cookbook/agent_concepts/knowledge/testing_resources/",
    metadata={"user_tag": "Engineering Candidates"},
)

knowledge.remove_vectors_by_name("CV")
