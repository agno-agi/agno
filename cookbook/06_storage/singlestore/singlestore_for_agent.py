"""Use SingleStore as the database for an agent.

Run `pip install ddgs sqlalchemy openai` to install dependencies."""

from os import getenv

from agno.agent import Agent
from agno.db.singlestore.singlestore import SingleStoreDb
from agno.tools.duckduckgo import DuckDuckGoTools

# Configure SingleStore DB connection
USERNAME = getenv("SINGLESTORE_USERNAME")
PASSWORD = getenv("SINGLESTORE_PASSWORD")
HOST = getenv("SINGLESTORE_HOST")
PORT = getenv("SINGLESTORE_PORT")
DATABASE = getenv("SINGLESTORE_DATABASE")

db_url = (
    f"mysql+pymysql://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}?charset=utf8mb4"
)
db = SingleStoreDb(db_url=db_url)

# Create an agent with SingleStore db
agent = Agent(
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
)
agent.print_response("How many people live in Canada?")
agent.print_response("What is their national anthem called?")
