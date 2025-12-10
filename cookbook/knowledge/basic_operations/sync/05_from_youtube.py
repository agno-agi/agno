"""This cookbook shows how to add content from a Youtube video to Knowledge.

1. Run: `python cookbook/agent_concepts/knowledge/05_from_youtube.py` to run the cookbook
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

# Add from Youtube link to knowledge. Youtube links are automatically detected and the reader is assigned automatically.
knowledge.add_content(
    name="Agents from Scratch",
    url="https://www.youtube.com/watch?v=nLkBNnnA8Ac",
    metadata={"user_tag": "Youtube video"},
)


agent = Agent(
    name="My Agent",
    description="Agno 2.0 Agent Implementation",
    knowledge=knowledge,
    search_knowledge=True,
    debug_mode=True,
)

agent.print_response(
    "What can you tell me about the building agents?",
    markdown=True,
)
