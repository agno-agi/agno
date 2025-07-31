"""This cookbook shows how to add content from a local file to the knowledge base.
1. Run: `python cookbook/agent_concepts/knowledge/01_from_path.py` to run the cookbook
"""

from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.clickhouse import Clickhouse

vector_db = Clickhouse(
    table_name="recipe_documents",
    host="localhost",
    port=8123,
    username="ai",
    password="ai",
)
# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=vector_db,
)

# Add from local file to the knowledge base
knowledge.add_content(
    name="CV",
    path="cookbook_v2/knowledge/data/filters/cv_1.docx",
    metadata={"user_tag": "Engineering Candidates"},
    skip_if_exists=True,
)

knowledge.add_content(
    name="CV",
    path="cookbook_v2/knowledge/data/filters/cv_1.docx",
    metadata={"user_tag": "Engineering Candidates"},
    skip_if_exists=False,
    upsert=False,
)
