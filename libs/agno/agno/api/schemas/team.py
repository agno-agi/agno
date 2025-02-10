from typing import Optional

from pydantic import BaseModel


class TeamSchema(BaseModel):
    """Schema for team data returned by the API."""

    id_team: str
    name: str
    url: str


class TeamIdentifier(BaseModel):
    id_team: Optional[str] = None
    team_url: Optional[str] = None
