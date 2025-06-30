from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.document import Document
from agno.document.local_document_store import LocalDocumentStore
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.managers import KnowledgeManager
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

document_store = LocalDocumentStore(
    name="local_document_store",
    description="Local document store",
    storage_path="tmp/documents",
)

vector_store = PgVector(
    table_name="vectors",
    # Can inspect database via psql e.g. "psql -h localhost -p 5432 -U ai -d ai"
    db_url=db_url,
)

document_db = PostgresDb(
    db_url=db_url,
    knowledge_table="knowledge_documents",
)

# Create knowledge base
knowledge = Knowledge(
    name="My Knowledge Base",
    description="A simple knowledge base",
    document_store=document_store,
    documents_db=document_db,
    vector_store=vector_store,
)

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    add_datetime_to_instructions=True,
    markdown=True,
)

agent_os = AgentOS(
    name="Example App: Knowledge Agent",
    description="Example app for basic agent with knowledge capabilities",
    os_id="knowledge-demo",
    agents=[
        basic_agent,
    ],
    apps=[KnowledgeManager(knowledge=knowledge)],
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
    agent_os.serve(app="knowledge_manager:app", reload=True)
