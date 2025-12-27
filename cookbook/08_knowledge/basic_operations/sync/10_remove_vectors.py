"""This cookbook shows how to remove vectors from Knowledge.

You can remove vectors by metadata or by name.

1. Run: `python cookbook/agent_concepts/knowledge/10_remove_vectors.py` to run the cookbook
"""

from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

knowledge.add_content(
    name="CV",
    path="cookbook/knowledge/testing_resources/cv_1.pdf",
    metadata={"user_tag": "Engineering Candidates"},
)


knowledge.remove_vectors_by_metadata({"user_tag": "Engineering Candidates"})

# Add from local file to the knowledge base
knowledge.add_content(
    name="CV",
    path="cookbook/knowledge/testing_resources/cv_1.pdf",
    metadata={"user_tag": "Engineering Candidates"},
)

knowledge.remove_vectors_by_name("CV")
