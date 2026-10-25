"""Validated declarations shared by code, YAML and blank-deployment setup."""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agno.db.schemas.sources import validate_source_fields


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


class AutoAccept(BaseModel):
    """Human-authored bounds; identifiers refer to existing records and server checks."""

    model_config = ConfigDict(extra="forbid", strict=True)
    executor_type: Literal["agent", "team", "workflow"]
    executor_id: str = Field(min_length=1)
    source_ids: Optional[List[str]] = None
    work_scope: Optional[AcceptanceScope] = None
    required_checks: List[str] = Field(default_factory=lambda: ["executor_registered"], min_length=1)
    limits: AcceptanceLimits
    complete_projects: bool = False


class Routine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    template: Optional[Literal["refresh", "intake", "summary"]] = None
    executor_type: Literal["agent", "team", "workflow"]
    executor_id: str = Field(min_length=1)
    cron_expr: Optional[str] = None
    timezone: str = "UTC"
    instructions: Optional[str] = None
    auto_accept: Union[Literal[False], AutoAccept] = False

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
