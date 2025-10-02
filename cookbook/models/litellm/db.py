"""Run `pip install ddgs openai` to install dependencies."""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.litellm import LiteLLM
from agno.tools.duckduckgo import DuckDuckGoTools

# Setup the database
db = SqliteDb(
    db_file="tmp/data.db",
)

# Add storage to the Agent
agent = Agent(
    model=LiteLLM(id="gpt-4o"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
)

agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
