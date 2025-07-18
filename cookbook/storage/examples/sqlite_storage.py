"""Run `pip install agno openai sqlalchemy` to install dependencies."""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from rich.pretty import pprint

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    # Fix the session id to continue the same session across execution cycles
    session_id="fixed_id_for_demo",
    storage=SqliteStorage(table_name="agent_sessions", db_file="tmp/data.db"),
    add_history_to_messages=True,
    num_history_runs=3,
)
agent.print_response("What was my last question?")
agent.print_response("What is the capital of France?")
agent.print_response("What was my last question?")
pprint(agent.get_messages_for_session())
