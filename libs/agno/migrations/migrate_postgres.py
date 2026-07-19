import asyncio

from agno.db.migrations.manager import MigrationManager
from agno.db.postgres import AsyncPostgresDb, PostgresDb

# Create your database connection here
db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    session_table="agno_sessions",
    memory_table="agno_memories",
)
# Or for asynchronous operations
async_db = AsyncPostgresDb(
    db_url="postgresql+psycopg_async://ai:ai@localhost:5532/ai",
    session_table="agno_sessions",
    memory_table="agno_memories",
)


# Upgrade your DB to the latest version
async def run_migration():
    await MigrationManager(async_db).up()
    # Optionally force the migration if necessary
    # await MigrationManager(db).up(force=True)

    # Downgrade your DB to a specific version
    # await MigrationManager(db).down(target_version="2.0.0")


if __name__ == "__main__":
    asyncio.run(run_migration())
