from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PlaygroundEndpointCreate(BaseModel):
    """Data sent to API to create a playground endpoint"""

    endpoint: str
    playground_data: Optional[Dict[str, Any]] = None


class PlaygroundEndpointSchema(BaseModel):
    """Schema for a playground endpoint returned by API"""

    id_workspace: Optional[UUID] = None
    id_playground_endpoint: Optional[UUID] = None
    endpoint: str
    playground_data: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)
