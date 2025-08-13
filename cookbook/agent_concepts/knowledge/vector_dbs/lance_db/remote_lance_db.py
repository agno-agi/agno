"""
This example shows how to use a remote LanceDB database.

- Set URI obtained from https://cloud.lancedb.com/
- Export `LANCEDB_API_KEY` OR set `api_key` in the `LanceDb` constructor
"""

# install lancedb - `pip install lancedb`

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.lancedb import LanceDb

# Initialize Remote LanceDB
vector_db = LanceDb(
    table_name="recipes",
    uri="<URI>",
    # api_key="<API_KEY>",
)

# Create knowledge base
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)

knowledge_base.load(recreate=False)  # Comment out after first run

# Create and use the agent
agent = Agent(knowledge=knowledge_base, show_tool_calls=True)
agent.print_response("How to make Tom Kha Gai", markdown=True)
