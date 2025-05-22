from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel


class EvalType(str, Enum):
    ACCURACY = "accuracy"
    PERFORMANCE = "performance"
    RELIABILITY = "reliability"


class EvalRunCreate(BaseModel):
    """Data sent to the API to create an evaluation run"""

    agent_id: Optional[str] = None
    model_id: Optional[str] = None
    model_provider: Optional[str] = None
    team_id: Optional[str] = None
    name: Optional[str] = None
    evaluated_entity_name: Optional[str] = None

    run_id: str
    eval_type: EvalType
    eval_data: Dict[str, Any]
