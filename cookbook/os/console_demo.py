"""Simple example creating a session and using the AgentOS with a SessionConnector to expose it"""

import asyncio
from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.document.base import Document
from agno.document.document_v2 import DocumentV2
from agno.document.local_document_store import LocalDocumentStore
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.memory import Memory
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.managers import KnowledgeManager, MemoryManager, SessionManager
from agno.os.console import Console
from agno.os.interfaces import Whatsapp
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.pgvector.pgvector import PgVector

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(
    db_url=db_url,
    agent_session_table="agent_sessions",
    team_session_table="team_sessions",
    workflow_session_table="workflow_sessions",
    knowledge_table="knowledge_documents",
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
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
)

# Create knowledge base
knowledge1 = Knowledge(
    name="My Knowledge Base",
    description="A simple knowledge base",
    document_store=document_store,
    vector_store=vector_store,
    documents_db=db,
)

knowledge2 = Knowledge(
    name="My Knowledge Base 2",
    description="A simple knowledge base 2",
    document_store=document_store,
    vector_store=vector_store,
    documents_db=db,
)


# knowledge1.add_document(
#     DocumentV2(
#         name="Thai Recipes",
#         paths=["./cookbook/os/data/thai_recipes_short.pdf"],
#         metadata={"user_tag": "Thai Recipes"},
#     )
# )

# knowledge2.add_document(
#     DocumentV2(
#         name="Thai Recipes",
#         paths=["./cookbook/os/data/thai_recipes_short.pdf"],
#         metadata={"user_tag": "Thai Recipes"},
#     )
# )

# Setup the agent
basic_agent = Agent(
    name="Basic Agent",
    agent_id="basic-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    enable_user_memories=True,
    knowledge=knowledge1,
    markdown=True,
)

finance_agent = Agent(
    name="Finance Agent",
    agent_id="finance-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    memory=memory,
    enable_user_memories=True,
    knowledge=knowledge2,
    tools=[YFinanceTools()],
    markdown=True,
)

# Setup the Agno API App
agent_os = AgentOS(
    name="Demo App",
    description="Demo app for basic agent with session, knowledge, and memory capabilities",
    os_id="demo",
    console=Console(model=OpenAIChat(id="gpt-4o-mini")),
    agents=[basic_agent, finance_agent],
    interfaces=[Whatsapp(agent=basic_agent)],
    apps=[
        SessionManager(db=db, name="Session Manager"),
        KnowledgeManager(knowledge=knowledge1, name="Knowledge Manager 1"),
        KnowledgeManager(knowledge=knowledge2, name="Knowledge Manager 2"),
        MemoryManager(memory=memory, name="Memory Manager"),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    asyncio.run(agent_os.cli())
    
    # Sample requests
    # 1. What agents do I have configured?
    # 2. Which managers does my OS have?
    # 3. Which interfaces does my OS have?
    # 4. What is the current price of AAPL?
    # 5. Run my basic agent and ask it to tell me a joke
    # 6. What recipes do you know about? @knowledge
    
