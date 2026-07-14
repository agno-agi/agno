"""
Session Summary
===============

Demonstrates configuring session summaries for an agent using PostgresDb.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.session.summary import SessionSummaryManager  # noqa: F401

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, session_table="sessions")

# Method 1: Set enable_session_summaries to True
#
# agent = Agent(
#     model=OpenAIChat(id="gpt-5.2"),
#     db=db,
#     enable_session_summaries=True,
#     session_id="session_summary",
#     add_session_summary_to_context=True,
# )
#
# agent.print_response("Hi my name is John and I live in New York")
# agent.print_response("I like to play basketball and hike in the mountains")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# Method 2: Set session_summary_manager
session_summary_manager = SessionSummaryManager(model=OpenAIChat(id="gpt-5.2"))
agent = Agent(
    model=OpenAIChat(id="gpt-5.2"),
    db=db,
    session_id="session_summary",
    session_summary_manager=session_summary_manager,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Hi my name is John and I live in New York")
    agent.print_response("I like to play basketball and hike in the mountains")
