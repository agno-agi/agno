from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from agno.eval.schemas import EvalType


class EvalSchema(BaseModel):
    id: str

    agent_id: Optional[str] = None
    model_id: Optional[str] = None
    model_provider: Optional[str] = None
    team_id: Optional[str] = None
    workflow_id: Optional[str] = None
    name: str
    evaluated_component_name: Optional[str] = None
    eval_type: EvalType
    eval_data: Dict[str, Any]

    @classmethod
    def from_dict(cls, eval_run: Dict[str, Any]) -> "EvalSchema":
        return cls(
            id=eval_run["run_id"],
            name=eval_run["name"],
            agent_id=eval_run["agent_id"],
            model_id=eval_run["model_id"],
            model_provider=eval_run["model_provider"],
            team_id=eval_run["team_id"],
            workflow_id=eval_run["workflow_id"],
            evaluated_component_name=eval_run["evaluated_component_name"],
            eval_type=eval_run["eval_type"],
            eval_data=eval_run["eval_data"],
        )

class DeleteEvalRunsRequest(BaseModel):
    eval_run_ids: List[str]

class UpdateEvalRunRequest(BaseModel):
    name: str