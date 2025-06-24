from agno.agent import Agent
from agno.os import AgentOS
from agno.os import Playground
from agno.os.connectors.knowledge import KnowledgeConnector
from agno.document import Document
from agno.document.local_document_store import LocalDocumentStore
from agno.knowledge.knowledge_base import KnowledgeBase
from agno.models.openai import OpenAIChat
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

# Create knowledge base
knowledge_base = KnowledgeBase(
    name="My Knowledge Base",
    description="A simple knowledge base",
    document_store=document_store,
)

# Add a document
doc = Document(content="Hello worlds", name="greetings")
doc_id = knowledge_base.add_document(doc)


basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge_base,
    add_datetime_to_instructions=True,
    markdown=True,
)

agno_client = AgentOS(
    name="Example App: Basic Agent",
    description="Example app for basic agent with playground capabilities",
    app_id="basic-app",
    agents=[
        basic_agent,
    ],
    interfaces=[
        Playground(),
    ],
    managers=[KnowledgeConnector(knowledge=knowledge_base)],
)
app = agno_client.get_app()

if __name__ == "__main__":
    agno_client.serve(app="with_knowledge:app", reload=True)
