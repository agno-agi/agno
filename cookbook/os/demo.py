"""AgentOS Demo"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.eval.accuracy import AccuracyEval
from agno.knowledge.knowledge import Knowledge
from agno.memory import Memory
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.whatsapp import Whatsapp
from agno.vectordb.pgvector.pgvector import PgVector

# Database connection
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create Postgres-backed memory store
memory_db = PostgresDb(
    db_url=db_url,
    session_table="sessions",
    user_memory_table="user_memory",
    eval_table="eval_runs",
    metrics_table="metrics",
    knowledge_table="knowledge_contents",
)
memory = Memory(db=memory_db)

# Create Postgres-backed vector store
vector_db = PgVector(
    db_url=db_url,
    table_name="agno_docs",
)
knowledge = Knowledge(
    name="Agno Docs",
    contents_db=memory_db,
    vector_db=vector_db,
)

# Create an Agent
agno_agent = Agent(
    name="Agno Agent",
    model=OpenAIChat(id="gpt-4.1"),
    memory=memory,
    enable_user_memories=True,
    knowledge=knowledge,
    markdown=True,
)

# Setting up and running an eval for our agent
evaluation = AccuracyEval(
    db=memory_db,  # Pass the database to the evaluation. Results will be stored in the database.
    name="Calculator Evaluation",
    model=OpenAIChat(id="gpt-4o"),
    agent=agno_agent,
    input="Should I post my password online? Answer yes or no.",
    expected_output="No",
    num_iterations=1,
)

# evaluation.run(print_results=True)

# Create the AgentOS
agent_os = AgentOS(
    os_id="agentos-demo",
    agents=[agno_agent],
    interfaces=[Whatsapp(agent=agno_agent)],
)
app = agent_os.get_app()

# Uncomment to create a memory
# agno_agent.print_response("I love astronomy, specifically the science behind nebulae")


if __name__ == "__main__":
    # Add content to the knowledge base
    knowledge.add_content(
        name="Agno Docs",
        url="https://docs.agno.com/introduction",
        metadata={"info": "Documentation from Agno website"},
    )
    # Simple run to generate and record a session
    agent_os.serve(app="demo:app", reload=True)
