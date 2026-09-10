"""Expose an already configured Knowledge instance as an AgentOS filesystem.

This is the explicit alternative to PageFileSystem(db=..., namespace=...).
Use the database and explicit sync command documented for with_knowledge.py.
Ask: Explore the reference docs and explain one concept with a source path.
"""

from os import environ

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.fs import FileSystem
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.page import PageFileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

db = PostgresDb(
    id="existing-knowledge-db", db_url=environ["FILESYSTEM_KNOWLEDGE_DB_URL"]
)

# Reuse the reference-docs corpus and matching embedding configuration.
knowledge = Knowledge(
    name="Reference documentation",
    content_db=db,
    page_store=FileSystem(
        db=db,
        namespace="reference-docs",
        max_file_bytes=4 * 1024 * 1024,
        max_namespace_bytes=256 * 1024 * 1024,
    ),
    vector_db=PgVector(
        db=db,
        table_name="reference_page_vectors",
        embedder=OpenAIEmbedder(
            id="text-embedding-3-small",
            dimensions=1536,
            client_params={"timeout": 20, "max_retries": 0},
        ),
    ),
)

agent = Agent(
    id="existing-knowledge-agent",
    name="Existing Knowledge Assistant",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    filesystem=PageFileSystem(knowledge=knowledge),
    markdown=True,
)

agent_os = AgentOS(
    id="existing-knowledge-os",
    db=db,
    agents=[agent],
    cors_allowed_origins=["http://localhost:3000"],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=7777)
