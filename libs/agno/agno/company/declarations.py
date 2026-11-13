"""Validated declarations shared by code, YAML and blank-deployment setup."""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from agno.db.schemas.sources import validate_source_fields
from agno.registry._reserved import MINI_AGENT_ID


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = None
    type: Literal["git", "markdown", "website"]
    reference: str
    credential_ref: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_reader(self):
        validate_source_fields(self.model_dump(exclude={"id"}))
        return self


class AcceptanceScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    product_ids: Optional[List[str]] = None
    project_ids: Optional[List[Optional[str]]] = None


class AcceptanceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_acceptances: int = Field(1, ge=1)
    expires_at: int = Field(ge=1)


def _default_executor(data: Any) -> Any:
    """Leave out a null executor so Mini Agent applies; one executor field without the other is an error."""
    if isinstance(data, dict):
        named = [key for key in ("executor_type", "executor_id") if data.get(key) is not None]
        if len(named) == 1:
            raise ValueError("Give executor_type and executor_id together, or leave both out to use Mini Agent")
        if not named:
            data = {key: value for key, value in data.items() if key not in ("executor_type", "executor_id")}
    return data


class AutoAccept(BaseModel):
    """What happens to a Routine's proposals with no person. Every field has a default.

    The Routine's Tasks are accepted and run, and finished work waits In review for a person. A Task
    runs on the executor its proposal suggests, or on default_executor when it suggests none.
    executors limits which executors a proposal may suggest; left out, any registered executor is
    accepted. Mini Agent and default_executor are always allowed. approve_projects also approves a
    Project the Routine proposed when one of its Tasks is accepted; turn it off for a person to
    approve each Project. max_open is the most Tasks of this Routine that may be Ready, In progress
    or In review at once; it applies when limits is not set. limits adds a lifetime count and an expiry.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    default_executor: str = Field(default=MINI_AGENT_ID, min_length=1)
    executors: Optional[List[str]] = None
    source_ids: Optional[List[str]] = None
    work_scope: Optional[AcceptanceScope] = None
    required_checks: List[str] = Field(default_factory=lambda: ["executor_registered"], min_length=1)
    limits: Optional[AcceptanceLimits] = None
    complete_projects: bool = False
    approve_projects: bool = True
    max_open: int = Field(5, ge=1)

    # The executor_type a policy was sent or saved with. The policy names executors by ID, so this is
    # kept only to be checked against the registered component.
    _sent_executor_type: Optional[str] = PrivateAttr(default=None)

    @model_validator(mode="wrap")
    @classmethod
    def read_saved_executor(cls, data: Any, handler: Any) -> Any:
        """A policy that names executor_type and executor_id allows that one executor, uses it by
        default, and approves no Project unless it says so."""
        sent = data.get("executor_type") if isinstance(data, dict) else None
        if isinstance(data, dict) and ("executor_type" in data or "executor_id" in data):
            if "default_executor" in data or "executors" in data:
                # The Routine API returns both forms, so a policy read from it can be sent back as it is.
                if data.get("executor_id") != data.get("default_executor"):
                    raise ValueError("executor_id and default_executor name different executors: send one")
                data = {key: value for key, value in data.items() if key not in ("executor_type", "executor_id")}
            else:
                data = _default_executor(data)
                executor_id = data.get("executor_id")
                data = {key: value for key, value in data.items() if key not in ("executor_type", "executor_id")}
                if executor_id is not None:
                    # This shape is from when a policy approved no Project. It reads the same from a
                    # request and from storage.
                    data = {
                        "approve_projects": False,
                        **data,
                        "default_executor": executor_id,
                        "executors": [executor_id],
                    }
        policy = handler(data)
        if not isinstance(data, AutoAccept):
            # A policy passed as an object keeps the type it was built with.
            policy._sent_executor_type = sent
        return policy


class Routine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    template: Optional[Literal["refresh", "intake", "summary"]] = None
    executor_type: Literal["agent", "team", "workflow"] = "agent"
    executor_id: str = Field(default=MINI_AGENT_ID, min_length=1)
    cron_expr: Optional[str] = None
    timezone: str = "UTC"
    enabled: bool = Field(default=True, description="Initial enabled state; existing routines retain later edits.")
    instructions: Optional[str] = None
    auto_accept: Union[Literal[False], AutoAccept] = Field(
        default=False,
        description="True is AutoAccept() with every default. Applied when the Routine is first created; "
        "an existing Routine keeps its stored setting.",
    )

    @model_validator(mode="before")
    @classmethod
    def default_executor(cls, data: Any) -> Any:
        """A Routine with no executor runs on Mini Agent, and auto_accept=True is the default policy."""
        data = _default_executor(data)
        if isinstance(data, dict) and data.get("auto_accept") is True:
            data = {**data, "auto_accept": AutoAccept()}
        return data

    @model_validator(mode="after")
    def validate_schedule(self):
        from agno.scheduler.cron import validate_cron_expr, validate_timezone

        if self.instructions is not None and not self.instructions.strip():
            raise ValueError("Routine instructions must be nonempty")
        if self.template is None and not self.instructions:
            raise ValueError("Routine instructions are required without a template")
        if self.cron_expr is not None and not validate_cron_expr(self.cron_expr):
            raise ValueError("Invalid cron expression")
        if not validate_timezone(self.timezone):
            raise ValueError("Invalid timezone")
        return self


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = None
    name: str = Field(min_length=1)
    purpose: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    sources: List[Source] = Field(default_factory=list)
    routines: List[Routine] = Field(default_factory=list)


class CompanyDeclarations(BaseModel):
    """Validated YAML declarations; runtime dependencies are supplied in code."""

    model_config = ConfigDict(extra="forbid")
    products: List[Product] = Field(default_factory=list)


class IntakeProposal(BaseModel):
    """An actionable proposal selected by the reader, not one Task per file."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1)
    brief: str = Field(min_length=1)
    proposal_key: str = Field(min_length=1)
    evidence_links: List[str] = Field(min_length=1)
    evidence_hashes: Dict[str, str] = Field(min_length=1, description="Observed content hash for each selected link")
