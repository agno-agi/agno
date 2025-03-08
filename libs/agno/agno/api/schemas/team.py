


from typing import Any, Dict, Optional

from pydantic import BaseModel


class TeamSessionCreate(BaseModel):
    """Data sent to API to create an Team Session"""

    session_id: str
    team_data: Optional[Dict[str, Any]] = None


class TeamRunCreate(BaseModel):
    """Data sent to API to create an Team Run"""

    session_id: str
    run_id: Optional[str] = None
    run_data: Optional[Dict[str, Any]] = None
    team_data: Optional[Dict[str, Any]] = None
