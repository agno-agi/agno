import asyncio

from agno.db.migrations.manager import MigrationManager
from agno.db.mysql import MySQLDb

# Create your database connection here
db_url = "mysql+pymysql://ai:ai@localhost:3306/ai"

db = MySQLDb(db_url=db_url)


# Upgrade your DB to the latest version
async def run_migration():
    await MigrationManager(db).up("v2.3.0")
    await MigrationManager(db).down("v2.0.0")
    # await MigrationManager(db).down(target_version="2.0.0")


if __name__ == "__main__":
    asyncio.run(run_migration())
