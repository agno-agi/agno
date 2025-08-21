from typing import Optional

from pydantic import BaseModel


class TeamRunCreate(BaseModel):
    """Data sent to API to create a Team Run"""

    session_id: str
    run_id: Optional[str] = None
