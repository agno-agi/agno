"""
Use JSON files as the database for an Agent.
Useful for simple demos where performance is not critical.

Run `pip install ddgs openai` to install dependencies."""

from agno.agent import Agent
from agno.db.json import JsonDb
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# Setup the JSON database
db = JsonDb(db_path="tmp/json_db")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    session_id="session_storage",
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    num_history_runs=3,
)
agent.print_response("How many people live in France?")
agent.print_response("What is their national anthem called?")
agent.print_response("What have we been talking about?")
