from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from agno.db.schemas.evals import EvalType
from agno.eval import AccuracyResult, AgentAsJudgeResult, PerformanceResult, ReliabilityResult
from agno.eval.accuracy import AccuracyEval
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.eval.performance import PerformanceEval
from agno.eval.reliability import ReliabilityEval
from agno.os.utils import to_utc_datetime


class EvalRunInput(BaseModel):
    agent_id: Optional[str] = Field(None, description="Agent ID to evaluate")
    team_id: Optional[str] = Field(None, description="Team ID to evaluate")

    model_id: Optional[str] = Field(None, description="Model ID to use for evaluation")
    model_provider: Optional[str] = Field(None, description="Model provider name")
    eval_type: EvalType = Field(..., description="Type of evaluation to run (accuracy, performance, or reliability)")
    input: str = Field(..., description="Input text/query for the evaluation", min_length=1)
    additional_guidelines: Optional[str] = Field(None, description="Additional guidelines for the evaluation")
    additional_context: Optional[str] = Field(None, description="Additional context for the evaluation")
    num_iterations: int = Field(1, description="Number of times to run the evaluation", ge=1, le=100)
    name: Optional[str] = Field(None, description="Name for this evaluation run")

    # Accuracy eval specific fields
    expected_output: Optional[str] = Field(None, description="Expected output for accuracy evaluation")

    # AgentAsJudge eval specific fields
    criteria: Optional[str] = Field(None, description="Evaluation criteria for agent-as-judge evaluation")
    scoring_strategy: Optional[Literal["numeric", "binary"]] = Field(
        "binary", description="Scoring strategy: 'numeric' (1-10 with threshold) or 'binary' (PASS/FAIL)"
    )
    threshold: Optional[int] = Field(
        7, description="Score threshold for pass/fail (1-10), only used with numeric scoring", ge=1, le=10
    )

    # Performance eval specific fields
    warmup_runs: int = Field(0, description="Number of warmup runs before measuring performance", ge=0, le=10)

    # Reliability eval specific fields
    expected_tool_calls: Optional[List[str]] = Field(None, description="Expected tool calls for reliability evaluation")


class EvalSchema(BaseModel):
    id: str = Field(..., description="Unique identifier for the evaluation run")

    agent_id: Optional[str] = Field(None, description="Agent ID that was evaluated")
    model_id: Optional[str] = Field(None, description="Model ID used in evaluation")
    model_provider: Optional[str] = Field(None, description="Model provider name")
    team_id: Optional[str] = Field(None, description="Team ID that was evaluated")
    workflow_id: Optional[str] = Field(None, description="Workflow ID that was evaluated")
    name: Optional[str] = Field(None, description="Name of the evaluation run")
    evaluated_component_name: Optional[str] = Field(None, description="Name of the evaluated component")
    eval_type: EvalType = Field(..., description="Type of evaluation (accuracy, performance, or reliability)")
    eval_data: Dict[str, Any] = Field(..., description="Evaluation results and metrics")
    eval_input: Optional[Dict[str, Any]] = Field(None, description="Input parameters used for the evaluation")
    created_at: Optional[datetime] = Field(None, description="Timestamp when evaluation was created")
    updated_at: Optional[datetime] = Field(None, description="Timestamp when evaluation was last updated")

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
            created_at=to_utc_datetime(eval_run.get("created_at")),
            updated_at=to_utc_datetime(eval_run.get("updated_at")),
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
    def from_agent_as_judge_eval(
        cls,
        agent_as_judge_eval: AgentAsJudgeEval,
        result: AgentAsJudgeResult,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> "EvalSchema":
        return cls(
            id=result.run_id,
            name=agent_as_judge_eval.name,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=None,
            model_id=model_id,
            model_provider=model_provider,
            eval_type=EvalType.AGENT_AS_JUDGE,
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
    eval_run_ids: List[str] = Field(..., description="List of evaluation run IDs to delete", min_length=1)


class UpdateEvalRunRequest(BaseModel):
    name: str = Field(..., description="New name for the evaluation run", min_length=1, max_length=255)
