"""Goal request and response schemas."""

from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agno.os.schema import InternalServerErrorResponse
from agno.registry._reserved import MINI_AGENT_ID

# Every Company route reads the Company tables, which a database from agno 3.2 must migrate first.
MIGRATION_REQUIRED_RESPONSE: Dict[Union[int, str], Dict[str, Any]] = {
    500: {
        "description": "Internal server error, or the database must be migrated first (migration_required_error)",
        "content": {
            "application/json": {
                "example": {
                    "detail": "Table agno_company_products was written by an older version of Agno and must be "
                    "renamed to agno_company_goals. Apply the pending migrations.",
                    "error_id": "migration_required_error",
                    "error_type": "migration_required_error",
                }
            }
        },
        "model": InternalServerErrorResponse,
    }
}


def refuse_product_id(request: Request) -> None:
    """Refuse ``product_id``, the filter a client written for agno 3.2 sends.

    It is not an alias of ``goal_id``. Ignored, it would answer with the records of every Goal.
    """
    if "product_id" in request.query_params:
        raise HTTPException(status_code=422, detail="product_id is not a filter of this route. Use goal_id.")


def _refuse_purpose(data: Any) -> Any:
    """Refuse ``purpose``, the field a client written for agno 3.2 sends. Dropped, the objective would stay as it is."""
    if isinstance(data, dict) and "purpose" in data:
        raise ValueError("purpose is not a field of a Goal. Use objective.")
    return data


class GoalCreate(BaseModel):
    name: str = Field(..., min_length=1)
    objective: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def refuse_purpose(cls, data: Any) -> Any:
        return _refuse_purpose(data)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must be a non-empty string")
        return value


class GoalUpdate(BaseModel):
    name: Optional[str] = None
    objective: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def refuse_purpose(cls, data: Any) -> Any:
        return _refuse_purpose(data)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> str:
        if value is None or not value.strip():
            raise ValueError("name must be a non-empty string")
        return value


class TaskCounts(BaseModel):
    backlog: int = 0
    ready: int = 0
    in_progress: int = 0
    in_review: int = 0
    done: int = 0
    cancelled: int = 0


class ProjectCounts(BaseModel):
    tasks: TaskCounts = Field(default_factory=TaskCounts)


class GoalCounts(ProjectCounts):
    projects: int = Field(0, description="Non-archived Projects in proposed or active status")


class GoalResponse(BaseModel):
    counts: GoalCounts = Field(default_factory=GoalCounts)
    id: str
    name: str
    objective: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: int
    updated_at: Optional[int] = None
    deleted_at: Optional[int] = None


ProjectStatus = Literal["proposed", "active", "done", "cancelled"]
TaskStatus = Literal["backlog", "ready", "in_progress", "in_review", "done", "cancelled"]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    outcome: Optional[str] = None
    target_date: Optional[int] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> str:
        if value is None or not value.strip():
            raise ValueError("name must be a non-empty string")
        return value


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    outcome: Optional[str] = None
    target_date: Optional[int] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> str:
        if value is None or not value.strip():
            raise ValueError("name must be a non-empty string")
        return value


class ProjectResponse(BaseModel):
    counts: ProjectCounts = Field(default_factory=ProjectCounts)
    goal_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    outcome: Optional[str] = None
    target_date: Optional[int] = None
    id: str
    status: ProjectStatus
    user_id: Optional[str] = None
    transitions: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: int
    updated_at: Optional[int] = None
    deleted_at: Optional[int] = None


class ProjectTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: ProjectStatus
    reason: str = Field(..., min_length=1)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A transition requires a non-empty reason")
        return value


def _ready_executor(executor_type: Any, executor_id: Any) -> Any:
    """The executor a Task enters Ready with: the one named, or Mini Agent when none is named."""
    if executor_type is None and executor_id is None:
        return "agent", MINI_AGENT_ID
    if executor_type is None or executor_id is None or not executor_id.strip():
        raise ValueError("Give executor_type and executor_id together, or leave both out to use Mini Agent")
    return executor_type, executor_id


class TaskCreate(BaseModel):
    executor_type: Optional[Literal["agent", "team", "workflow"]] = None
    executor_id: Optional[str] = Field(None, min_length=1)
    model_config = ConfigDict(extra="forbid")
    goal_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    brief: Optional[str] = None
    project_id: str = Field(..., min_length=1)
    evidence: Optional[List[Dict[str, Any]]] = None
    # In progress and later stages need a run, so they are reached through POST /company/tasks/{id}/runs.
    status: Literal["backlog", "ready", "cancelled"] = "backlog"

    @field_validator("title")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> str:
        if value is None or not value.strip():
            raise ValueError("title must be a non-empty string")
        return value

    @model_validator(mode="after")
    def validate_executor(self) -> "TaskCreate":
        if self.status == "ready":
            self.executor_type, self.executor_id = _ready_executor(self.executor_type, self.executor_id)
        return self


