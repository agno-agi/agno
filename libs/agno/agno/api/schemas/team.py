from typing import Any, Dict, Optional

from pydantic import BaseModel


class TeamSessionCreate(BaseModel):
    """Data sent to API to create a Team Session"""

    session_id: str
    team_data: Optional[Dict[str, Any]] = None


class TeamRunCreate(BaseModel):
    """Data sent to API to create a Team Run"""

    session_id: str
    team_session_id: Optional[str] = None
    run_id: Optional[str] = None
    run_data: Optional[Dict[str, Any]] = None
    team_data: Optional[Dict[str, Any]] = None


class TeamCreate(BaseModel):
    """Data sent to API to create aTeam"""

    team_id: str
    parent_team_id: Optional[str] = None
    app_id: Optional[str] = None
    workflow_id: Optional[str] = None
    name: Optional[str] = None
    config: Dict[str, Any]
