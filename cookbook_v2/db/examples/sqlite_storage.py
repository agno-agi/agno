"""Run `pip install agno openai sqlalchemy` to install dependencies."""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

db = SqliteDb(db_file="tmp/data.db")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    # Fix the session id to continue the same session across execution cycles
    session_id="fixed_id_for_demo",
    add_history_to_messages=True,
    num_history_runs=3,
)
agent.print_response("What was my last question?")
agent.print_response("What is the capital of France?")
agent.print_response("What was my last question?")
pprint(agent.get_messages_for_session())
