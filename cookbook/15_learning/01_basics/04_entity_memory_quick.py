"""
Entity Memory Quick Start
=========================
Track external entities in 40 lines.

Entity Memory stores knowledge about things other than the user:
- Companies, people, projects
- Facts, events, relationships

Run:
    python cookbook/15_learning/basics/04_entity_memory_quick.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import EntityMemoryConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIChat

# Setup
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

# Agent with entity memory
agent = Agent(
    name="Entity Memory Agent",
    model=model,
    db=db,
    instructions="Track companies and people mentioned in conversations. Use entity tools to save information.",
    learning=LearningMachine(
        db=db,
        model=model,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)

# Demo
if __name__ == "__main__":
    user = "entity_user@example.com"

    # Track entity information
    print("\n--- Share entity information ---\n")
    agent.print_response(
        "Acme Corp is a fintech startup based in San Francisco. "
        "They use Python and PostgreSQL. Their CTO is Jane Smith. "
        "Please save this information.",
        user_id=user,
        session_id="s1",
        stream=True,
    )

    print("\n--- Query entities ---\n")
    agent.print_response(
        "What do we know about Acme Corp?",
        user_id=user,
        session_id="s2",
        stream=True,
    )
