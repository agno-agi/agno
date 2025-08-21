from typing import Optional

from pydantic import BaseModel


class AgentRunCreate(BaseModel):
    """Data sent to API to create an Agent Run"""

    session_id: str
    run_id: Optional[str] = None
