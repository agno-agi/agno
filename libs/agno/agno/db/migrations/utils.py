"""Util to migrate tables from v1 to v2"""

from typing import Any, Dict, List, Tuple

from agno.db.postgres.postgres import log_error
from agno.db.schemas.memory import UserMemory
from agno.session import AgentSession, TeamSession, WorkflowSession


def get_all_table_content(db, db_schema: str, table_name: str) -> list[dict[str, Any]]:
    """Get all content from the given table"""
    try:
        rows = db.execute(f"SELECT * FROM {db_schema}.{table_name}")
        return [dict(row) for row in rows]

    except Exception as e:
        log_error(f"Error getting all content from table {table_name}: {e}")
        return []


def parse_agent_sessions(old_content: List[Dict[str, Any]]) -> Tuple[List[AgentSession], List[UserMemory]]:
    """Parse v1 Agent sessions into v2 Agent sessions and Memories"""
    sessions_v2 = []
    memories_v2 = []

    for item in old_content:
        session = {
            "agent_id": item.get("agent_id"),
            "agent_data": item.get("agent_data"),
            "session_id": item.get("session_id"),
            "user_id": item.get("user_id"),
            "session_data": item.get("session_data"),
            "metadata": item.get("extra_data"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }
        sessions_v2.append(AgentSession.from_dict(session))

        if item.get("memory"):
            memory = {
                "memory_id": item.get("memory", {}).get("memory_id"),
                "memory": item.get("memory", {}).get("memory"),
                "input": item.get("memory", {}).get("input"),
                "agent_id": item.get("memory", {}).get("agent_id"),
                "team_id": item.get("memory", {}).get("team_id"),
                "user_id": item.get("memory", {}).get("user_id"),
            }
            memories_v2.append(UserMemory.from_dict(memory))

    return sessions_v2, memories_v2


def parse_team_sessions(old_content: List[Dict[str, Any]]) -> Tuple[List[TeamSession], List[UserMemory]]:
    """Parse v1 Team sessions into v2 Team sessions and Memories"""
    sessions_v2 = []
    memories_v2 = []

    for item in old_content:
        session = {
            "team_id": item.get("team_id"),
            "team_data": item.get("team_data"),
            "session_id": item.get("session_id"),
            "user_id": item.get("user_id"),
            "session_data": item.get("session_data"),
            "metadata": item.get("extra_data"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }
        sessions_v2.append(TeamSession.from_dict(session))

        if item.get("memory"):
            memory = {
                "memory_id": item.get("memory", {}).get("memory_id"),
                "memory": item.get("memory", {}).get("memory"),
                "input": item.get("memory", {}).get("input"),
                "agent_id": item.get("memory", {}).get("agent_id"),
                "team_id": item.get("memory", {}).get("team_id"),
                "user_id": item.get("memory", {}).get("user_id"),
            }
            memories_v2.append(UserMemory.from_dict(memory))

    return sessions_v2, memories_v2


def parse_workflow_sessions(old_content: List[Dict[str, Any]]) -> List[WorkflowSession]:
    """Parse v1 Workflow sessions into v2 Workflow sessions"""
    sessions_v2 = []

    for item in old_content:
        session = {
            "workflow_id": item.get("workflow_id"),
            "workflow_data": item.get("workflow_data"),
            "session_id": item.get("session_id"),
            "user_id": item.get("user_id"),
            "session_data": item.get("session_data"),
            "metadata": item.get("extra_data"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }
        sessions_v2.append(WorkflowSession.from_dict(session))

    return sessions_v2


def parse_workflow_v2_sessions(old_content: List[Dict[str, Any]]) -> List[WorkflowSession]:
    """Parse v1 Workflow v2 sessions into v2 Workflow sessions"""
    sessions_v2 = []

    for item in old_content:
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
        sessions_v2.append(WorkflowSession.from_dict(session))

    return sessions_v2
