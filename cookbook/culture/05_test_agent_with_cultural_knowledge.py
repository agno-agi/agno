"""
This is just a sample file you can use to test run Agents with cultural knowledge.

There's no agenda to it, just test various inputs and see what the Agent says.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

db = SqliteDb(db_file="tmp/demo.db")

agent = Agent(
    db=db,
    model=Claude(id="claude-sonnet-4-5"),
    update_cultural_knowledge=True,
)

agent.print_response(
    "Hi, how's life",
    stream=True,
    markdown=True,
)
