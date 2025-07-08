"""Simple example creating a session and using the AgentOS with a SessionManager to expose it"""

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.document.local_document_store import LocalDocumentStore
from agno.eval.accuracy import AccuracyEval
from agno.eval.performance import PerformanceEval
from agno.knowledge.knowledge import Knowledge
from agno.memory import Memory
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces import Whatsapp
from agno.os.managers import (
    EvalManager,
    KnowledgeManager,
    MemoryManager,
    MetricsManager,
    SessionManager,
)
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

document_store = LocalDocumentStore(
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
    document_store=document_store,
    documents_db=document_db,
    vector_store=vector_store_1,
)

knowledge2 = Knowledge(
    name="My Knowledge Base 2",
    description="A simple knowledge base 2",
    document_store=document_store,
    documents_db=document_db,
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
agent = Agent(
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


def instantiate_agent():
    return Agent(system_message="Be concise, reply with one sentence.")


evaluation = AccuracyEval(
    db=db,
    name="Calculator Evaluation",
    model=OpenAIChat(id="gpt-4o"),
    agent=agent,
    input="Should I post my password online? Answer yes or no.",
    expected_output="No",
    num_iterations=1,
)

evaluation2 = PerformanceEval(
    name="Performance Evaluation",
    func=instantiate_agent,
    num_iterations=100,
)

# evaluation2.run(print_results=True)  # Comment this to prevent the eval from running
# Setup the Agno API App
agent_os = AgentOS(
    name="Demo App",
    description="Demo app for basic agent with session, knowledge, and memory capabilities",
    os_id="demo",
    agents=[agent],
    interfaces=[Whatsapp(agent=agent)],
    apps=[
        SessionManager(db=db, name="Session Manager"),
        SessionManager(db=db, name="Session Manager 2"),
        KnowledgeManager(knowledge=knowledge1, name="Knowledge Manager 1"),
        KnowledgeManager(knowledge=knowledge2, name="Knowledge Manager 2"),
        MemoryManager(memory=memory, name="Memory Manager"),
        MetricsManager(db=db, name="Metrics Manager"),
        EvalManager(db=db, name="Eval Manager"),
        EvalManager(db=db, name="Eval Manager 2"),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    # Simple run to generate and record a session
    agent.print_response("What is the capital of France?")
    agent_os.serve(app="demo:app", reload=True)
