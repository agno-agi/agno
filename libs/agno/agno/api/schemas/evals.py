from pydantic import BaseModel

from agno.db.schemas.evals import EvalType


class EvalRunCreate(BaseModel):
    """Data sent to the telemetry API to create an Eval run event"""

    run_id: str
    eval_type: EvalType
