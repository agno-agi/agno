"""Migration utility to migrate your Agno tables from v1 to v2"""

from typing import Any, Dict, List, Optional, Union

from sqlalchemy import text

from agno.db.mysql.mysql import MySQLDb
from agno.db.postgres.postgres import PostgresDb
from agno.db.schemas.memory import UserMemory
from agno.db.sqlite.sqlite import SqliteDb
from agno.session import AgentSession, TeamSession, WorkflowSession
from agno.utils.log import log_error


def migrate(
    db: Union[PostgresDb, MySQLDb, SqliteDb],
    v1_db_schema: str,
    agent_sessions_table_name: Optional[str] = None,
    team_sessions_table_name: Optional[str] = None,
    workflow_sessions_table_name: Optional[str] = None,
    memories_table_name: Optional[str] = None,
):
    """Given a PostgresDb and table names, parse and migrate the tables' content to the corresponding v2 tables.

    Args:
        db: The database to migrate
        v1_db_schema: The schema of the v1 tables
        agent_sessions_table_name: The name of the agent sessions table. If not provided, the agent sessions table will not be migrated.
        team_sessions_table_name: The name of the team sessions table. If not provided, the team sessions table will not be migrated.
        workflow_sessions_table_name: The name of the workflow sessions table. If not provided, the workflow sessions table will not be migrated.
        workflow_v2_sessions_table_name: The name of the workflow v2 sessions table. If not provided, the workflow v2 sessions table will not be migrated.
        memories_table_name: The name of the memories table. If not provided, the memories table will not be migrated.
    """
    if agent_sessions_table_name:
        db.migrate_table_from_v1_to_v2(
            v1_db_schema=v1_db_schema,
            v1_table_name=agent_sessions_table_name,
            v1_table_type="agent_sessions",
        )

    if team_sessions_table_name:
        db.migrate_table_from_v1_to_v2(
            v1_db_schema=v1_db_schema,
            v1_table_name=team_sessions_table_name,
            v1_table_type="team_sessions",
        )

    if workflow_sessions_table_name:
        db.migrate_table_from_v1_to_v2(
            v1_db_schema=v1_db_schema,
            v1_table_name=workflow_sessions_table_name,
            v1_table_type="workflow_sessions",
        )

    if memories_table_name:
        db.migrate_table_from_v1_to_v2(
            v1_db_schema=v1_db_schema,
            v1_table_name=memories_table_name,
            v1_table_type="memories",
        )


def get_all_table_content(db, db_schema: str, table_name: str) -> list[dict[str, Any]]:
    """Get all content from the given table"""
    try:
        with db.Session() as sess:
            result = sess.execute(text(f"SELECT * FROM {db_schema}.{table_name}"))
            return [row._asdict() for row in result]

    except Exception as e:
        log_error(f"Error getting all content from table {table_name}: {e}")
        return []


def parse_agent_sessions(v1_content: List[Dict[str, Any]]) -> List[AgentSession]:
    """Parse v1 Agent sessions into v2 Agent sessions and Memories"""
    sessions_v2 = []

    for item in v1_content:
        session = {
            "agent_id": item.get("agent_id"),
            "agent_data": item.get("agent_data"),
            "session_id": item.get("session_id"),
            "user_id": item.get("user_id"),
            "session_data": item.get("session_data"),
            "metadata": item.get("extra_data"),
            "runs": item.get("memory", {}).get("runs"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }
        agent_session = AgentSession.from_dict(session)
        if agent_session is not None:
            sessions_v2.append(agent_session)

    return sessions_v2


def parse_team_sessions(v1_content: List[Dict[str, Any]]) -> List[TeamSession]:
    """Parse v1 Team sessions into v2 Team sessions and Memories"""
    sessions_v2 = []

    for item in v1_content:
        session = {
            "team_id": item.get("team_id"),
            "team_data": item.get("team_data"),
            "session_id": item.get("session_id"),
            "user_id": item.get("user_id"),
            "session_data": item.get("session_data"),
            "metadata": item.get("extra_data"),
            "runs": item.get("memory", {}).get("runs"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }
        team_session = TeamSession.from_dict(session)
        if team_session is not None:
            sessions_v2.append(team_session)

    return sessions_v2


def parse_workflow_sessions(v1_content: List[Dict[str, Any]]) -> List[WorkflowSession]:
    """Parse v1 Workflow sessions into v2 Workflow sessions"""
    sessions_v2 = []

    for item in v1_content:
        session = {
            "workflow_id": item.get("workflow_id"),
            "workflow_data": item.get("workflow_data"),
            "session_id": item.get("session_id"),
            "user_id": item.get("user_id"),
            "session_data": item.get("session_data"),
            "metadata": item.get("extra_data"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            # Workflow v2 specific fields
            "workflow_name": item.get("workflow_name"),
            "runs": item.get("runs"),
        }
        workflow_session = WorkflowSession.from_dict(session)
        if workflow_session is not None:
            sessions_v2.append(workflow_session)

    return sessions_v2


def parse_memories(v1_content: List[Dict[str, Any]]) -> List[UserMemory]:
    """Parse v1 Memories into v2 Memories"""
    memories_v2 = []

    for item in v1_content:
        memory = {
            "memory_id": item.get("memory_id"),
            "memory": item.get("memory"),
            "input": item.get("input"),
            "updated_at": item.get("updated_at"),
            "agent_id": item.get("agent_id"),
            "team_id": item.get("team_id"),
            "user_id": item.get("user_id"),
        }
        memories_v2.append(UserMemory.from_dict(memory))

    return memories_v2
