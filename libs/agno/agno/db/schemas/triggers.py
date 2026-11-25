"""Schemas and shared constants for triggers.

A trigger starts a run of an agent, team or workflow when an event arrives from a source.
An event row records one delivery for one trigger and the run it started.
"""

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.utils.dttm import now_epoch_s, to_epoch_s

# The event is stored and waits for a worker.
EVENT_PENDING = "pending"
# A worker holds the event and is starting or following its run.
EVENT_RUNNING = "running"
EVENT_SUCCESS = "success"
EVENT_FAILED = "failed"
EVENT_PAUSED = "paused"
EVENT_CANCELLED = "cancelled"
# The trigger's prepare step declined the event, or the trigger was disabled before it ran.
EVENT_SKIPPED = "skipped"
# The event matched no trigger or failed a trigger's filter. It starts nothing.
EVENT_IGNORED = "ignored"

# An event in one of these states still has work to do.
UNFINISHED_EVENT_STATUSES = (EVENT_PENDING, EVENT_RUNNING)

# A trigger has handled a key once an event for it was accepted, whatever its run did afterwards.
HANDLED_EVENT_STATUSES = (
    EVENT_PENDING,
    EVENT_RUNNING,
    EVENT_SUCCESS,
    EVENT_FAILED,
    EVENT_PAUSED,
    EVENT_CANCELLED,
)

# An event that matched no trigger is stored under this trigger id, so a redelivery finds the same row.
NO_TRIGGER_ID = ""

# managed_by of a trigger declared in code.
CODE_MANAGED = "code"

# disabled_reason of a trigger or schedule that code declared and no longer declares.
NOT_DECLARED_REASON = "not_declared"

# os_id of the triggers declared by an AgentOS that was given neither an id nor a name. Such an
# AgentOS gets a new random id every time it starts, so that id cannot say which rows are its own.
UNNAMED_OS_ID = "__unnamed__"

# The columns update_trigger may write. The id, the owner and the creating run never change.
TRIGGER_MUTABLE_COLUMNS = frozenset(
    {
        "name",
        "description",
        "source_id",
        "events",
        "continue_on",
        "filters",
        "target_type",
        "target_id",
        "input",
        "key_path",
        "payload",
        "timeout_seconds",
        "max_retries",
        "retry_delay_seconds",
        "enabled",
        "disabled_reason",
        "managed_by",
        "os_id",
        "updated_by_run_id",
        "updated_by_session_id",
    }
)


def validate_trigger_update(kwargs: Dict[str, Any]) -> None:
    """Refuse update_trigger writes outside the mutable column set."""
    rejected = sorted(set(kwargs) - TRIGGER_MUTABLE_COLUMNS)
    if rejected:
        raise ValueError(f"update_trigger cannot modify {rejected}: only {sorted(TRIGGER_MUTABLE_COLUMNS)} are mutable")


_last_timestamp = 0
_lock = Lock()


def new_trigger_event_id(after: Optional[str] = None) -> str:
    """An id that sorts in the order events were received.

    Events for one key run in id order. The nanosecond prefix orders them across workers, and the
    local counter keeps two events received in the same reading apart.

    Args:
        after: The id of the newest event already stored for the same conversation. The new id
            sorts after it even when this process's clock is behind the one that stored it.
    """
    global _last_timestamp
    earliest = 0
    if after:
        try:
            earliest = int(after.split("_")[1]) + 1
        except (IndexError, ValueError):
            earliest = 0
    with _lock:
        _last_timestamp = max(time.time_ns(), _last_timestamp + 1, earliest)
        timestamp = _last_timestamp
    return f"te_{timestamp:020d}_{uuid4()}"


@dataclass
class StoredTrigger:
    """A trigger as stored: which events from which source start a run of which target."""

    id: str
    name: str
    source_id: str
    target_type: str
    target_id: str
    input: str
    events: List[str] = field(default_factory=list)
    # Event kinds that fire only when this trigger already handled the same key.
    continue_on: List[str] = field(default_factory=list)
    # Source-specific and declarative, e.g. labels and who may start a run for GitHub.
    filters: Dict[str, Any] = field(default_factory=dict)
    # Where a source that takes any payload reads the conversation key. Sources that set the key
    # themselves, such as GitHub, leave it empty.
    key_path: Optional[str] = None
    description: Optional[str] = None
    # Extra run parameters, and the saved authority of the person or agent that created the trigger.
    payload: Optional[Dict[str, Any]] = None
    timeout_seconds: int = 3600
    max_retries: int = 0
    retry_delay_seconds: int = 60
    enabled: bool = True
    disabled_reason: Optional[str] = None
    # Owner. None for a trigger declared in code, which fires as the system.
    user_id: Optional[str] = None
    # "code" for a trigger declared in code, None for one created as data.
    managed_by: Optional[str] = None
    # The AgentOS the trigger belongs to: only that one matches deliveries against it and runs its
    # events. None for a trigger that is not tied to one AgentOS; any AgentOS with its source takes it.
    os_id: Optional[str] = None
    created_by_run_id: Optional[str] = None
    created_by_session_id: Optional[str] = None
    updated_by_run_id: Optional[str] = None
    updated_by_session_id: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    def __post_init__(self) -> None:
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.updated_at is not None:
            self.updated_at = to_epoch_s(self.updated_at)
        self.events = list(self.events or [])
        self.continue_on = list(self.continue_on or [])
        self.filters = dict(self.filters or {})

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict. Preserves None values (important for DB updates)."""
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoredTrigger":
        return cls(**{key: value for key, value in data.items() if key in cls.__dataclass_fields__})


@dataclass
class TriggerEvent:
    """One delivery for one trigger, and the run it started."""

    id: str
    source_id: str
    delivery_id: str
    kind: str
    # The trigger the event matched. Empty when it matched none.
    trigger_id: str = NO_TRIGGER_ID
    # What groups events into one conversation, e.g. "owner/name#12". None means the event stands alone.
    event_key: Optional[str] = None
    status: str = EVENT_PENDING
    # Why the event was ignored or skipped, or what a step after the run reported.
    reason: Optional[str] = None
    # The event as its source stores it.
    event: Optional[Dict[str, Any]] = None
    attempt: int = 0
    # The claim of the worker handling the event, and when that worker last renewed it.
    claimed_by: Optional[str] = None
    claimed_at: Optional[int] = None
    completed_at: Optional[int] = None
    status_code: Optional[int] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    requirements: Optional[List[Dict[str, Any]]] = None
    # Denormalised from the trigger's owner, so event reads scope by owner without a join.
    user_id: Optional[str] = None
    created_at: Optional[int] = None

    def __post_init__(self) -> None:
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.claimed_at is not None:
            self.claimed_at = int(self.claimed_at)
        if self.completed_at is not None:
            self.completed_at = int(self.completed_at)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict. Preserves None values."""
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TriggerEvent":
        return cls(**{key: value for key, value in data.items() if key in cls.__dataclass_fields__})
