"""
Entity Memory: Links, Browse and Forget
=======================================
The graph half of entity memory:

- link_entities writes the edge on BOTH entities, so "who works on radar?"
  is answerable from either side, and recall shows linked entities by NAME
  (one-hop expansion): "radar - designed_by <- Sarah Chen".
- search_entities with no query lists entities by recency - the browse
  surface ("who works on what" needs enumeration).
- forget archives an entity: it leaves recall and the directory, stays
  findable by explicit search with an (archived) marker, and any later
  remember_about revives it.

Run:
    .venvs/demo/bin/python cookbook/08_learning/04_entity_memory/02_links_and_forget.py
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
NAMESPACE = f"links_{uuid4().hex[:6]}"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="You are a team tracker. Record what you are told, briefly.",
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
    print("TURN 1: capture people, projects and their links")
    print("=" * 60)
    agent.print_response(
        "Sarah Chen designs the radar project. Tom Alvarez runs the infra platform. "
        "Radar depends on the infra platform.",
        session_id="s1",
        stream=True,
    )

    print("\n--- the edge is on BOTH rows (reciprocal, with the far end's type) ---")
    store.print(entity_id="radar", entity_type="project", namespace=NAMESPACE)
    store.print(entity_id="sarah_chen", entity_type="person", namespace=NAMESPACE)

    print("=" * 60)
    print("TURN 2: browse - no query lists entities by recency")
    print("=" * 60)
    agent.print_response(
        "Who and what are you tracking right now? List everything.",
        session_id="s2",
        stream=True,
    )

    print("=" * 60)
    print("TURN 3: archive - 'we killed radar' is a status change")
    print("=" * 60)
    agent.print_response(
        "We cancelled the radar project. Archive it.",
        session_id="s3",
        stream=True,
    )

    print("\n--- archived: out of the directory, still searchable ---")
    print(store.search_entities(query="radar", namespace=NAMESPACE))
