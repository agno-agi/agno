"""
Schema Migrations
=================

Upgrading Agno with an existing database can leave some tables (metrics,
evals, knowledge, schedules, ...) at an older schema version. Chat traffic
keeps working, but the features backed by those tables fail with an
invalid-schema error on first touch until the pending migrations are applied.

Migrations are never applied behind your back. You have three options:

1. Inspect and apply explicitly (recommended in production):
       pending = asyncio.run(MigrationManager(db).pending())
       asyncio.run(MigrationManager(db).up())
2. Let AgentOS tell you: it logs a warning at startup listing pending
   migrations, and exposes POST /databases/all/migrate to apply them.
3. Opt in at the database (this example): construct the db with
   auto_migrate=True and pending migrations are applied once, on the first
   table the db resolves, before that table is validated. Suited to local
   development and single-process deployments.

Run: .venvs/demo/bin/python cookbook/06_storage/05_schema_migrations.py
"""

import asyncio

from agno.agent import Agent
from agno.db.migrations.manager import MigrationManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

# Pending migrations are applied on first use. Leave this off in production and
# run MigrationManager(db).up() as an explicit deploy step instead.
db = SqliteDb(db_file="tmp/schema_migrations.db", auto_migrate=True)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    add_history_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response("What is the capital of France?", stream=True)

    # Read-only check: which tables still have a migration pending? Nothing here,
    # because auto_migrate applied them when the agent first touched the db.
    pending = asyncio.run(MigrationManager(db).pending())
    print("Pending migrations:", [p.table_name for p in pending] or "none")
