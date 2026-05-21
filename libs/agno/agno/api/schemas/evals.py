from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from agno.api.schemas.utils import get_sdk_version
from agno.db.schemas.evals import EvalType


class EvalRunCreate(BaseModel):
    """Data sent to the telemetry API to create an Eval run event"""

    run_id: str
    eval_type: EvalType
    data: Optional[Dict[Any, Any]] = None

    sdk_version: str = Field(default_factory=get_sdk_version)
