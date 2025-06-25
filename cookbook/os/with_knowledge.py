from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.document.local_document_store import LocalDocumentStore
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.playground import Playground
from agno.os.managers import KnowledgeManager
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

document_store = LocalDocumentStore(
    name="local_document_store",
    description="Local document store",
    storage_path="tmp/documents",
)

vector_store = PgVector(
    table_name="pdf_documents",
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
    vector_store=vector_store,
    document_store=document_store,
    documents_db=document_db,
)

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    add_datetime_to_instructions=True,
    markdown=True,
)

agno_client = AgentOS(
    name="Example App: Basic Agent",
    description="Example app for basic agent with playground capabilities",
    os_id="basic-os-with-knowledge",
    agents=[
        basic_agent,
    ],
    interfaces=[
        Playground(),
    ],
    apps=[
        KnowledgeManager(knowledge=knowledge),
    ],
)
app = agno_client.get_app()

if __name__ == "__main__":
    agno_client.serve(app="with_knowledge:app", reload=True)
