"""Use this script to migrate your Agno tables from v1 to v2

- Configure your db_url in the script
- Run the script
"""

from agno.db.migrations.v1_to_v2 import migrate
from agno.db.postgres.postgres import PostgresDb

# --- Set these variables before running the script ---

# Your db_url
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# The schema and names of your v1 tables. Leave the names of tables you don't need to migrate blank.
v1_tables_schema = ""
v1_agent_sessions_table_name = ""
v1_team_sessions_table_name = ""
v1_workflow_sessions_table_name = ""
v1_memories_table_name = ""

# Names for the v2 tables
v2_sessions_table_name = ""
v2_memories_table_name = ""


# --- Set your database connection ---

# For Postgres:
#

db = PostgresDb(
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
#     db_url=db_url,
#     session_table=v2_sessions_table_name,
#     memory_table=v2_memories_table_name,
# )


# --- Run the migration ---

migrate(
    db=db,
    v1_db_schema=v1_tables_schema,
    agent_sessions_table_name=v1_agent_sessions_table_name,
    team_sessions_table_name=v1_team_sessions_table_name,
    workflow_sessions_table_name=v1_workflow_sessions_table_name,
    memories_table_name=v1_memories_table_name,
)
