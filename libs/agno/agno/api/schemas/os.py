from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from agno.api.schemas.utils import get_sdk_version


class OSLaunch(BaseModel):
    """Data sent to API to create an OS Launch"""

    os_id: Optional[str] = None
    data: Optional[Dict[Any, Any]] = None

    sdk_version: str = Field(default_factory=get_sdk_version)
