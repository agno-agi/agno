"""
AgentOS PostgreSQL File System
=============================

Supply a configured ``FileSystem`` backed by PostgreSQL with an explicit namespace.

Prerequisites: PostgreSQL (./cookbook/scripts/run_pgvector.sh), psycopg
Environment: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/postgres_filesystem.py
Try: Connect Agno OS to http://localhost:7777 and open File System
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

db = PostgresDb(
    id="filesystem-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

filesystem_agent = Agent(
    id="filesystem-agent",
    name="File System Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    filesystem=True,
    instructions="Keep durable working notes in your filesystem.",
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
    agent_os.serve(app="postgres_filesystem:app", reload=True)
