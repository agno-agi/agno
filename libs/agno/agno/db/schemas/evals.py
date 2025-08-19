from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel


class EvalType(str, Enum):
    ACCURACY = "accuracy"
    PERFORMANCE = "performance"
    RELIABILITY = "reliability"


class EvalFilterType(str, Enum):
    AGENT = "agent"
    TEAM = "team"
    WORKFLOW = "workflow"


class EvalRunRecord(BaseModel):
    """Evaluation run results stored in the database"""

    agent_id: Optional[str] = None
    model_id: Optional[str] = None
    model_provider: Optional[str] = None
    team_id: Optional[str] = None
    workflow_id: Optional[str] = None
    name: Optional[str] = None
    evaluated_component_name: Optional[str] = None

    run_id: str
    eval_type: EvalType
    eval_data: Dict[str, Any]
    eval_input: Optional[Dict[str, Any]] = None
