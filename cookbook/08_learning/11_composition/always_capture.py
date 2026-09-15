"""
Composition: ALWAYS Capture Through the Manual Door
===================================================
The manual door has no automatic post-run extraction - the tools are the
capture mechanism. For hand-placed prompts AND ALWAYS-mode extraction,
capture_hook() returns a post_hooks-compatible callable around the machine's
capture pass (backgrounded on the agent's executor). An escape hatch, not a
third shape.

Run:
    .venvs/demo/bin/python cookbook/08_learning/11_composition/always_capture.py
"""

import time

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine
from agno.models.openai import OpenAIResponses

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ALWAYS-mode stores: extraction runs after the response, no agent tools needed.
# The manual door injects nothing: the machine needs its db AND its model
# given explicitly (extraction is a model call).
learning = LearningMachine(
    db=db, model=OpenAIResponses(id="gpt-5.5"), user_profile=True, user_memory=True
)

USER_ID = "composer@example.com"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions=["You are a helpful assistant."],
    post_hooks=[learning.capture_hook()],
    user_id=USER_ID,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "I'm Dana, a data engineer in Lisbon. I mostly work on our ClickHouse pipelines.",
        stream=True,
    )

    # The capture pass runs in the background; give it a moment before reading
    time.sleep(10)
    print("\n--- what ALWAYS capture extracted ---")
    learning.user_profile_store.print(user_id=USER_ID)
    learning.user_memory_store.print(user_id=USER_ID)
