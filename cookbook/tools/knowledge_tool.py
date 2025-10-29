from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

kb = Knowledge(
    vector_db=PgVector(
        table_name="documents",
        db_url=db_url,
    ),
)

agent = Agent(
    knowledge=kb,
    update_knowledge=True,
)
agent.print_response(
    "Update your knowledge with the fact that cats and dogs are pets", markdown=True
)
