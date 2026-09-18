"""Pydantic request/response models for the monitor API."""

import re
import unicodedata
from typing import Annotated, Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agno.db.schemas.monitor import (
    validate_event_budget,
    validate_run_watch_is_bounded,
    validate_watch_target,
)

_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9 ._-]*$")

# How many paths one monitor may watch, and how many extra patterns it may
# exclude. Both are capped because both are turned into real work by the worker
# that claims the row: every path becomes an OS watch held for the monitor's
# whole life, and every pattern is matched against every change those watches
# report. An uncapped list is that much work bought with one request, by a
# caller who only needs monitors:write.
MAX_WATCH_PATHS = 32
MAX_EXCLUDE_PATTERNS = 64

# One entry of either list. Declared once so the per-entry ceiling is the same
# whether the caller sent a single path or several -- a list must not be a way
# past the length a lone string is held to.
_WatchPath = Annotated[str, Field(max_length=1024)]
_ExcludePattern = Annotated[str, Field(max_length=255)]


class MonitorCreate(BaseModel):
    name: str = Field(..., max_length=255)
    # A subpath of the deployment's monitor root, or several of them, the same
    # contract FileTools takes: relative in, resolved and containment-checked by
    # the route, absolute on the row. Several paths are still ONE watch -- the
    # watcher takes them together -- so the row keeps one status, one exit code
    # and one event count. The check cannot live on this model because the root
    # is a property of the deployment, not of the request body.
    watch_path: Optional[Union[_WatchPath, Annotated[List[_WatchPath], Field(max_length=MAX_WATCH_PATHS)]]] = None
    watch_command: Optional[str] = Field(default=None, max_length=255)
    watch_run_id: Optional[str] = Field(default=None, max_length=255)
    # Glob patterns dropped from a path watch, on top of whatever
    # ``use_default_filter`` leaves in place. Editable afterwards as well: a
    # watch that turns out to be too noisy is the most likely thing an owner
    # wants to change without recreating the monitor.
    exclude: Optional[Annotated[List[_ExcludePattern], Field(max_length=MAX_EXCLUDE_PATTERNS)]] = None
    # Whether the watcher's own default exclusions apply -- .git, .venv,
    # __pycache__, node_modules, compiled Python, editor swap files. Right often
    # enough to be the default and wrong often enough to be a choice: a watch
    # that looks inert is usually watching something on that list.
    use_default_filter: bool = True
    endpoint: Optional[str] = Field(default=None, max_length=512)
    method: str = Field(default="POST", max_length=10)
    description: Optional[str] = Field(default=None, max_length=1024)
    payload: Optional[Dict[str, Any]] = None
    timeout_seconds: int = Field(default=300, ge=1, le=86400)
    persistent: bool = False
    max_events: int = Field(default=100, ge=0, le=10000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _NAME_PATTERN.match(v):
            raise ValueError("Name must start with alphanumeric and contain only alphanumeric, spaces, '.', '_', '-'")
        return v

    @model_validator(mode="after")
    def validate_target(self) -> "MonitorCreate":
        validate_watch_target(self.watch_command, self.watch_run_id, self.watch_path)
        validate_run_watch_is_bounded(self.watch_run_id, self.persistent)
        # Kept here as well as in the manager so the route answers 422 rather
        # than turning the manager's ValueError into a 500.
        validate_event_budget(self.persistent, self.max_events, self.endpoint)
        return self

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
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
            # A control character makes the URL unsendable, so the monitor would fail on every event.
            if any(c.isspace() or unicodedata.category(c) == "Cc" for c in v):
                raise ValueError("Endpoint must not contain whitespace or control characters")
        return v


class MonitorUpdate(BaseModel):
    """Owner-facing edit. Only the fields present in the body are written.

    Unknown fields are kept rather than dropped so the router can name them in a
    400: a body carrying ``status`` or ``locked_by`` is a caller trying to drive
    the executor's state machine, and silently accepting it would report success
    for a write that never happened. The watch target is not editable at all --
    it picks the executor's whole code path.
    """

    model_config = ConfigDict(extra="allow")

    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=1024)
    # Declared here as well as on the create model so an edit is held to the same
    # ceilings the create was. Without the declaration ``extra="allow"`` would
    # still carry them through -- they are user-mutable columns -- but unbounded,
    # which makes PATCH the way past a cap POST enforces. Nullable because
    # clearing the extra patterns is a real edit: it leaves the watch with
    # whatever ``use_default_filter`` provides and nothing else.
    exclude: Optional[Annotated[List[_ExcludePattern], Field(max_length=MAX_EXCLUDE_PATTERNS)]] = None
    use_default_filter: Optional[bool] = None
    # Nullable on purpose: clearing the endpoint turns a delivering monitor into
    # a watch-and-read one, which needs no permission because it reaches nothing.
    endpoint: Optional[str] = Field(default=None, max_length=512)
    method: Optional[str] = Field(default=None, max_length=10)
    payload: Optional[Dict[str, Any]] = None
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=86400)
    persistent: Optional[bool] = None
    max_events: Optional[int] = Field(default=None, ge=0, le=10000)

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
            # A control character makes the URL unsendable, so the monitor would fail on every event.
            if any(c.isspace() or unicodedata.category(c) == "Cc" for c in v):
                raise ValueError("Endpoint must not contain whitespace or control characters")
        return v

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> "MonitorUpdate":
        non_nullable = ("name", "method", "timeout_seconds", "persistent", "max_events", "use_default_filter")
        data = self.model_dump(exclude_unset=True)
        for field_name in non_nullable:
            if field_name in data and data[field_name] is None:
                raise ValueError(f"'{field_name}' cannot be set to null")
        return self


class MonitorResponse(BaseModel):
    id: str
    user_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    # A list, and absolute by the time it is read back: the route resolves and
    # contains every subpath the caller sent, and de-duplicates them, before any
    # of it reaches the database. A caller that sent one string reads back a
    # one-element list, so nothing downstream has two shapes to handle.
    watch_path: Optional[List[str]] = None
    # The NAME of a declared command, never the command. The command is
    # operator-authored and can hold credentials; monitors:read is a read scope
    # held by people who are not the operator. ``description`` is the operator's
    # own publishable sentence about the same command, and is what the create
    # route copies onto the row in its place.
    watch_command: Optional[str] = None
    watch_run_id: Optional[str] = None
    exclude: Optional[List[str]] = None
    # Defaulted rather than required: a row written before this column existed
    # reads back without the key, and a reflected table carries only what the
    # DDL says, so demanding it here would 500 the read instead of the write.
    use_default_filter: bool = True
    endpoint: Optional[str] = None
    method: str
    payload: Optional[Dict[str, Any]] = None
    timeout_seconds: int
    persistent: bool
    max_events: int
    status: str
    exit_code: Optional[int] = None
    error: Optional[str] = None
    event_count: int
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class MonitorStateResponse(BaseModel):
    """Trimmed response for state-changing operations (stop/restart)."""

    id: str
    name: str
    status: str
    updated_at: Optional[int] = None


class MonitorEventResponse(BaseModel):
    id: str
    monitor_id: str
    user_id: Optional[str] = None
    seq: int
    content: str
    delivery_status: Optional[str] = None
    status_code: Optional[int] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[int] = None
