from typing import Any, Dict, Optional

from pydantic import BaseModel


class AgentRunCreate(BaseModel):
    """Data sent to API to create an Agent Run"""
    agent_data: Optional[Dict[str, Any]] = None

