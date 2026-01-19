import asyncio

from agno.db.migrations.manager import MigrationManager
from agno.db.sqlite import AsyncSqliteDb, SqliteDb

# Create your database connection here
db = SqliteDb(
    db_file="tmp/data.db",
    session_table="agno_sessions",
    memory_table="agno_memories",
)
# Or for asynchronous operations
async_db = AsyncSqliteDb(
    db_file="tmp/data.db",
    session_table="agno_sessions",
    memory_table="agno_memories",
)


# Upgrade your DB to the latest version
async def run_migration():
    await MigrationManager(async_db).up()
    # Optionally force the migration if necessary
    # await MigrationManager(async_db).up(force=True)

    # Downgrade your DB to a specific version
    # await MigrationManager(async_db).down(target_version="2.0.0")


if __name__ == "__main__":
    asyncio.run(run_migration())
