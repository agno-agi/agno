"""This cookbook shows how to skip content if it already exists in the knowledge base.
By default, skip_if_exists=False, so content is re-indexed. Set skip_if_exists=True to skip.

1. Run: `python cookbook/08_knowledge/basic_operations/sync/11_skip_if_exists.py`
"""

from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

# Add from local file to the knowledge base
knowledge.insert(
    name="CV",
    path="cookbook/08_knowledge/testing_resources/cv_1.pdf",
    metadata={"user_tag": "Engineering Candidates"},
    skip_if_exists=True,  # Set to True to skip re-indexing existing content
)

# Add from local file to the knowledge base, but don't skip if it already exists
knowledge.insert(
    name="CV",
    path="cookbook/08_knowledge/testing_resources/cv_1.pdf",
    metadata={"user_tag": "Engineering Candidates"},
    skip_if_exists=False,
)
