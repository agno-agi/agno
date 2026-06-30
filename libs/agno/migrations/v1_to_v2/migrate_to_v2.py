"""Use this script to migrate your Agno tables from v1 to v2

- Configure your db_url in the script
- Run the script
"""

from agno.db.migrations.v1_to_v2 import migrate
from agno.db.postgres.postgres import PostgresDb
from agno.utils.log import log_info

# --- Set these variables before running the script ---

## Your db_url ##
db_url = ""

## Postgres Sample ##
# db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

## MySQL Sample ##
# db_url = "mysql+pymysql://ai:ai@localhost:3306/ai"

## SQLite Sample ##
# sqlite_db_file = "tmp/data.db"

## MongoDB Sample ##
# db_url = "mongodb://mongoadmin:secret@127.0.0.1:27017/admin"


# The schema and names of your v1 tables. Leave the names of tables you don't need to migrate blank.
v1_tables_schema = ""  # Leave empty for SQLite and MongoDB
v1_agent_sessions_table_name = ""
v1_team_sessions_table_name = ""
v1_workflow_sessions_table_name = ""
v1_memories_table_name = ""

# Names for the v2 tables/collections
v2_sessions_table_name = ""
v2_memories_table_name = ""

# Migration batch size (adjust based on available memory and table size)
migration_batch_size = 5000

# --- Set your database connection ---

# For Postgres:
#

db = PostgresDb(  # type: ignore
    db_url=db_url,
    session_table=v2_sessions_table_name,
    memory_table=v2_memories_table_name,
)

# For MySQL:
#
# from agno.db.mysql.mysql import MySQLDb
# db = MySQLDb(
#     db_url=db_url,
#     session_table=v2_sessions_table_name,
#     memory_table=v2_memories_table_name,
# )


# For SQLite:
#
# from agno.db.sqlite.sqlite import SqliteDb
# db = SqliteDb(
#     db_file=sqlite_db_file,
#     session_table=v2_sessions_table_name,
#     memory_table=v2_memories_table_name,
# )


# For MongoDB:
#
# from agno.db.mongo.mongo import MongoDb
# db = MongoDb(db_url=db_url)
# or
# db = MongoDb(
#     host=mongo_host,
#     port=mongo_port,
#     db_name=mongo_db_name,
#     session_collection=v2_sessions_table_name,
#     memory_collection=v2_memories_table_name,
# )


#  --- Exit if no tables are provided ---

if (
    not v1_agent_sessions_table_name
    and not v1_team_sessions_table_name
    and not v1_workflow_sessions_table_name
    and not v1_memories_table_name
):
    log_info(
        "No tables provided, nothing can be migrated. Update the variables in the migration script to point to the tables you want to migrate."
    )
    exit()

# --- Run the migration ---

migrate(
    db=db,
    v1_db_schema=v1_tables_schema,
    agent_sessions_table_name=v1_agent_sessions_table_name,
    team_sessions_table_name=v1_team_sessions_table_name,
    workflow_sessions_table_name=v1_workflow_sessions_table_name,
    memories_table_name=v1_memories_table_name,
    batch_size=migration_batch_size,
)
