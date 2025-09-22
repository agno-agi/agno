from typing import Optional

from pydantic import BaseModel


class AwsBuildContext(BaseModel):
    aws_region: Optional[str] = None
    aws_profile: Optional[str] = None
