"""
Entity Memory: The Four Tools
=============================
Entity memory is the agent's knowledge base about the world: the people,
projects, companies and systems around the user. The agent records through
four tools:

- remember_about: upsert an entity by name - facts, events, a description,
  and a note pointer. Resolution is the store's job (ids are slugified,
  "Sarah Chen" and "sarah chen" are one person).
- link_entities: record a relationship; the edge is stored on both entities.
- search_entities: find entities, or list them by recency (no query).
- forget: retire a fact, or archive a whole entity.

Corrections are just new facts: stating "radar shipped" retires "radar is
blocked on review" automatically (fact supersession), and facts render with
as-of dates so newer truth outranks older.

Run:
    .venvs/demo/bin/python cookbook/08_learning/04_entity_memory/01_the_four_tools.py
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
# A real deployment pins one namespace - that persistence is the point.
NAMESPACE = f"four_tools_{uuid4().hex[:6]}"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="You are a project tracker. Record what you are told, briefly.",
    learning=LearningMachine(
        entity_memory=EntityMemoryConfig(namespace=NAMESPACE),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    store = agent.learning_machine.entity_memory_store

    print("=" * 60)
    print("TURN 1: capture a project and a person")
    print("=" * 60)
    agent.print_response(
        "Track the radar project: it is blocked on security review, and Sarah Chen is the designer.",
        session_id="s1",
        stream=True,
    )

    print("=" * 60)
    print("TURN 2: a correction - supersession retires the stale fact")
    print("=" * 60)
    agent.print_response(
        "Good news: radar shipped v1 to production today.",
        session_id="s2",
        stream=True,
    )

    print("\n--- radar, live facts only (the blocked fact is retired, not deleted) ---")
    store.print(entity_id="radar", entity_type="project", namespace=NAMESPACE)

    print("=" * 60)
    print("TURN 3: recall in a fresh session - the entity directory plus")
    print("relevance recall inject what this turn is about")
    print("=" * 60)
    agent.print_response(
        "What do you know about radar?",
        session_id="s3",
        stream=True,
    )
