from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from agno.api.schemas.utils import TelemetryRunEventType, get_sdk_version


class TeamRunCreate(BaseModel):
    """Data sent to API to create a Team Run"""

    session_id: str
    run_id: Optional[str] = None
    data: Optional[Dict[Any, Any]] = None

    sdk_version: str = Field(default_factory=get_sdk_version)
    type: TelemetryRunEventType = TelemetryRunEventType.TEAM
