"""Sync documentation knowledge and serve an agent with a durable filesystem."""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.fs import FileSystem
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

db = PostgresDb(
    id="filesystem-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

knowledge = Knowledge(
    content_db=db,
    page_store=FileSystem(db=db, namespace="product-docs"),
    vector_db=PgVector(
        db=db,
        table_name="product_doc_vectors",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

filesystem_agent = Agent(
    id="filesystem-agent",
    name="File System Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    filesystem=FileSystem(db=db, namespace="product-docs"),
    knowledge=knowledge,
    search_knowledge=True,
    instructions=[
        "Keep durable working notes in your filesystem.",
        "Search the documentation knowledge base for Agno questions and cite sources.",
    ],
    markdown=True,
)


agent_os = AgentOS(
    id="filesystem-os",
    description="AgentOS with a durable PostgreSQL filesystem.",
    db=db,
    agents=[filesystem_agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    knowledge.setup()
    report = knowledge.sync_pages(url="https://docs.agno.com/llms.txt")
    print(report.model_dump_json(indent=2))
    if report.status == "partial":
        raise RuntimeError("Some documentation pages could not be synchronized")
    agent_os.serve(app=app)
