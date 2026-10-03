"""Result envelope and workflow step schema for the Studio control plane.

Every StudioTools tool returns ``str(StudioResult)``: one JSON shape with a
stable machine-readable status, optional data, a typed error, and warnings.
The model branches on ``error.code`` instead of parsing prose; ``retryable``
says whether re-reading state and retrying can succeed.

Inputs stay flat (plain parameters) except where structure is real: workflow
steps are a discriminated ``WorkflowStepSpec`` tree, because compound steps
(parallel, loop, condition, router) are genuinely recursive.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

# Stable error codes. A code is a contract: tests pin them and models branch
# on them, so add new ones rather than renaming.
StudioErrorCode = Literal[
    "component_not_found",
    "component_conflict",
    "version_conflict",
    "version_not_found",
    "component_archived",
    "component_not_published",
    "dependency_conflict",
    "shared_component",
    "not_owner",
    "invalid_request",
    "invalid_component_id",
    "model_not_found",
    "tool_not_found",
    "tool_not_allowed",
    "function_not_found",
    "knowledge_not_found",
    "schema_not_found",
    "memory_manager_not_found",
    "learning_not_found",
    "ambiguous_reference",
    "schedule_not_found",
    "schedule_conflict",
    "target_not_published",
    "db_not_configured",
    # The catalog table exists but is on an older shape. Distinct from
    # db_not_configured, where there is no catalog at all: the remedy is a
    # migration, not configuration, and the message carries the command.
    "db_schema_stale",
    "validation_failed",
    # The target is already on this dispatch chain, or the chain is at
    # max_dispatch_depth. Deliberately not retryable: retrying the same
    # dispatch is the loop the refusal exists to stop.
    "dispatch_refused",
    "internal_error",
]


class StudioError(BaseModel):
    """Structured failure: a stable code, a safe message, safe details."""

    code: StudioErrorCode
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class StudioResult(BaseModel):
    """The one envelope every Studio tool returns, serialized as JSON.

    Exactly one of ``data`` / ``error`` is set. ``status`` is a short stable
    verb ("created", "edited", "published", "archived", ...) on success and
    "error" on failure. ``warnings`` carry non-fatal follow-ups (for example
    the count of schedules disabled by an archive).
    """

    ok: bool
    status: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[StudioError] = None
    warnings: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _exactly_one_side(self) -> "StudioResult":
        if self.ok and (self.error is not None or self.data is None):
            raise ValueError("ok results carry data and no error")
        if not self.ok and self.error is None:
            raise ValueError("failed results carry an error")
        return self

    def __str__(self) -> str:
        return json.dumps(self.model_dump(exclude_none=True), default=str)


def ok_result(status: str, warnings: Optional[List[str]] = None, **data: Any) -> str:
    return str(StudioResult(ok=True, status=status, data=data, warnings=warnings or []))


def error_result(
    code: StudioErrorCode,
    message: str,
    retryable: bool = False,
    warnings: Optional[List[str]] = None,
    **details: Any,
) -> str:
    return str(
        StudioResult(
            ok=False,
            status="error",
            error=StudioError(code=code, message=message, details=details, retryable=retryable),
            warnings=warnings or [],
        )
    )


class WorkflowStepSpec(BaseModel):
    """One workflow step, plain or compound.

    ``type`` defaults to "step": a plain step names exactly one executor via
    ``agent_id``, ``team_id`` or ``function_name`` (no discriminator needed -
    which field is present decides). Compound steps carry nested ``steps``
    (or ``choices`` for a router) of this same shape:

    - parallel: run ``steps`` concurrently
    - loop: repeat ``steps`` up to ``max_iterations``; ``end_condition_function``
      (a registered function) may stop earlier
    - condition: run ``steps`` when ``evaluator_function`` returns truthy,
      else ``else_steps``
    - router: ``selector_function`` picks from ``choices``
    - steps: a named sequential group
    """

    type: Literal["step", "parallel", "loop", "condition", "router", "steps"] = "step"
    name: Optional[str] = None
    description: Optional[str] = None
    # Plain step executors (exactly one for type="step")
    agent_id: Optional[str] = None
    team_id: Optional[str] = None
    function_name: Optional[str] = None
    # Compound bodies
    steps: Optional[List["WorkflowStepSpec"]] = None
    else_steps: Optional[List["WorkflowStepSpec"]] = None
    choices: Optional[List["WorkflowStepSpec"]] = None
    max_iterations: Optional[int] = None
    end_condition_function: Optional[str] = None
    evaluator_function: Optional[str] = None
    selector_function: Optional[str] = None

    @model_validator(mode="after")
    def _one_executor_per_plain_step(self) -> "WorkflowStepSpec":
        executors = [x for x in (self.agent_id, self.team_id, self.function_name) if x]
        if self.type == "step":
            if len(executors) != 1:
                raise ValueError("a plain step names exactly one of agent_id, team_id, or function_name")
        elif executors:
            raise ValueError(f"a {self.type} step does not take an executor; put it in a nested step")
        if self.type in ("parallel", "loop", "steps", "condition") and not self.steps:
            raise ValueError(f"a {self.type} step requires nested steps")
        if self.type == "router":
            if not self.choices:
                raise ValueError("a router step requires choices")
            if not self.selector_function:
                raise ValueError("a router step requires selector_function")
        if self.type == "condition" and not self.evaluator_function:
            raise ValueError("a condition step requires evaluator_function")
        return self


WorkflowStepSpec.model_rebuild()
