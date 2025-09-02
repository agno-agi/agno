"""Run `pip install ddgs sqlalchemy openai` to install dependencies."""

from agno.agent import Agent
from agno.storage.mysql import MySQLStorage

db_url = "mysql+pymysql://ai:ai@localhost:3306/ai"

agent = Agent(
    storage=MySQLStorage(
        table_name="agent_sessions", db_url=db_url, auto_upgrade_schema=True
    ),
    add_history_to_messages=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")

print(
    f"Session IDs created in DB: {agent.storage.get_all_session_ids(entity_id=agent.agent_id)}"
)
