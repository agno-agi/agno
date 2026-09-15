"""
Entity Memory: The Four Tools
=============================
Entity memory is the agent's knowledge about the WORLD - the people,
projects, companies and systems around the user - as opposed to user
memory, which is about the user themselves.

It is AGENTIC-only: the agent records through four tools (remember_about,
link_entities, search_entities, forget), and the store does the librarian
work - ids are slugified from names, "Sarah Chen" and "sarah chen" resolve
to one person, and a correcting fact retires the stale one (supersession).

Deep dives: cookbook/08_learning/04_entity_memory/

Run:
    .venvs/demo/bin/python cookbook/08_learning/01_basics/5_entity_memory.py
"""

from uuid import uuid4

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import EntityMemoryConfig, LearningMachine
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Fresh per-run namespace so the demo starts clean on every execution.
NAMESPACE = f"basics_{uuid4().hex[:6]}"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="You are a sales assistant. Acknowledge notes briefly.",
    learning=LearningMachine(
        entity_memory=EntityMemoryConfig(namespace=NAMESPACE),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Note on Acme Corp: fintech startup in SF, about 50 people. "
        "Jane Smith is their CTO.",
        session_id="s1",
        stream=True,
    )

    # A fresh session: the entity directory plus relevance recall carry the
    # context - no tool call needed to answer.
    agent.print_response(
        "What do we know about Acme?",
        session_id="s2",
        stream=True,
    )
