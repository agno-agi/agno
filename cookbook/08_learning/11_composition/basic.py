"""
Composition: The Manual Door
============================
learning= is the automatic door: the framework injects context, instructions
and tools for you. This folder is the other door - no learning= at all. You
place the three public surfaces yourself, the way FileSystem composes:

- learning.get_tools(...)      the capture tools
- learning.instructions()      the guidance block (how to use them)
- learning.build_context(...)  the recalled-data block

An agent with no learning= has no automatic capture: the manual door is
agentic by nature - the agent captures by calling the tools you handed it.

Run:
    .venvs/demo/bin/python cookbook/08_learning/11_composition/basic.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserMemoryConfig
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Build the machine, place its surfaces by hand
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# The manual door injects nothing: without learning= nobody hands the machine
# the agent's model, and capture is a model call.
learning = LearningMachine(
    db=db,
    model=OpenAIResponses(id="gpt-5.5"),
    user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
    entity_memory=True,
)

USER_ID = "composer@example.com"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[*learning.get_tools(user_id=USER_ID)],
    instructions=[
        "You are a research assistant.",
        learning.instructions(),
    ],
    user_id=USER_ID,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Remember that I prefer sources with primary data, and track the "
        "Meridian project - Priya runs it.",
        stream=True,
    )

    print("\n--- what the manual door placed (guidance + data) ---")
    print(learning.instructions()[:400])
    print("...")
    print(learning.build_context(user_id=USER_ID, message="what about meridian?"))
