from typing import Optional

from agno.db.postgres.postgres import PostgresDb

DEFAULT_SESSIONS_TABLE_NAME = "agno_sessions"
DEFAULT_MEMORIES_TABLE_NAME = "agno_memories"


def migrate(
    db: PostgresDb,
    current_schema: str,
    new_schema: Optional[str] = None,
    agent_sessions_table_name: Optional[str] = None,
    team_sessions_table_name: Optional[str] = None,
    workflow_sessions_table_name: Optional[str] = None,
    memories_table_name: Optional[str] = None,
    new_sessions_table_name: Optional[str] = None,
    new_memories_table_name: Optional[str] = None,
):
    """Migrate the given tables from v1 to v2

    Args:
        db: The database to migrate
        current_schema: The schema of the current tables
        new_schema: The schema of the new tables. If not provided, the current schema will be used.
        agent_sessions_table_name: The name of the agent sessions table. If not provided, the agent sessions table will not be migrated.
        team_sessions_table_name: The name of the team sessions table. If not provided, the team sessions table will not be migrated.
        workflow_sessions_table_name: The name of the workflow sessions table. If not provided, the workflow sessions table will not be migrated.
        memories_table_name: The name of the memories table. If not provided, the memories table will not be migrated.

    """
    if agent_sessions_table_name:
        db.migrate_v1_to_v2(
            old_db_schema=current_schema,
            new_db_schema=new_schema,
            old_table_name=agent_sessions_table_name,
            old_table_type="agent_sessions",
            new_table_name=new_sessions_table_name or DEFAULT_SESSIONS_TABLE_NAME,
        )

    if team_sessions_table_name:
        db.migrate_v1_to_v2(
            old_db_schema=current_schema,
            new_db_schema=new_schema,
            old_table_name=team_sessions_table_name,
            old_table_type="team_sessions",
            new_table_name=new_sessions_table_name or DEFAULT_SESSIONS_TABLE_NAME,
        )

    if workflow_sessions_table_name:
        db.migrate_v1_to_v2(
            old_db_schema=current_schema,
            new_db_schema=new_schema,
            old_table_name=workflow_sessions_table_name,
            old_table_type="workflow_sessions",
            new_table_name=new_sessions_table_name or DEFAULT_SESSIONS_TABLE_NAME,
        )

    if memories_table_name:
        db.migrate_v1_to_v2(
            old_db_schema=current_schema,
            new_db_schema=new_schema,
            old_table_name=memories_table_name,
            old_table_type="memories",
            new_table_name=new_memories_table_name or DEFAULT_MEMORIES_TABLE_NAME,
        )
