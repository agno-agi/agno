from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

db = SqliteDb(db_file="tmp/agents.db", session_table="agent_sessions")

INTRODUCTION = """Hello, I'm your personal assistant. I can help you only with questions related to mountain climbing."""

agent = Agent(
    model=OpenAIChat(),
    db=db,
    introduction=INTRODUCTION,
    session_id="introduction_session_mountain_climbing",
    add_history_to_context=True,
)

agent.print_response("Easiest 14er in USA?")
agent.print_response("Is K2 harder to climb than Everest?")
