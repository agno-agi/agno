"""This cookbook shows how to use include and exclude filters when adding content to Knowledge.

1. Run: `python cookbook/agent_concepts/knowledge/08_include_exclude_files.py` to run the cookbook
"""

from agno.agent import Agent
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

# Add from local file to the knowledge base
knowledge.add_content(
    name="CV",
    path="cookbook/knowledge/testing_resources",
    metadata={"user_tag": "Engineering Candidates"},
    # Only include PDF files
    include=["*.pdf"],
    # Don't include files that match this pattern
    exclude=["*cv_5*"],
)

agent = Agent(
    name="My Agent",
    description="Agno 2.0 Agent Implementation",
    knowledge=knowledge,
    search_knowledge=True,
    debug_mode=True,
)

agent.print_response(
    "Who is the best candidate for the role of a software engineer?",
    markdown=True,
)

# Alex River is not in the knowledge base, so the Agent should not find any information about him
agent.print_response(
    "Do you think Alex Rivera is a good candidate?",
    markdown=True,
)
