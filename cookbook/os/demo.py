"""Simple example creating a session and using the AgentOS with a SessionManager to expose it"""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.document.local_store import LocalStore
from agno.knowledge.knowledge import Knowledge
from agno.memory import Memory
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.vectordb.pgvector.pgvector import PgVector

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(
    db_url=db_url,
    session_table="sessions",
    user_memory_table="user_memory",
    eval_table="eval_runs",
    metrics_table="metrics",
)

# Setup the memory
memory = Memory(db=db)

store = LocalStore(
    name="local_document_store",
    description="Local document store",
    storage_path="tmp/documents",
)

vector_store_1 = PgVector(
    table_name="pdf_documents",
    # Can inspect database via psql e.g. "psql -h localhost -p 5532 -U ai -d ai"
    db_url=db_url,
)

vector_store_2 = PgVector(
    table_name="pdf_documents_2",
    # Can inspect database via psql e.g. "psql -h localhost -p 5532 -U ai -d ai"
    db_url=db_url,
)

document_db = PostgresDb(
    db_url=db_url,
    knowledge_table="knowledge_documents",
)

# Create knowledge base
knowledge1 = Knowledge(
    name="My Knowledge Base",
    description="A simple knowledge base",
    store=store,
    sources_db=document_db,
    vector_store=vector_store_1,
)

knowledge2 = Knowledge(
    name="My Knowledge Base 2",
    description="A simple knowledge base 2",
    # document_store=document_store,
    sources_db=document_db,
    vector_store=vector_store_2,
)


# Add a document
# knowledge1.add_documents(
#     DocumentV2(
#         name="CV1",
#         paths=["tmp/cv_1.pdf"],
#         metadata={"user_tag": "Engineering candidates"},
#     )
# )

# knowledge2.add_documents(
#     DocumentV2(
#         name="CV1",
#         paths=["tmp/cv_2.pdf"],
#         metadata={"user_tag": "Engineering candidates"},
#     )
# )

# Setup the agent
agent_1 = Agent(
    name="Basic Agent",
    agent_id="basic-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    enable_user_memories=True,
    knowledge=knowledge1,
    markdown=True,
)

agent_2 = Agent(
    name="Basic Agent 2",
    agent_id="basic-agent-2",
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    enable_user_memories=True,
    knowledge=knowledge2,
    markdown=True,
)


# Setup the Agno API App
agent_os = AgentOS(
    name="Demo App",
    description="Demo app for basic agent with session, knowledge, and memory capabilities",
    os_id="demo",
    agents=[agent_1, agent_2],
    interfaces=[Whatsapp(agent=agent_1)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    # Simple run to generate and record a session
    agent_os.serve(app="demo:app", reload=True)
