"""Serve Prime Agent with AgentOS and Postgres-backed session persistence.

Requires prime-agent, agno[os,postgres], and DATABASE_URL.
"""

from os import environ, getenv

from agno.agents.prime import PrimeAgent
from agno.db.postgres import PostgresDb
from agno.os import AgentOS

db = PostgresDb(
    id="prime-db",
    db_url=environ["DATABASE_URL"],
)
agent = PrimeAgent(
    id="prime-agent",
    name="Prime Agent",
    cwd=getenv("PRIME_AGENT_CWD", "."),
    db=db,
)

agent_os = AgentOS(
    id="prime-agent-os",
    name="Prime AgentOS",
    agents=[agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="prime_agentos:app", reload=True)
