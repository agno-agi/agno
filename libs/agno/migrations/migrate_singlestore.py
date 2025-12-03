import asyncio
from os import getenv

from agno.db.migrations.manager import MigrationManager
from agno.db.singlestore import SingleStoreDb

# Create your database connection here
USERNAME = getenv("SINGLESTORE_USERNAME")
PASSWORD = getenv("SINGLESTORE_PASSWORD")
HOST = getenv("SINGLESTORE_HOST")
PORT = getenv("SINGLESTORE_PORT")
DATABASE = getenv("SINGLESTORE_DATABASE")

db_url = f"mysql+pymysql://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
db = SingleStoreDb(db_url=db_url)


# Upgrade your DB to the latest version
async def run_migration():
    await MigrationManager(db).up()
    # Optionally force the migration if necessary
    # await MigrationManager(db).up(force=True)

    # Downgrade your DB to a specific version
    # await MigrationManager(db).down(target_version="2.0.0")


if __name__ == "__main__":
    asyncio.run(run_migration())
