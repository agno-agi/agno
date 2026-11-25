"""Pydantic request/response models for the trigger API."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

TargetType = Literal["agent", "team", "workflow"]


def _kinds(value: Optional[List[str]], what: str) -> Optional[List[str]]:
    if value is None:
        return None
    kinds = [kind.strip() for kind in value]
    if not all(kinds):
        raise ValueError(f"{what} holds event kinds, e.g. issues.opened")
    return kinds


class TriggerCreate(BaseModel):
    name: str = Field(..., max_length=255)
    source_id: str = Field(..., max_length=255)
    # The event kinds that start a run, e.g. ["issues.opened"].
    events: List[str] = Field(..., min_length=1)
    target_type: TargetType
    target_id: str = Field(..., max_length=255)
    # The instruction for the run. The event is added after it.
    input: str = Field(..., min_length=1)
    # Event kinds that only continue a conversation this trigger already started.
    continue_on: Optional[List[str]] = None
    # The source's own filter, e.g. {"allow": "members", "labels": ["agent"]} for GitHub.
    filters: Optional[Dict[str, Any]] = None
    description: Optional[str] = Field(default=None, max_length=1024)
    timeout_seconds: int = Field(default=3600, ge=1, le=86400)
    max_retries: int = Field(default=0, ge=0, le=10)
    retry_delay_seconds: int = Field(default=60, ge=1, le=3600)

    @field_validator("name", "source_id", "target_id", "input")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()

    @field_validator("events")
    @classmethod
    def validate_events(cls, v: List[str]) -> List[str]:
        return _kinds(v, "events") or []

    @field_validator("continue_on")
    @classmethod
    def validate_continue_on(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        return _kinds(v, "continue_on")


class TriggerUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    source_id: Optional[str] = Field(default=None, max_length=255)
    events: Optional[List[str]] = Field(default=None, min_length=1)
    target_type: Optional[TargetType] = None
    target_id: Optional[str] = Field(default=None, max_length=255)
    input: Optional[str] = Field(default=None, min_length=1)
    continue_on: Optional[List[str]] = None
    filters: Optional[Dict[str, Any]] = None
    description: Optional[str] = Field(default=None, max_length=1024)
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=86400)
    max_retries: Optional[int] = Field(default=None, ge=0, le=10)
    retry_delay_seconds: Optional[int] = Field(default=None, ge=1, le=3600)

    @field_validator("name", "source_id", "target_id", "input")
    @classmethod
    def not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("must not be blank")
        return v.strip() if v is not None else v

    @field_validator("events")
    @classmethod
    def validate_events(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        return _kinds(v, "events")

    @field_validator("continue_on")
    @classmethod
    def validate_continue_on(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        return _kinds(v, "continue_on")

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "TriggerUpdate":
        """A field that every trigger has cannot be cleared; only the optional ones take null."""
        required = ("name", "source_id", "events", "target_type", "target_id", "input")
        cleared = [name for name in required if name in self.model_fields_set and getattr(self, name) is None]
        cleared += [
            name
            for name in ("timeout_seconds", "max_retries", "retry_delay_seconds")
            if name in self.model_fields_set and getattr(self, name) is None
        ]
        if cleared:
            raise ValueError(f"{', '.join(cleared)} cannot be null")
        return self


class TriggerResponse(BaseModel):
    id: str
    # ``None`` is an unowned trigger, such as one declared in code. Its runs act as the system.
    user_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    source_id: str
    events: List[str]
    continue_on: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    target_type: str
    target_id: str
    input: str
    payload: Optional[Dict[str, Any]] = None
    timeout_seconds: int
    max_retries: int
    retry_delay_seconds: int
    enabled: bool
    disabled_reason: Optional[str] = None
    # "code" for a trigger declared in code; it is changed there, not through the API.
    managed_by: Optional[str] = None
    # The AgentOS the trigger belongs to.
    os_id: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    @field_validator("continue_on", mode="before")
    @classmethod
    def no_continue_on(cls, value: Any) -> Any:
        return value or []

    @field_validator("filters", mode="before")
    @classmethod
    def no_filters(cls, value: Any) -> Any:
        return value or {}

    @field_validator("payload", mode="before")
    @classmethod
    def hide_authorization(cls, value: Any) -> Any:
        from agno.run.authorization import public_payload

        return public_payload(value)


class TriggerStateResponse(BaseModel):
    """Trimmed response for state-changing operations (enable/disable)."""

    id: str
    name: str
    enabled: bool
    disabled_reason: Optional[str] = None
    updated_at: Optional[int] = None


class TriggerSourceResponse(BaseModel):
    """A source of events declared on this AgentOS. Triggers are created on these."""

    id: str
    type: str
    # The event kinds the source commonly sends. A trigger may name any kind it sends.
    event_kinds: List[str] = Field(default_factory=list)


class TriggerEventResponse(BaseModel):
    """One delivery for one trigger: the run it started, or why it started none."""

    id: str
    source_id: str
    delivery_id: str
    # None when the event matched no trigger.
    trigger_id: Optional[str] = None
    kind: str
    event_key: Optional[str] = None
    status: str
    reason: Optional[str] = None
    # The event as its source describes it, without the raw payload.
    event: Optional[Dict[str, Any]] = None
    attempt: int = 0
    user_id: Optional[str] = None
    completed_at: Optional[int] = None
    status_code: Optional[int] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    requirements: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[int] = None

    @field_validator("trigger_id", mode="before")
    @classmethod
    def no_trigger(cls, value: Any) -> Any:
        return value or None

    @field_validator("event", mode="before")
    @classmethod
    def without_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {key: item for key, item in value.items() if key != "payload"}
