from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from agno.db.schemas.evals import EvalType
from agno.eval import AccuracyResult, PerformanceResult, ReliabilityResult
from agno.eval.accuracy import AccuracyEval
from agno.eval.performance import PerformanceEval
from agno.eval.reliability import ReliabilityEval


class EvalRunInput(BaseModel):
    agent_id: Optional[str] = None
    team_id: Optional[str] = None

    model_id: Optional[str] = None
    model_provider: Optional[str] = None
    eval_type: EvalType
    input: str
    additional_guidelines: Optional[str] = None
    additional_context: Optional[str] = None
    num_iterations: Optional[int] = 1
    name: Optional[str] = None

    # Accuracy eval specific fields
    expected_output: Optional[str] = None

    # Performance eval specific fields
    warmup_runs: Optional[int] = 0

    # Reliability eval specific fields
    expected_tool_calls: Optional[List[str]] = None


class EvalSchema(BaseModel):
    id: str

    agent_id: Optional[str] = None
    model_id: Optional[str] = None
    model_provider: Optional[str] = None
    team_id: Optional[str] = None
    workflow_id: Optional[str] = None
    name: Optional[str] = None
    evaluated_component_name: Optional[str] = None
    eval_type: EvalType
    eval_data: Dict[str, Any]
    eval_input: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_dict(cls, eval_run: Dict[str, Any]) -> "EvalSchema":
        return cls(
            id=eval_run["run_id"],
            name=eval_run.get("name"),
            agent_id=eval_run.get("agent_id"),
            model_id=eval_run.get("model_id"),
            model_provider=eval_run.get("model_provider"),
            team_id=eval_run.get("team_id"),
            workflow_id=eval_run.get("workflow_id"),
            evaluated_component_name=eval_run.get("evaluated_component_name"),
            eval_type=eval_run["eval_type"],
            eval_data=eval_run["eval_data"],
            eval_input=eval_run.get("eval_input"),
            created_at=datetime.fromtimestamp(eval_run["created_at"], tz=timezone.utc),
            updated_at=datetime.fromtimestamp(eval_run["updated_at"], tz=timezone.utc),
        )

    @classmethod
    def from_accuracy_eval(cls, accuracy_eval: AccuracyEval, result: AccuracyResult) -> "EvalSchema":
        model_provider = (
            accuracy_eval.agent.model.provider
            if accuracy_eval.agent and accuracy_eval.agent.model
            else accuracy_eval.team.model.provider
            if accuracy_eval.team and accuracy_eval.team.model
            else None
        )
        return cls(
            id=accuracy_eval.eval_id,
            name=accuracy_eval.name,
            agent_id=accuracy_eval.agent.id if accuracy_eval.agent else None,
            team_id=accuracy_eval.team.id if accuracy_eval.team else None,
            workflow_id=None,
            model_id=accuracy_eval.agent.model.id if accuracy_eval.agent else accuracy_eval.team.model.id,  # type: ignore
            model_provider=model_provider,
            eval_type=EvalType.ACCURACY,
            eval_data=asdict(result),
        )

    @classmethod
    def from_performance_eval(
        cls,
        performance_eval: PerformanceEval,
        result: PerformanceResult,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> "EvalSchema":
        return cls(
            id=performance_eval.eval_id,
            name=performance_eval.name,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=None,
            model_id=model_id,
            model_provider=model_provider,
            eval_type=EvalType.PERFORMANCE,
            eval_data=asdict(result),
        )

    @classmethod
    def from_reliability_eval(
        cls,
        reliability_eval: ReliabilityEval,
        result: ReliabilityResult,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> "EvalSchema":
        return cls(
            id=reliability_eval.eval_id,
            name=reliability_eval.name,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=None,
            model_id=model_id,
            model_provider=model_provider,
            eval_type=EvalType.RELIABILITY,
            eval_data=asdict(result),
        )


class DeleteEvalRunsRequest(BaseModel):
    eval_run_ids: List[str]


class UpdateEvalRunRequest(BaseModel):
    name: str
