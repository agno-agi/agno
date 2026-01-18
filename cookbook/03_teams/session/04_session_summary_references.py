"""
This example shows how to use the `add_session_summary_to_context` parameter in the Team config to
add session summaries to the Team context.

Start the postgres db locally on Docker by running: cookbook/scripts/run_pgvector.sh
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.team import Team

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions")

agent = Agent(
    model=OpenAIChat(id="o3-mini"),
)

team = Team(
    model=OpenAIChat(id="o3-mini"),
    members=[agent],
    db=db,
    enable_session_summaries=True,
)

# This will create a new session summary
team.print_response(
    "My name is John Doe and I like to hike in the mountains on weekends.",
)

# You can use existing session summaries from session storage without creating or updating any new ones.
team = Team(
    model=OpenAIChat(id="o3-mini"),
    db=db,
    session_id="session_summary",
    add_session_summary_to_context=True,
    members=[agent],
)

team.print_response("I also like to play basketball.")

# Alternatively, you can create a new session summary without adding the session summary to context.

# team = Team(
#     model=OpenAIChat(id="o3-mini"),
#     db=db,
#     session_id="session_summary",
#     enable_session_summaries=True,
#     add_session_summary_to_context=False,
# )

# team.print_response("I also like to play basketball.")
