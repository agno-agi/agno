"""AgentOS with managed durable files in PostgreSQL.

Set FILESYSTEM_DB_URL and OPENAI_API_KEY, then run this file.
Ask: Save our deployment checklist to notes/deployment.md.
"""

from os import environ

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

db = PostgresDb(id="postgres-files-db", db_url=environ["FILESYSTEM_DB_URL"])

agent = Agent(
    id="postgres-files-agent",
    name="Postgres Files Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    filesystem=True,
    instructions="Keep durable working notes in your filesystem. Save notes only when asked.",
    markdown=True,
)

# AgentOS supplies the database; files live under agents/postgres-files-agent.
agent_os = AgentOS(
    id="postgres-files-os",
    db=db,
    agents=[agent],
    cors_allowed_origins=["http://localhost:3000"],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=7777)
