"""Simple example creating a session and using the AgentOS with a SessionManager to expose it"""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.document.base import Document
from agno.document.local_document_store import LocalDocumentStore
from agno.knowledge.knowledge_base import KnowledgeBase
from agno.memory import Memory
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.managers import KnowledgeManager, MemoryManager, SessionManager
from agno.os.interfaces import Whatsapp
from agno.vectordb.pgvector.pgvector import PgVector

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(
    db_url=db_url,
    agent_session_table="agent_sessions",
    team_session_table="team_sessions",
    workflow_session_table="workflow_sessions",
)

# Setup the memory
memory = Memory(db=db)

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

knowledge_base_2 = KnowledgeBase(
    name="My Knowledge Base 2",
    description="A simple knowledge base 2",
    document_store=document_store,
)


# Add a document
doc_1 = Document(content="Hello worlds", name="greetings")
knowledge_base.add_document(doc_1)

doc_2 = Document(content="Hello worlds 2", name="greetings 2")
knowledge_base_2.add_document(doc_2)

# Setup the agent
agent = Agent(
    name="Basic Agent",
    agent_id="basic-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    enable_user_memories=True,
    knowledge=knowledge_base,
    markdown=True,
)

agent_2 = Agent(
    name="Basic Agent 2",
    agent_id="basic-agent-2",
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    enable_user_memories=True,
    knowledge=knowledge_base,
    markdown=True,
)

# Setup the Agno API App
agent_os = AgentOS(
    name="Demo App",
    description="Demo app for basic agent with session, knowledge, and memory capabilities",
    os_id="demo",
    agents=[agent],
    interfaces=[Whatsapp(agent=agent)],
    apps=[
        SessionManager(db=db, name="Session Manager"),
        KnowledgeManager(knowledge=knowledge_base, name="Knowledge Manager 1"),
        KnowledgeManager(knowledge=knowledge_base_2, name="Knowledge Manager 2"),
        MemoryManager(memory=memory, name="Memory Manager"),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    # Simple run to generate and record a session
    agent_os.serve(app="demo:app", reload=True)
