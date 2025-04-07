"""
This recipe shows how to store agent sessions in a MongoDB database.
Steps:
1. Run: `pip install openai pymongo agno` to install dependencies
2. Make sure you are running a local instance of mongodb
3. Run: `python cookbook/storage/mongodb_storage.py` to run the agent
"""

from agno.agent import Agent
from agno.storage.mongodb import MongoDbStorage
from agno.tools.duckduckgo import DuckDuckGoTools

# MongoDB connection settings
db_url = "mongodb://localhost:27017"

agent = Agent(
    storage=MongoDbStorage(
        collection_name="agent_sessions", db_url=db_url, db_name="agno"
    ),
    tools=[DuckDuckGoTools()],
    add_history_to_messages=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
