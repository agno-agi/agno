"""Use this script to migrate your Agno tables from v1 to v2

- Configure your db_url in the script
- Run the script
"""

from agno.db.migrations.v1_to_v2 import migrate
from agno.db.postgres.postgres import PostgresDb

# --- Set these variables before running the script ---

# Your db_url
db_url = ""

# The schema and names of your v1 tables. Leave the names of tables you don't need to migrate blank.
old_tables_schema = ""
old_agent_sessions_table_name = ""
old_team_sessions_table_name = ""
old_workflow_sessions_table_name = ""
old_workflow_v2_sessions_table_name = ""

# Names for the new tables
new_sessions_table_name = ""
new_memories_table_name = ""


# --- Migration logic ---

db = PostgresDb(
    db_url,
    session_table=new_sessions_table_name,
    memory_table=new_memories_table_name,
)

migrate(
    db=db,
    old_db_schema=old_tables_schema,
    agent_sessions_table_name=old_agent_sessions_table_name,
    team_sessions_table_name=old_team_sessions_table_name,
    workflow_sessions_table_name=old_workflow_sessions_table_name,
    workflow_v2_sessions_table_name=old_workflow_v2_sessions_table_name,
)
