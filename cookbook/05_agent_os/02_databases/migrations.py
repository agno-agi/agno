"""
AgentOS Schema Migrations
=========================

When you upgrade Agno with an existing database, some tables may need a schema
migration before the features backed by them (metrics, evals, knowledge, ...)
work again. Chat traffic keeps working either way. Migrations are never applied
behind your back:

- By default AgentOS logs a warning at startup listing every pending migration.
- Preview what would change with `GET /databases/migrations/pending` or
  `agno db migrate --dry-run`, then apply with `POST /databases/all/migrate`
  or `agno db migrate`.
- Opt in to `auto_migrate_dbs=True` (below) to apply pending migrations at
  startup, before tables are provisioned. Suited to local development; in
  production prefer an explicit migrate step in your deploy.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/02_databases/migrations.py
Try: curl http://localhost:7777/databases/migrations/pending
     agno db status --url http://localhost:7777
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Database and Agent
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="agent-os-migrations-db",
    db_file="tmp/migrations.db",
)

migrations_agent = Agent(
    id="migrations-agent",
    name="Migrations Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Answer questions concisely.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="database-migrations-os",
    description="AgentOS that applies pending schema migrations at startup.",
    db=db,
    agents=[migrations_agent],
    # Apply pending schema migrations to every local database at startup.
    # Leave this off in production and run `agno db migrate` as a deploy step.
    auto_migrate_dbs=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="migrations:app", reload=True)
