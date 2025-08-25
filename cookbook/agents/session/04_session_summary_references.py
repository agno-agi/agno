"""
This example shows how to use the `add_session_summary_to_context` parameter in the Agent config to
add session summaries to the Agent context.

Start the postgres db locally on Docker by running: cookbook/scripts/run_pgvector.sh
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions")

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    session_id="session_summary",
    enable_session_summaries=True,
)

# This will create a new session summary
agent.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
)

# You can use existing session summaries from session storage without creating or updating any new ones.
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    session_id="session_summary",
    add_session_summary_to_context=True,
)

agent.print_response("I also like to play basketball.")

# Alternatively, you can create a new session summary without adding the session summary to context.

# agent = Agent(
#     model=OpenAIChat(id="gpt-4o"),
#     db=db,
#     session_id="session_summary",
#     enable_session_summaries=True,
#     add_session_summary_to_context=False,
# )

# agent.print_response("I also like to play basketball.")
