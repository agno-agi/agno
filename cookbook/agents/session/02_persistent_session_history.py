"""
This example shows how to use the session history to store the conversation history.
add_history_to_context flag is used to add the history to the messages.
num_history_runs is used to set the number of history runs to add to the messages.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    add_history_to_context=True,
    num_history_runs=3,
)

agent.print_response("Tell me a new interesting fact about space")

agent.print_response("What was my first message?")
