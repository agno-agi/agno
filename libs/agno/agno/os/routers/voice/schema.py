from typing import Optional

from pydantic import BaseModel, Field


class VoicePipeResponse(BaseModel):
    id: str = Field(..., description="Voice pipe ID")
    agent_id: Optional[str] = Field(None, description="ID of the agent the pipe speaks for")
    agent_name: Optional[str] = Field(None, description="Name of the agent the pipe speaks for")
    path: str = Field(..., description="WebSocket path to connect to")
