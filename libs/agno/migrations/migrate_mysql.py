import asyncio

from agno.db.migrations.manager import MigrationManager
from agno.db.mysql import MySQLDb

# Create your database connection here
db_url = "mysql+pymysql://ai:ai@localhost:3306/ai"

db = MySQLDb(db_url=db_url)


# Upgrade your DB to the latest version
async def run_migration():
    await MigrationManager(db).up()
    # Optionally force the migration if necessary
    # await MigrationManager(db).up(force=True)

    # Downgrade your DB to a specific version
    # await MigrationManager(db).down(target_version="2.0.0")


if __name__ == "__main__":
    asyncio.run(run_migration())
