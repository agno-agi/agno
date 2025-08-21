from typing import Optional

from pydantic import BaseModel, Field

from agno.api.schemas.utils import get_sdk_version


class OSLaunch(BaseModel):
    """Data sent to API to create an OS Launch"""

    os_id: Optional[str] = None

    sdk_version: str = Field(default_factory=get_sdk_version)
