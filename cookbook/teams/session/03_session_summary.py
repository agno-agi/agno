"""
This example shows how to use the session summary to store the conversation summary.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.session.summary import SessionSummaryManager  # noqa: F401
from agno.team import Team

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions")

# Method 1: Set enable_session_summaries to True

agent = Agent(
    model=OpenAIChat(id="o3-mini"),
)

team = Team(
    model=OpenAIChat(id="o3-mini"),
    members=[agent],
    db=db,
    enable_session_summaries=True,
)

team.print_response("Hi my name is John and I live in New York")
team.print_response("I like to play basketball and hike in the mountains")

# Method 2: Set session_summary_manager

# session_summary_manager = SessionSummaryManager(model=OpenAIChat(id="o3-mini"))

# agent = Agent(
#     model=OpenAIChat(id="o3-mini"),
# )

# team = Team(
#     model=OpenAIChat(id="o3-mini"),
#     members=[agent],
#     db=db,
#     session_summary_manager=session_summary_manager,
# )

# team.print_response("Hi my name is John and I live in New York")
# team.print_response("I like to play basketball and hike in the mountains")
