"""Typed public request and response models for Studio tools."""

from __future__ import annotations

from typing import Annotated, Any, Generic, Literal, TypeVar, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("Value must contain at least one non-whitespace character")
    return value


NonBlankString = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(_require_nonblank),
]
ComponentId = Annotated[
    str,
    StringConstraints(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"),
]


class StudioSchema(BaseModel):
    """Base model for the public Studio contract."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class ModelRef(StudioSchema):
    """Reference to a model registered with AgentOS."""

    id: NonBlankString = Field(description="Exact model id returned by list_models.")
    provider: NonBlankString | None = Field(
        default=None,
        description="Registered provider used to disambiguate models that share an id.",
    )
    name: NonBlankString | None = Field(
        default=None,
        description="Registered model name used for final disambiguation.",
    )


class ToolRef(StudioSchema):
    """Reference to a whole toolkit or one registered function."""

    kind: Literal["toolkit", "function"] = Field(description="Kind of registry entry to attach.")
    name: NonBlankString = Field(description="Exact toolkit or function name returned by list_tools.")
    toolkit: NonBlankString | None = Field(
        default=None,
        description="Owning toolkit when selecting one function from a toolkit.",
    )

    @model_validator(mode="after")
    def validate_toolkit_qualifier(self) -> "ToolRef":
        if self.kind == "toolkit" and self.toolkit is not None:
            raise ValueError("'toolkit' is only valid when kind='function'")
        return self


class FunctionRef(StudioSchema):
    """Summary of a registered function available to workflow steps."""

    name: NonBlankString = Field(description="Exact registered function name used by a function workflow step.")
    description: str | None = Field(default=None, description="Registered function documentation, when available.")


class ContextPolicy(StudioSchema):
    """Context behavior for a Studio-created agent or team."""

    include_history: bool = Field(default=True, description="Include prior runs from the current session.")
    history_runs: int | None = Field(
        default=None,
        ge=1,
        description="Number of prior runs to include, or null to use the Studio default.",
    )
    include_datetime: bool = Field(default=True, description="Include the current date and time in context.")

    @model_validator(mode="after")
    def validate_history_policy(self) -> "ContextPolicy":
        if not self.include_history and self.history_runs is not None:
            raise ValueError("'history_runs' cannot be set when history is disabled")
        return self


class ContextPolicyPatch(StudioSchema):
    """Omission-aware patch for context behavior."""

    include_history: bool | None = Field(
        default=None,
        description="Set whether prior runs are included; omit to preserve the current value.",
    )
    history_runs: int | None = Field(
        default=None,
        ge=1,
        description="Set history depth, use null to reset to the Studio default, or omit to preserve it.",
    )
    include_datetime: bool | None = Field(
        default=None,
        description="Set whether current date and time are included; omit to preserve the current value.",
    )

    @model_validator(mode="after")
    def validate_patch(self) -> "ContextPolicyPatch":
        if not self.model_fields_set:
            raise ValueError("Context patch must contain at least one field")
        for field_name in ("include_history", "include_datetime"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"'{field_name}' cannot be set to null")
        if self.include_history is False and "history_runs" in self.model_fields_set and self.history_runs is not None:
            raise ValueError("'history_runs' cannot be set when history is disabled")
        return self


class ComponentRef(StudioSchema):
    """Reference to a versioned agent or team component."""

    component_type: Literal["agent", "team"] = Field(description="Exact type of the referenced component.")
    component_id: ComponentId = Field(description="Exact path-safe component id returned by Studio discovery.")
    version: int | None = Field(
        default=None,
        ge=1,
        description="Pinned component version, or null to resolve the current published version.",
    )


def _validate_unique_member_ids(members: list[ComponentRef]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for member in members:
        if member.component_id in seen:
            duplicates.add(member.component_id)
        seen.add(member.component_id)
    if duplicates:
        duplicate_list = ", ".join(sorted(duplicates))
        raise ValueError(f"Team members must have unique component_id values; duplicates: {duplicate_list}")


class AgentCreate(StudioSchema):
    """Declarative request for creating an agent component."""

    component_id: ComponentId | None = Field(
        default=None,
        description="Stable path-safe component id; deterministically derived from name when omitted.",
    )
    name: NonBlankString = Field(description="Human-readable agent name.")
    instructions: NonBlankString = Field(description="Instructions that define the agent's behavior.")
    description: str | None = Field(default=None, description="Optional concise purpose shown in Studio discovery.")
    model: ModelRef | None = Field(default=None, description="Model reference, or null to use the Studio default.")
    tools: list[ToolRef] = Field(default_factory=list, description="Exact registered tools available to the agent.")
    context: ContextPolicy | None = Field(default=None, description="Context policy, or null to use Studio defaults.")
    if_exists: Literal["error", "return_existing"] = Field(
        default="error",
        description="Create policy: reject an occupied id, or return an identical existing component.",
    )


class AgentPatch(StudioSchema):
    """Omission-aware patch for an agent component.

    Explicit null clears ``description`` and resets ``model`` to the Studio
    default. An empty list clears ``tools``. Other fields reject explicit null.
    """

    name: NonBlankString | None = Field(default=None, description="Replacement agent name; omit to preserve it.")
    instructions: NonBlankString | None = Field(
        default=None,
        description="Replacement agent instructions; omit to preserve them.",
    )
    description: str | None = Field(
        default=None,
        description="Replacement description, explicit null to clear, or omit to preserve it.",
    )
    model: ModelRef | None = Field(
        default=None,
        description="Replacement model, explicit null to reset to the Studio default, or omit to preserve it.",
    )
    tools: list[ToolRef] | None = Field(
        default=None,
        description="Replacement tool list, an empty list to clear, or omit to preserve it.",
    )
    context: ContextPolicyPatch | None = Field(
        default=None,
        description="Context changes to apply; omit to preserve the current policy.",
    )

    @model_validator(mode="after")
    def validate_patch(self) -> "AgentPatch":
        if not self.model_fields_set:
            raise ValueError("Agent patch must contain at least one field")
        for field_name in ("name", "instructions", "tools", "context"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"'{field_name}' cannot be set to null")
        return self


class TeamCreate(StudioSchema):
    """Declarative request for creating a team component."""

    component_id: ComponentId | None = Field(
        default=None,
        description="Stable path-safe component id; deterministically derived from name when omitted.",
    )
    name: NonBlankString = Field(description="Human-readable team name.")
    instructions: NonBlankString = Field(description="Instructions that define how the team collaborates.")
    members: list[ComponentRef] = Field(
        min_length=1,
        description="Ordered agent or team references; stored references resolve to exact published versions.",
    )
    description: str | None = Field(default=None, description="Optional concise purpose shown in Studio discovery.")
    model: ModelRef | None = Field(default=None, description="Model reference, or null to use the Studio default.")
    context: ContextPolicy | None = Field(default=None, description="Context policy, or null to use Studio defaults.")
    if_exists: Literal["error", "return_existing"] = Field(
        default="error",
        description="Create policy: reject an occupied id, or return an identical existing component.",
    )

    @model_validator(mode="after")
    def validate_unique_members(self) -> "TeamCreate":
        _validate_unique_member_ids(self.members)
        return self


class TeamPatch(StudioSchema):
    """Omission-aware patch for a team component."""

    name: NonBlankString | None = Field(default=None, description="Replacement team name; omit to preserve it.")
    instructions: NonBlankString | None = Field(
        default=None,
        description="Replacement team instructions; omit to preserve them.",
    )
    members: list[ComponentRef] | None = Field(
        default=None,
        min_length=1,
        description="Replacement ordered member list; omit to preserve current members.",
    )
    description: str | None = Field(
        default=None,
        description="Replacement description, explicit null to clear, or omit to preserve it.",
    )
    model: ModelRef | None = Field(
        default=None,
        description="Replacement model, explicit null to reset to the Studio default, or omit to preserve it.",
    )
    context: ContextPolicyPatch | None = Field(
        default=None,
        description="Context changes to apply; omit to preserve the current policy.",
    )

    @model_validator(mode="after")
    def validate_patch(self) -> "TeamPatch":
        if not self.model_fields_set:
            raise ValueError("Team patch must contain at least one field")
        for field_name in ("name", "instructions", "members", "context"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"'{field_name}' cannot be set to null")
        if self.members is not None:
            _validate_unique_member_ids(self.members)
        return self


class AgentWorkflowStep(StudioSchema):
    """Workflow step executed by an agent component."""

    kind: Literal["agent"] = Field(description="Discriminator selecting an agent-backed step.")
    step_id: NonBlankString | None = Field(
        default=None,
        description="Stable step id; deterministically derived from name and position when omitted.",
    )
    name: NonBlankString = Field(description="Human-readable name for this workflow step.")
    component_id: ComponentId = Field(description="Exact agent component id returned by Studio discovery.")
    version: int | None = Field(
        default=None,
        ge=1,
        description="Exact published agent version, or null to resolve the current published version.",
    )
    description: str | None = Field(default=None, description="Optional explanation of this step's purpose.")


class TeamWorkflowStep(StudioSchema):
    """Workflow step executed by a team component."""

    kind: Literal["team"] = Field(description="Discriminator selecting a team-backed step.")
    step_id: NonBlankString | None = Field(
        default=None,
        description="Stable step id; deterministically derived from name and position when omitted.",
    )
    name: NonBlankString = Field(description="Human-readable name for this workflow step.")
    component_id: ComponentId = Field(description="Exact team component id returned by Studio discovery.")
    version: int | None = Field(
        default=None,
        ge=1,
        description="Exact published team version, or null to resolve the current published version.",
    )
    description: str | None = Field(default=None, description="Optional explanation of this step's purpose.")


class FunctionWorkflowStep(StudioSchema):
    """Workflow step executed by a registered function."""

    kind: Literal["function"] = Field(description="Discriminator selecting a registered-function step.")
    step_id: NonBlankString | None = Field(
        default=None,
        description="Stable step id; deterministically derived from name and position when omitted.",
    )
    name: NonBlankString = Field(description="Human-readable name for this workflow step.")
    function_name: NonBlankString = Field(description="Exact unique function name returned by list_functions.")
    description: str | None = Field(default=None, description="Optional explanation of this step's purpose.")


WorkflowStep = Annotated[
    Union[AgentWorkflowStep, TeamWorkflowStep, FunctionWorkflowStep],
    Field(discriminator="kind"),
]


class WorkflowCreate(StudioSchema):
    """Declarative request for creating a workflow component."""

    component_id: ComponentId | None = Field(
        default=None,
        description="Stable path-safe component id; deterministically derived from name when omitted.",
    )
    name: NonBlankString = Field(description="Human-readable workflow name.")
    description: str | None = Field(default=None, description="Optional concise purpose shown in Studio discovery.")
    steps: list[WorkflowStep] = Field(
        min_length=1,
        description="Ordered discriminated steps executed by the workflow.",
    )
    if_exists: Literal["error", "return_existing"] = Field(
        default="error",
        description="Create policy: reject an occupied id, or return an identical existing component.",
    )


class WorkflowPatch(StudioSchema):
    """Omission-aware patch for a workflow component."""

    name: NonBlankString | None = Field(default=None, description="Replacement workflow name; omit to preserve it.")
    description: str | None = Field(
        default=None,
        description="Replacement description, explicit null to clear, or omit to preserve it.",
    )
    steps: list[WorkflowStep] | None = Field(
        default=None,
        min_length=1,
        description="Replacement ordered steps; omit to preserve the current workflow.",
    )

    @model_validator(mode="after")
    def validate_patch(self) -> "WorkflowPatch":
        if not self.model_fields_set:
            raise ValueError("Workflow patch must contain at least one field")
        for field_name in ("name", "steps"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"'{field_name}' cannot be set to null")
        return self


ComponentStage = Literal["draft", "published", "code"]
ComponentSource = Literal["studio", "code"]


class ComponentSummary(StudioSchema):
    """Compact component projection used by Studio discovery tools."""

    component_id: ComponentId | None = Field(
        default=None,
        description="Exact component id, or null when a code-defined component has no stable id.",
    )
    component_type: Literal["agent", "team", "workflow"] = Field(description="Component runtime type.")
    name: NonBlankString = Field(description="Human-readable component name.")
    source: ComponentSource = Field(description="Whether the component is stored by Studio or defined in code.")
    latest_version: int | None = Field(
        default=None,
        ge=1,
        description="Latest edit-head version used for optimistic concurrency, or null for code source.",
    )
    latest_stage: ComponentStage = Field(description="Lifecycle stage of the latest stored version.")
    current_version: int | None = Field(
        default=None,
        ge=1,
        description="Published dispatch version, or null when no stored version is current.",
    )


class VersionSummary(StudioSchema):
    """Compact metadata for one stored component version."""

    version: int = Field(ge=1, description="Immutable component version number.")
    stage: Literal["draft", "published"] = Field(description="Lifecycle stage of this version.")
    label: NonBlankString | None = Field(default=None, description="Optional stored version label.")
    is_current: bool = Field(description="Whether this published version is the current dispatch target.")
    created_at: int | None = Field(default=None, description="Creation timestamp, when recorded by the database.")
    updated_at: int | None = Field(default=None, description="Last update timestamp, when recorded by the database.")


class ComponentActionView(StudioSchema):
    """Minimal result for a successful component lifecycle action."""

    component_id: ComponentId = Field(description="Exact affected component id.")
    component_type: Literal["agent", "team", "workflow"] = Field(description="Affected component type.")
    version: int | None = Field(default=None, ge=1, description="Affected version, when applicable.")


class AgentView(StudioSchema):
    """Safe, model-facing projection of an agent configuration."""

    component_id: ComponentId = Field(description="Exact path-safe agent component id.")
    component_type: Literal["agent"] = Field(default="agent", description="Agent view discriminator.")
    name: NonBlankString = Field(description="Human-readable agent name.")
    instructions: NonBlankString = Field(description="Instructions defining the agent's behavior.")
    description: str | None = Field(default=None, description="Optional concise purpose.")
    model: ModelRef = Field(description="Exact resolved model reference.")
    tools: list[ToolRef] = Field(default_factory=list, description="Exact resolved tool references.")
    context: ContextPolicy = Field(description="Resolved context policy.")
    version: int | None = Field(default=None, ge=1, description="Stored version, or null for code source.")
    stage: ComponentStage = Field(description="Lifecycle stage.")
    is_current: bool = Field(description="Whether this version is the current dispatch target.")
    source: ComponentSource = Field(description="Whether this agent is stored by Studio or defined in code.")


class TeamView(StudioSchema):
    """Safe, model-facing projection of a team configuration."""

    component_id: ComponentId = Field(description="Exact path-safe team component id.")
    component_type: Literal["team"] = Field(default="team", description="Team view discriminator.")
    name: NonBlankString = Field(description="Human-readable team name.")
    instructions: NonBlankString = Field(description="Instructions defining team collaboration.")
    members: list[ComponentRef] = Field(default_factory=list, description="Ordered exact member references.")
    description: str | None = Field(default=None, description="Optional concise purpose.")
    model: ModelRef = Field(description="Exact resolved model reference.")
    context: ContextPolicy = Field(description="Resolved context policy.")
    version: int | None = Field(default=None, ge=1, description="Stored version, or null for code source.")
    stage: ComponentStage = Field(description="Lifecycle stage.")
    is_current: bool = Field(description="Whether this version is the current dispatch target.")
    source: ComponentSource = Field(description="Whether this team is stored by Studio or defined in code.")


class WorkflowView(StudioSchema):
    """Safe, model-facing projection of a workflow configuration."""

    component_id: ComponentId = Field(description="Exact path-safe workflow component id.")
    component_type: Literal["workflow"] = Field(default="workflow", description="Workflow view discriminator.")
    name: NonBlankString = Field(description="Human-readable workflow name.")
    description: str | None = Field(default=None, description="Optional concise purpose.")
    steps: list[WorkflowStep] = Field(default_factory=list, description="Ordered discriminated workflow steps.")
    version: int | None = Field(default=None, ge=1, description="Stored version, or null for code source.")
    stage: ComponentStage = Field(description="Lifecycle stage.")
    is_current: bool = Field(description="Whether this version is the current dispatch target.")
    source: ComponentSource = Field(description="Whether this workflow is stored by Studio or defined in code.")


ComponentView = Annotated[
    Union[AgentView, TeamView, WorkflowView],
    Field(discriminator="component_type"),
]


ScheduleTargetType = Literal["agent", "team", "workflow"]


class ScheduleCreate(StudioSchema):
    """Declarative request for a Studio-owned component schedule."""

    name: NonBlankString = Field(
        description="Human-readable schedule name, unique within the authenticated actor's Studio namespace."
    )
    cron: NonBlankString = Field(description="Five-field cron expression controlling the recurring cadence.")
    target_type: ScheduleTargetType = Field(description="Type of published component the schedule dispatches.")
    target_id: ComponentId = Field(description="Exact published component id the schedule dispatches.")
    message: NonBlankString = Field(description="Prompt sent to the component whenever the schedule runs.")
    timezone: NonBlankString = Field(default="UTC", description="IANA timezone used to interpret the cron expression.")
    description: str | None = Field(default=None, description="Optional concise purpose shown in schedule discovery.")


class ScheduleView(StudioSchema):
    """Safe projection of a Studio-owned schedule without its raw payload."""

    schedule_id: NonBlankString = Field(description="Exact scheduler record id.")
    name: NonBlankString = Field(description="Human-readable schedule name.")
    description: str | None = Field(default=None, description="Optional concise purpose.")
    cron: NonBlankString = Field(description="Five-field cron expression controlling the recurring cadence.")
    target_type: ScheduleTargetType = Field(description="Type of component dispatched by the schedule.")
    target_id: ComponentId = Field(description="Exact component id dispatched by the schedule.")
    timezone: NonBlankString = Field(description="IANA timezone used to interpret the cron expression.")
    enabled: bool = Field(description="Whether the scheduler may claim this schedule.")
    next_run_at: int | None = Field(default=None, description="Next planned execution timestamp, when available.")
    owner_actor_id: NonBlankString = Field(description="Authenticated actor that owns this Studio schedule.")
    created_at: int | None = Field(default=None, description="Creation timestamp, when recorded by the database.")
    updated_at: int | None = Field(default=None, description="Last update timestamp, when recorded by the database.")


class ScheduleRunView(StudioSchema):
    """Safe schedule-run projection without raw input, output, errors, or requirements."""

    schedule_run_id: NonBlankString = Field(description="Exact schedule-run record id.")
    schedule_id: NonBlankString = Field(description="Owning schedule record id.")
    attempt: int = Field(ge=1, description="One-based execution attempt number.")
    status: NonBlankString = Field(description="Recorded scheduler execution status.")
    triggered_at: int | None = Field(default=None, description="Timestamp at which execution started.")
    completed_at: int | None = Field(default=None, description="Timestamp at which execution completed.")
    status_code: int | None = Field(default=None, description="Endpoint response status code, when recorded.")
    component_run_id: NonBlankString | None = Field(
        default=None, description="Dispatched component run id, when recorded."
    )
    session_id: NonBlankString | None = Field(
        default=None, description="Dispatched component session id, when recorded."
    )
    has_error: bool = Field(description="Whether the scheduler recorded an error without exposing its contents.")
    has_requirements: bool = Field(description="Whether the run recorded pending requirements without exposing them.")
    created_at: int | None = Field(default=None, description="Creation timestamp, when recorded by the database.")


class ScheduleActionView(StudioSchema):
    """Minimal safe result for a successful schedule lifecycle action."""

    schedule_id: NonBlankString = Field(description="Exact affected schedule id.")
    name: NonBlankString = Field(description="Human-readable affected schedule name.")
    target_type: ScheduleTargetType = Field(description="Type of component dispatched by the schedule.")
    target_id: ComponentId = Field(description="Exact component id dispatched by the schedule.")
    enabled: bool = Field(description="Schedule enabled state immediately before or after the action.")


class StudioError(StudioSchema):
    """Stable structured error returned by Studio operations."""

    code: NonBlankString = Field(description="Stable machine-readable error code.")
    message: NonBlankString = Field(description="Safe actionable error message.")
    details: dict[str, Any] = Field(default_factory=dict, description="Safe structured diagnostic details.")
    retryable: bool = Field(default=False, description="Whether retrying after refreshing state may succeed.")


ResultT = TypeVar("ResultT")


class StudioResult(StudioSchema, Generic[ResultT]):
    """Result envelope containing exactly one typed value or structured error."""

    ok: bool = Field(description="True exactly when data is present and error is absent.")
    status: NonBlankString = Field(description="Stable operation status.")
    data: ResultT | None = Field(default=None, description="Typed successful result.")
    error: StudioError | None = Field(default=None, description="Structured failure result.")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal follow-up guidance.")

    @model_validator(mode="after")
    def validate_result(self) -> "StudioResult[ResultT]":
        has_data = self.data is not None
        has_error = self.error is not None
        if has_data == has_error:
            raise ValueError("StudioResult must contain exactly one of 'data' or 'error'")
        if self.ok != has_data:
            raise ValueError("'ok' must be true for data results and false for error results")
        return self

    def __str__(self) -> str:
        """Serialize tool results as JSON while keeping typed Python returns."""
        return self.model_dump_json(exclude_none=True)


__all__ = [
    "AgentCreate",
    "AgentPatch",
    "AgentView",
    "AgentWorkflowStep",
    "ComponentActionView",
    "ComponentId",
    "ComponentRef",
    "ComponentSource",
    "ComponentStage",
    "ComponentSummary",
    "ComponentView",
    "ContextPolicy",
    "ContextPolicyPatch",
    "FunctionRef",
    "FunctionWorkflowStep",
    "ModelRef",
    "ScheduleActionView",
    "ScheduleCreate",
    "ScheduleRunView",
    "ScheduleTargetType",
    "ScheduleView",
    "StudioError",
    "StudioResult",
    "TeamCreate",
    "TeamPatch",
    "TeamView",
    "TeamWorkflowStep",
    "ToolRef",
    "VersionSummary",
    "WorkflowCreate",
    "WorkflowPatch",
    "WorkflowStep",
    "WorkflowView",
]
