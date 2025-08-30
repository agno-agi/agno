"""Use MongoDb as the database for an agent.

Run `pip install openai pymongo` to install dependencies
"""

from agno.agent import Agent
from agno.db.mongo import MongoDb
from agno.tools.duckduckgo import DuckDuckGoTools

# MongoDB connection settings
db_url = "mongodb://localhost:27017"

db = MongoDb(db_url=db_url)

agent = Agent(
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
