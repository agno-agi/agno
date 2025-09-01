"""
This example shows how to use a remote LanceDB database.

- Set URI obtained from https://cloud.lancedb.com/
- Export `LANCEDB_API_KEY` OR set `api_key` in the `LanceDb` constructor
"""

# install lancedb - `pip install lancedb`

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb

# Initialize Remote LanceDB
vector_db = LanceDb(
    table_name="recipes",
    uri="<URI>",
    # api_key="<API_KEY>",
)

# Create knowledge base
knowledge_base = Knowledge(
    vector_db=vector_db,
)

knowledge_base.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
)

# Create and use the agent
agent = Agent(knowledge=knowledge_base)
agent.print_response("How to make Tom Kha Gai", markdown=True)
