from typing import Any, Dict, Optional

from pydantic import BaseModel


class AgentSessionCreate(BaseModel):
    """Data sent to API to create an Agent Session"""

    session_id: str
    agent_data: Optional[Dict[str, Any]] = None


class AgentRunCreate(BaseModel):
    """Data sent to API to create an Agent Run"""

    session_id: str
    run_id: Optional[str] = None
    run_data: Optional[Dict[str, Any]] = None
    agent_data: Optional[Dict[str, Any]] = None
