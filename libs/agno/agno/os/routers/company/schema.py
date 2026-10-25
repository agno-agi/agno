"""Product request and response schemas."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1)
    purpose: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must be a non-empty string")
        return value


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    purpose: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

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


class ProductCounts(ProjectCounts):
    projects: int = Field(0, description="Non-archived Projects in proposed or active status")


class ProductResponse(BaseModel):
    counts: ProductCounts = Field(default_factory=ProductCounts)
    id: str
    name: str
    purpose: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: int
    updated_at: Optional[int] = None
    deleted_at: Optional[int] = None


ProjectStatus = Literal["proposed", "active", "done", "cancelled"]
TaskStatus = Literal["backlog", "ready", "in_progress", "in_review", "done", "cancelled"]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(..., min_length=1)
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
    product_id: str = Field(..., min_length=1)
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


class TaskCreate(BaseModel):
    executor_type: Optional[Literal["agent", "team", "workflow"]] = None
    executor_id: Optional[str] = Field(None, min_length=1)
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    brief: Optional[str] = None
    project_id: str = Field(..., min_length=1)
    evidence: Optional[List[Dict[str, Any]]] = None

    @field_validator("title")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> str:
        if value is None or not value.strip():
            raise ValueError("title must be a non-empty string")
        return value


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


class TaskResponse(BaseModel):
    @field_validator("transitions", mode="before")
    @classmethod
    def public_transitions(cls, value):
        from agno.db.schemas.tasks import public_task

        return public_task({"transitions": value})["transitions"]

    product_id: str = Field(..., min_length=1)
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
            if self.executor_type is None or self.executor_id is None or not self.executor_id.strip():
                raise ValueError("Ready requires an executor type and id")
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
    attempt: int = Field(1, ge=1, strict=True)
