"""
Composition: The Data Block via additional_context
==================================================
build_context() returns the recalled-data block on its own, for when you
want the data injected but not the tools - a read-only view of what the
machine knows, placed exactly where you choose.

Run:
    .venvs/demo/bin/python cookbook/08_learning/11_composition/context_block.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserMemoryConfig
from agno.models.openai import OpenAIResponses

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

learning = LearningMachine(
    db=db,
    model=OpenAIResponses(id="gpt-5.5"),  # the manual door injects nothing
    user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
)

USER_ID = "composer@example.com"

# Seed a memory through the data API so the read-only agent has something to see
store = learning.user_memory_store
store.get_tools(user_id=USER_ID)[0]("Prefers conclusions first, then supporting detail")

# No learning=, no tools: just the data block, placed as additional context
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    additional_context=learning.build_context(user_id=USER_ID),
    user_id=USER_ID,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response("Summarize why teams adopt vector databases.", stream=True)
