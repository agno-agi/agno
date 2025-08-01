"""Util to migrate tables from v1 to v2"""

from typing import Any, Dict, List


def get_all_table_content(db, db_schema: str, table_name: str) -> list[dict[str, Any]]:
    """Get all content from the given table"""
    rows = db.execute(f"SELECT * FROM {db_schema}.{table_name}")
    return [dict(row) for row in rows]


def parse_agent_sessions(old_content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parse the agent sessions from the old content"""
    return []


def parse_team_sessions(old_content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parse the team sessions from the old content"""
    return []


def parse_workflow_sessions(old_content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parse the workflow sessions from the old content"""
    return []


def parse_memories(old_content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parse the memories from the old content"""
    return []
