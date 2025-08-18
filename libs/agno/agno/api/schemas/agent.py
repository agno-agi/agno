from typing import Any, Dict, Optional

from pydantic import BaseModel


class AgentRunCreate(BaseModel):
    """Data sent to API to create an Agent Run"""

    session_id: str
    run_id: Optional[str] = None
    run_data: Optional[Dict[str, Any]] = None
    agent_data: Optional[Dict[str, Any]] = None
