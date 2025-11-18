"""Use MySQL as the database for an agent.

Run `pip install openai` to install dependencies."""

from agno.agent import Agent
from agno.db.mysql import MySQLDb

db_url = "mysql+pymysql://ai:ai@localhost:3306/ai"

db = MySQLDb(db_url=db_url)

agent = Agent(
    db=db,
    add_history_to_context=True,
    enable_agentic_memory=True,
)
agent.print_response("please remember i like sushi")
