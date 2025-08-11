import os

from agno.agent import Agent
from agno.db.json import JsonDb  # noqa: F401
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.vectordb.lightrag import LightRag
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


vector_db = PgVector(
    table_name="vectors",
    # Can inspect database via psql e.g. "psql -h localhost -p 5432 -U ai -d ai"
    db_url=db_url,
)

vector_db = LightRag(
    api_key=os.getenv("LIGHTRAG_API_KEY"),
)

# contents_db = JsonDb(db_path="./agno_json_data")
contents_db = PostgresDb(db_url=db_url)

# Create knowledge base
knowledge = Knowledge(
    name="My Knowledge Base",
    description="A simple knowledge base",
    contents_db=contents_db,
    vector_db=vector_db,
)

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    add_datetime_to_context=True,
    markdown=True,
    db=contents_db,
)

agent_os = AgentOS(
    description="Example app for basic agent with knowledge capabilities",
    os_id="knowledge-demo",
    agents=[basic_agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    """ Run your AgentOS:
    Now you can interact with your knowledge base using the API. Examples:
    - http://localhost:8001/knowledge/{id}/documents
    - http://localhost:8001/knowledge/{id}/documents/123
    - http://localhost:8001/knowledge/{id}/documents?agent_id=123
    - http://localhost:8001/knowledge/{id}/documents?limit=10&page=0&sort_by=created_at&sort_order=desc
    """
    agent_os.serve(app="knowledge_demo:app", reload=True)
