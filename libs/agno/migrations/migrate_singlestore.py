import asyncio
from urllib.parse import quote_plus

from agno.db.migrations.manager import MigrationManager
from agno.db.singlestore import SingleStoreDb

# Create your database connection here
username = "xxxxxx"
encoded_password = quote_plus("xxxxxx")
host = "xxxxxxxxxxx.aws-virginia-6.svc.singlestore.com"
port = "3333"
database = "xxxxxx"

db_url = f"mysql+pymysql://{username}:{encoded_password}@{host}:{port}/{database}"
db = SingleStoreDb(db_url=db_url)


# Upgrade your DB to the latest version
async def run_migration():
    await MigrationManager(db).up()
    # await MigrationManager(db).down(target_version="2.0.0")


if __name__ == "__main__":
    asyncio.run(run_migration())