class TaskUpdate(BaseModel):
    executor_type: Optional[Literal["agent", "team", "workflow"]] = None
    executor_id: Optional[str] = Field(None, min_length=1)
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = None
    brief: Optional[str] = None
    project_id: Optional[str] = None
    evidence: Optional[List[Dict[str, Any]]] = None

    @field_validator("title")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> str:
        if value is None or not value.strip():
            raise ValueError("title must be a non-empty string")
        return value


class TaskLastRun(BaseModel):
    status: str
    triggered_at: Optional[int] = None
    completed_at: Optional[int] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
    attempt: Optional[int] = None


class TaskTransitionOption(BaseModel):
    target: TaskStatus
    allowed: bool
    reason: Optional[str] = None
    # In progress is entered with POST /company/tasks/{id}/runs, not a transition.
    starts_run: bool = False


class TaskResponse(BaseModel):
    @field_validator("transitions", mode="before")
    @classmethod
    def public_transitions(cls, value):
        from agno.db.schemas.tasks import public_task

        return public_task({"transitions": value})["transitions"]

    goal_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    brief: Optional[str] = None
    project_id: Optional[str] = None
    evidence: Optional[List[Dict[str, Any]]] = None
    origin: Optional[str] = None
    routine_id: Optional[str] = None
    dedupe_key: Optional[str] = None
    id: str
    status: TaskStatus
    user_id: Optional[str] = None
    transitions: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: int
    updated_at: Optional[int] = None
    deleted_at: Optional[int] = None
    executor_type: Optional[str] = None
    executor_id: Optional[str] = None
    accepted_by: Optional[str] = None
    accepted_at: Optional[int] = None

    session_id: Optional[str] = None
    job_id: Optional[str] = None
    sandboxed: bool = False
    metadata: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    last_run: Optional[TaskLastRun] = None
    allowed_transitions: List[TaskTransitionOption] = Field(default_factory=list)


class TaskTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: TaskStatus
    reason: str = Field(..., min_length=1)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A transition requires a non-empty reason")
        return value

    executor_type: Optional[Literal["agent", "team", "workflow"]] = None
    executor_id: Optional[str] = Field(None, min_length=1)

    @model_validator(mode="after")
    def validate_executor(self) -> "TaskTransition":
        if self.target == "ready":
            # With no executor named, the route keeps the Task's executor, or names Mini Agent when it has none.
            if self.executor_type is not None or self.executor_id is not None:
                self.executor_type, self.executor_id = _ready_executor(self.executor_type, self.executor_id)
        elif self.executor_type is not None or self.executor_id is not None:
            raise ValueError("Only Ready can set an executor")
        return self


class WikiWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    expected_version: int = Field(..., ge=0, strict=True)


class DecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(..., min_length=1)
    reasoning: Optional[str] = None
    context: Optional[str] = None
    outcome: Optional[str] = None


class WikiPageResponse(BaseModel):
    path: str
    size_bytes: int
    version: Optional[int] = None
    updated_at: Optional[int] = None
    user_id: Optional[str] = None


class WikiReadResponse(BaseModel):
    content: str
    metadata: WikiPageResponse


class CompanyFileReadResponse(WikiReadResponse):
    """One read of a file in tasks/ or notes/. A long file takes more than one read."""

    # Where the next read starts. Null when this read reached the end of the file.
    next_offset: Optional[int] = None


class DecisionResponse(BaseModel):
    id: str
    decision: str
    reasoning: Optional[str] = None
    context: Optional[str] = None
    outcome: Optional[str] = None
    decision_type: Optional[str] = None
    alternatives: Optional[List[str]] = None
    confidence: Optional[float] = None
    outcome_quality: Optional[str] = None
    tags: Optional[List[str]] = None
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    team_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TaskRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempt: Optional[int] = Field(None, ge=1, strict=True)
    executor_type: Optional[Literal["agent", "team", "workflow"]] = None
    executor_id: Optional[str] = Field(None, min_length=1)

    @model_validator(mode="after")
    def validate_executor(self) -> "TaskRunCreate":
        if self.executor_type is not None or self.executor_id is not None:
            if self.executor_type is None or self.executor_id is None or not self.executor_id.strip():
                raise ValueError("A direct start requires an executor type and id")
        return self
