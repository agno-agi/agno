"""Use SQLite as the database for an Agent, selecting custom names for the tables.

Run `pip install ddgs sqlalchemy openai` to install dependencies.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb

# Setup the SQLite database
db = SqliteDb(
    db_file="tmp/data.db",
    # Selecting which tables to use
    session_table="agent_sessions",
    memory_table="agent_memories",
    metrics_table="agent_metrics",
)

# Setup a basic agent with the SQLite database
agent = Agent(
    db=db,
    enable_user_memories=True,
    add_history_to_context=True,
    add_datetime_to_context=True,
)

# The Agent sessions and runs will now be stored in SQLite
agent.print_response("How many people live in Canada?")
agent.print_response("And in Mexico?")
agent.print_response("List my messages one by one")
