"""Telemetry logging helpers for Team."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from agno.utils.log import log_debug

if TYPE_CHECKING:
    from agno.team.team import Team


def get_team_data(team: "Team") -> Dict[str, Any]:
    team_data: Dict[str, Any] = {}
    if team.name is not None:
        team_data["name"] = team.name
    if team.id is not None:
        team_data["team_id"] = team.id
    if team.model is not None:
        team_data["model"] = team.model.to_dict()
    return team_data


def get_telemetry_data(team: "Team") -> Dict[str, Any]:
    """Get the telemetry data for the team"""
    return {
        "team_id": team.id,
        "db_type": team.db.__class__.__name__ if team.db else None,
        "model_provider": team.model.provider if team.model else None,
        "model_name": team.model.name if team.model else None,
        "model_id": team.model.id if team.model else None,
        "parser_model": team.parser_model.to_dict() if team.parser_model else None,
        "output_model": team.output_model.to_dict() if team.output_model else None,
        "member_count": len(team.members) if isinstance(team.members, list) else 0,
        "has_knowledge": team.knowledge is not None,
        "has_tools": team.tools is not None,
        "has_learnings": team._learning is not None,
    }


def log_team_telemetry(team: "Team", session_id: str, run_id: Optional[str] = None) -> None:
    """Fire-and-forget telemetry event for a created Team run."""

    from agno.team._init import _set_telemetry

    _set_telemetry(team)
    if not team.telemetry:
        return

    from agno.api._executor import get_telemetry_executor
    from agno.api.team import TeamRunCreate, create_team_run

    try:
        run = TeamRunCreate(session_id=session_id, run_id=run_id, data=get_telemetry_data(team))
        get_telemetry_executor().submit(create_team_run, run)
    except Exception as e:
        log_debug(f"Could not submit Team run telemetry event: {e}")


async def alog_team_telemetry(team: "Team", session_id: str, run_id: Optional[str] = None) -> None:
    """Fire-and-forget telemetry event for a created Team async run."""

    from agno.team._init import _set_telemetry

    _set_telemetry(team)
    if not team.telemetry:
        return

    from agno.api._executor import get_telemetry_executor
    from agno.api.team import TeamRunCreate, create_team_run

    try:
        run = TeamRunCreate(session_id=session_id, run_id=run_id, data=get_telemetry_data(team))
        get_telemetry_executor().submit(create_team_run, run)
    except Exception as e:
        log_debug(f"Could not submit Team run telemetry event: {e}")
