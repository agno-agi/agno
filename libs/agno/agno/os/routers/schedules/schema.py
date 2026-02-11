"""Pydantic request/response models for the schedule API."""

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9 ._-]*$")


class ScheduleCreate(BaseModel):
    name: str = Field(..., max_length=255)
    cron_expr: str = Field(..., max_length=128)
    endpoint: str = Field(..., max_length=512)
    method: str = Field(default="POST", max_length=10)
    description: Optional[str] = Field(default=None, max_length=1024)
    payload: Optional[Dict[str, Any]] = None
    timezone: str = Field(default="UTC", max_length=64)
    timeout_seconds: int = Field(default=3600, ge=1, le=86400)
    max_retries: int = Field(default=0, ge=0, le=10)
    retry_delay_seconds: int = Field(default=60, ge=1, le=3600)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _NAME_PATTERN.match(v):
            raise ValueError("Name must start with alphanumeric and contain only alphanumeric, spaces, '.', '_', '-'")
        return v

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        v = v.upper()
        if v not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            raise ValueError("Method must be GET, POST, PUT, PATCH, or DELETE")
        return v

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("Endpoint must start with '/'")
        if "://" in v:
            raise ValueError("Endpoint must be a path, not a full URL")
        return v


class ScheduleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    cron_expr: Optional[str] = Field(default=None, max_length=128)
    endpoint: Optional[str] = Field(default=None, max_length=512)
    method: Optional[str] = Field(default=None, max_length=10)
    description: Optional[str] = Field(default=None, max_length=1024)
    payload: Optional[Dict[str, Any]] = None
    timezone: Optional[str] = Field(default=None, max_length=64)
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=86400)
    max_retries: Optional[int] = Field(default=None, ge=0, le=10)
    retry_delay_seconds: Optional[int] = Field(default=None, ge=1, le=3600)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _NAME_PATTERN.match(v):
            raise ValueError("Name must start with alphanumeric and contain only alphanumeric, spaces, '.', '_', '-'")
        return v

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.upper()
            if v not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                raise ValueError("Method must be GET, POST, PUT, PATCH, or DELETE")
        return v

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.startswith("/"):
                raise ValueError("Endpoint must start with '/'")
            if "://" in v:
                raise ValueError("Endpoint must be a path, not a full URL")
        return v

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "ScheduleUpdate":
        non_nullable = (
            "name",
            "cron_expr",
            "endpoint",
            "method",
            "timezone",
            "timeout_seconds",
            "max_retries",
            "retry_delay_seconds",
        )
        data = self.model_dump(exclude_unset=True)
        for field_name in non_nullable:
            if field_name in data and data[field_name] is None:
                raise ValueError(f"'{field_name}' cannot be set to null")
        return self


class ScheduleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    method: str
    endpoint: str
    payload: Optional[Dict[str, Any]] = None
    cron_expr: str
    timezone: str
    timeout_seconds: int
    max_retries: int
    retry_delay_seconds: int
    enabled: bool
    next_run_at: Optional[int] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class ScheduleStateResponse(BaseModel):
    """Trimmed response for state-changing operations (enable/disable)."""

    id: str
    name: str
    enabled: bool
    next_run_at: Optional[int] = None
    updated_at: Optional[int] = None


class ScheduleRunResponse(BaseModel):
    id: str
    schedule_id: str
    attempt: int
    triggered_at: Optional[int] = None
    completed_at: Optional[int] = None
    status: str
    status_code: Optional[int] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    requirements: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[int] = None
