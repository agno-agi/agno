"""
This example shows how to use the session history to store the conversation history.
add_history_to_context flag is used to add the history to the messages.
num_history_runs is used to set the number of history runs to add to the messages.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team import Team

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions")

agent = Agent(model=OpenAIChat(id="gpt-5-mini"))

team = Team(
    model=OpenAIChat(id="gpt-5-mini"),
    members=[agent],
    db=db,
    add_history_to_context=True,
    num_history_messages=1,  # Only include the assistant response
)

team.print_response("Tell me a new interesting fact about space")
team.print_response("Repeat the last message, but make it much more concise")
