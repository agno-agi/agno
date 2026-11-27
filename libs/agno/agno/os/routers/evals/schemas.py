from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agno.db.schemas.evals import EvalType
from agno.eval import AccuracyResult, AgentAsJudgeResult, PerformanceResult, ReliabilityResult
from agno.eval.accuracy import AccuracyEval
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.eval.performance import PerformanceEval
from agno.eval.reliability import ReliabilityEval
from agno.eval.suite import EvalSuite, SuiteResult
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
    allow_additional_tool_calls: bool = Field(
        False, description="When True, tool calls not in expected_tool_calls are allowed (subset matching)"
    )
    expected_tool_call_arguments: Optional[Dict[str, Union[Dict[str, Any], List[Dict[str, Any]]]]] = Field(
        None,
        description='Expected arguments for specific tool calls, e.g. {"tool_name": {"arg_name": "expected_value"}} or {"tool_name": [{"arg_name": "val1"}, {"arg_name": "val2"}]}',
    )


class EvalSchema(BaseModel):
    id: str = Field(..., description="Unique identifier for the evaluation run")

    agent_id: Optional[str] = Field(None, description="Agent ID that was evaluated")
    model_id: Optional[str] = Field(None, description="Model ID used in evaluation")
    model_provider: Optional[str] = Field(None, description="Model provider name")
    team_id: Optional[str] = Field(None, description="Team ID that was evaluated")
    workflow_id: Optional[str] = Field(None, description="Workflow ID that was evaluated")
    name: Optional[str] = Field(None, description="Name of the evaluation run")
    evaluated_component_name: Optional[str] = Field(None, description="Name of the evaluated component")
    user_id: Optional[str] = Field(None, description="Owner of the evaluation run")
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
            user_id=eval_run.get("user_id"),
            eval_type=eval_run["eval_type"],
            # queue_attempt is the queue fence's bookkeeping, kept out of the response as RunSchema keeps it
            eval_data={key: value for key, value in eval_run["eval_data"].items() if key != "queue_attempt"},
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
            id=result.run_id,
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
            id=result.run_id,
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
            id=result.run_id,
            name=reliability_eval.name,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=None,
            model_id=model_id,
            model_provider=model_provider,
            eval_type=EvalType.RELIABILITY,
            eval_data=asdict(result),
        )

    @classmethod
    def from_suite_result(
        cls,
        eval_suite: EvalSuite,
        result: SuiteResult,
        run_id: str,
        eval_input: Dict[str, Any],
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> "EvalSchema":
        return cls(
            id=run_id,
            name=eval_suite.name or eval_suite.id,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=None,
            eval_type=EvalType.SUITE,
            eval_data=result.to_dict(),
            eval_input=eval_input,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    @classmethod
    def from_running_suite(
        cls,
        eval_suite: EvalSuite,
        total: int,
        run_id: str,
        eval_input: Dict[str, Any],
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> "EvalSchema":
        return cls(
            id=run_id,
            name=eval_suite.name or eval_suite.id,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=None,
            eval_type=EvalType.SUITE,
            eval_data={"summary": {"total": total, "passed": 0, "failed": 0, "status": "RUNNING"}, "cases": []},
            eval_input=eval_input,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )


class EvalSuiteCaseInput(BaseModel):
    # A field Case does not have is refused, as Case(...) refuses an unknown keyword.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Name of the case", min_length=1, max_length=255)
    input: str = Field(..., description="Input text/query for the case", min_length=1)
    agent_id: Optional[str] = Field(None, description="Agent ID the case runs; exactly one of agent_id or team_id")
    team_id: Optional[str] = Field(None, description="Team ID the case runs; exactly one of agent_id or team_id")
    tags: List[str] = Field(default_factory=list, description="Tags the case can be selected by")
    timeout_seconds: Optional[int] = Field(None, description="Per-case timeout in seconds", ge=1)
    criteria: Optional[str] = Field(None, description="What the judge checks the output for", min_length=1)
    judge_mode: Literal["binary", "numeric"] = Field("binary", description="How the judge scores: pass/fail or 1-10")
    judge_threshold: int = Field(7, description="Minimum numeric judge score to pass", ge=1, le=10)
    expected_tool_calls: Optional[List[str]] = Field(None, description="Tool names the run must have called")
    allow_additional_tool_calls: bool = Field(True, description="Whether tools beyond the expected ones are allowed")
    judge_model_id: Optional[str] = Field(
        None, description="Model ID that judges this case; defaults to the eval judge"
    )
    judge_model_provider: Optional[str] = Field(None, description="Provider of judge_model_id, e.g. anthropic")
    session_id: Optional[str] = Field(None, description="Session to run in; cases sharing one continue a conversation")
    session_state: Optional[Dict[str, Any]] = Field(None, description="Session state for the run")
    dependencies: Optional[Dict[str, Any]] = Field(None, description="Dependencies for the run")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Metadata for the run")
    knowledge_filters: Optional[Dict[str, Any]] = Field(None, description="Knowledge filters for the run")

    @model_validator(mode="after")
    def validate_case(self) -> "EvalSuiteCaseInput":
        if bool(self.agent_id) == bool(self.team_id):
            raise ValueError("Each case requires exactly one of agent_id or team_id")
        if bool(self.judge_model_id) != bool(self.judge_model_provider):
            raise ValueError("judge_model_id and judge_model_provider must be set together")
        if not self.criteria and not self.expected_tool_calls:
            raise ValueError("Each case requires criteria or expected_tool_calls")
        return self


class EvalSuiteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Name for the suite run", min_length=1, max_length=255)
    cases: List[EvalSuiteCaseInput] = Field(..., description="The cases to run", min_length=1)
    tag: Optional[str] = Field(None, description="Run only the cases with this tag")
    case_name: Optional[str] = Field(None, description="Run only the case with this name")
    default_timeout: int = Field(120, description="Default per-case timeout in seconds", ge=1)


class EvalSuiteRunInput(BaseModel):
    # A mistyped selector must not run the whole suite.
    model_config = ConfigDict(extra="forbid")

    tag: Optional[str] = Field(None, description="Run only the cases with this tag")
    case_name: Optional[str] = Field(None, description="Run only the case with this name")
    default_timeout: int = Field(120, description="Default per-case timeout in seconds", ge=1)


class EvalSuiteCaseSchema(BaseModel):
    name: str = Field(..., description="Name of the case")
    agent_id: Optional[str] = Field(None, description="Agent ID the case runs")
    team_id: Optional[str] = Field(None, description="Team ID the case runs")
    tags: List[str] = Field(default_factory=list, description="Tags the case can be selected by")
    timeout_seconds: Optional[int] = Field(
        None, description="Per-case timeout in seconds; null when the case runs with the run's default_timeout"
    )


class EvalSuiteSchema(BaseModel):
    id: str = Field(..., description="Unique identifier for the eval suite")
    name: Optional[str] = Field(None, description="Name of the eval suite")
    description: Optional[str] = Field(None, description="Description of the eval suite")
    cases: List[EvalSuiteCaseSchema] = Field(default_factory=list, description="The cases the suite runs")

    @classmethod
    def from_eval_suite(cls, eval_suite: EvalSuite) -> "EvalSuiteSchema":
        return cls(**eval_suite.to_dict())


class DeleteEvalRunsRequest(BaseModel):
    eval_run_ids: List[str] = Field(..., description="List of evaluation run IDs to delete", min_length=1)


class UpdateEvalRunRequest(BaseModel):
    name: str = Field(..., description="New name for the evaluation run", min_length=1, max_length=255)
