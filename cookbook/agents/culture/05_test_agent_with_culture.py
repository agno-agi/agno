"""This is just a sample file you can use to test run Agents with cultural knowledge.

There's no agenda to it, just test various inputs and see what the Agent says.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

db = SqliteDb(db_file="tmp/demo.db")

agent = Agent(
    db=db,
    # This flag will add the cultural knowledge to the agent's context
    add_culture_to_context=True,
    # This flag will enable the agent to add or update cultural knowledge automatically
    enable_agentic_culture=True,
    # This flag will run the CultureManager after every run
    # update_cultural_knowledge=True,
    model=Claude(id="claude-sonnet-4-5"),
)

agent.print_response(
    "Hi, how's life",
    stream=True,
    markdown=True,
)
