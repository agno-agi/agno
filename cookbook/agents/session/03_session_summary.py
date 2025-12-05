"""
This example shows how to use the session summary to store the conversation summary.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.session.summary import SessionSummaryManager  # noqa: F401

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions")

# Method 1: Set enable_session_summaries to True

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    enable_session_summaries=True,
    session_id="session_123",
)

agent.print_response("Hi my name is John and I live in New York")
agent.print_response("I like to play basketball and hike in the mountains")

print(agent.get_session_summary(session_id="session_123"))

# Method 2: Set session_summary_manager

# session_summary_manager = SessionSummaryManager(model=OpenAIChat(id="gpt-4o-mini"))

# agent = Agent(
#     model=OpenAIChat(id="gpt-4o-mini"),
#     db=db,
#     session_id="session_summary",
#     session_summary_manager=session_summary_manager,
# )

# agent.print_response("Hi my name is John and I live in New York")
# agent.print_response("I like to play basketball and hike in the mountains")
