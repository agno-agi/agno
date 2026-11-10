"""
Composition: LearningMachine + FileSystem, One Deliberate Order
===============================================================
The point of the manual door: LearningMachine, FileSystem and your own
system prompt compose in one order you can read off the page. Nothing is
attached behind your back.

Run:
    .venvs/demo/bin/python cookbook/08_learning/11_composition/with_filesystem.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.fs import FileSystem
from agno.learn import LearningMachine, LearningMode, UserMemoryConfig
from agno.models.openai import OpenAIResponses

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

learning = LearningMachine(
    db=db,
    model=OpenAIResponses(id="gpt-5.5"),  # the manual door injects nothing
    user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
)
fs = FileSystem(db, namespace="composition-notes")

USER_ID = "composer@example.com"

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[*learning.get_tools(user_id=USER_ID), fs.tools()],
    instructions=[
        "You are a research assistant. Keep running notes on topics you research.",
        learning.instructions(),
        fs.instructions(),
    ],
    user_id=USER_ID,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Note down: the vector-db comparison is due Friday. And remember that "
        "I want conclusions first in every summary.",
        stream=True,
    )
    print("\n--- files ---")
    for f in fs.list():
        print(f.path)
