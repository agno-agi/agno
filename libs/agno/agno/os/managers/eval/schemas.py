from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from agno.eval import AccuracyResult, PerformanceResult, ReliabilityResult
from agno.eval.schemas import EvalType


class AccuracyEvalInput(BaseModel):
    input: str
    expected_output: str
    additional_guidelines: Optional[str] = None
    num_iterations: Optional[int] = 1
    name: Optional[str] = None

    agent_id: Optional[str] = None
    team_id: Optional[str] = None
    workflow_id: Optional[str] = None


class ReliabilityEvalInput(BaseModel):
    input: str
    expected_tool_calls: List[str]
    additional_guidelines: Optional[str] = None
    num_iterations: Optional[int] = 1
    name: Optional[str] = None


class PerformanceEvalInput(BaseModel):
    input: str
    expected_output: str
    additional_guidelines: Optional[str] = None
    num_iterations: Optional[int] = 3
    warmup_runs: Optional[int] = 0
    name: Optional[str] = None


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
    created_at: datetime
    updated_at: datetime

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
            created_at=datetime.fromtimestamp(eval_run["created_at"], tz=timezone.utc),
            updated_at=datetime.fromtimestamp(eval_run["updated_at"], tz=timezone.utc),
        )

    @classmethod
    def from_accuracy_result(cls, result: AccuracyResult) -> "EvalSchema":
        return cls()

    @classmethod
    def from_performance_result(cls, result: PerformanceResult) -> "EvalSchema":
        return cls()

    @classmethod
    def from_reliability_result(cls, result: ReliabilityResult) -> "EvalSchema":
        return cls()


class DeleteEvalRunsRequest(BaseModel):
    eval_run_ids: List[str]


class UpdateEvalRunRequest(BaseModel):
    name: str
