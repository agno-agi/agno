"""
This example shows how to use the session summary to store the conversation summary.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.session.summary import SessionSummaryManager  # noqa: F401

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=db_url, session_table="sessions")

session_summary_manager = SessionSummaryManager(
    model=OpenAIChat(
        id="gpt-4o-mini"
    ),  # Set a custom model for session summary generation
    summary_request_message="Write the summary in Spanish.",  # Set a custom request message for how the summary should be written
    # session_summary_prompt="Write the summary in Spanish.", # Alternatively override the entire system prompt
)

agent = Agent(
    model=OpenAIChat(id="gpt-5"),
    db=db,
    session_id="session_summary",
    session_summary_manager=session_summary_manager,
)

agent.print_response("Hi my name is John and I live in New York")
agent.print_response("I like to play basketball and hike in the mountains")

print(agent.get_session_summary(session_id="session_summary"))
