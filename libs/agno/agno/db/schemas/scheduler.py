"""Schemas and shared constants for the scheduler.

The constants live here rather than in ``agno.os`` because ``agno[scheduler]`` does not depend on fastapi.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agno.utils.dttm import now_epoch_s, to_epoch_s

# Header the executor stamps with the schedule's owner, so routes scope the call to the owner
# instead of the caller. Only honoured once the internal service token has authenticated the caller.
SCHEDULE_OWNER_HEADER: str = "X-Schedule-Owner"

# The user_id the internal scheduler token authenticates as. Reserved: a JWT may never claim it
# (see ``is_reserved_principal``) and it may not own a schedule.
INTERNAL_SCHEDULER_USER_ID: str = "__scheduler__"

# Matches a run endpoint and captures resource type + ID. ``\Z`` rather than ``$`` so a trailing
# newline can't slip past the run-endpoint check.
RUN_ENDPOINT_RE = re.compile(r"^/(agents|teams|workflows)/([^/]+)/runs/?\Z")


def build_run_endpoint(target_type: str, target_id: str) -> str:
    """Build the canonical run endpoint for a component.

    The single builder for every surface that constructs or compares a run
    endpoint, so builder and parser cannot drift: ``RUN_ENDPOINT_RE`` accepts an
    optional trailing slash, and a hand-built ``f"/{type}s/{id}/runs"`` compared
    with ``==`` silently misses those rows. Callers matching a stored endpoint
    must normalise it the same way - see ``match_run_endpoint``.
    """
    return f"/{target_type}s/{target_id}/runs"


def match_run_endpoint(endpoint: str, target_type: str, target_id: str) -> bool:
    """True when ``endpoint`` addresses that component's run route.

    Tolerates the trailing slash ``RUN_ENDPOINT_RE`` accepts, so a schedule
    stored as ``/agents/x/runs/`` is still recognised as targeting agent ``x``.
    """
    return endpoint.rstrip("/") == build_run_endpoint(target_type, target_id)


# Marker for builder-managed schedules; generic surfaces may filter on it.
STUDIO_SCHEDULE_MANAGED_BY = "studio"

# Run-metadata key recording which component version a run was started with.
# Written by the run-start routes when the caller pins a version explicitly
# (draft preview); read back by the lifecycle routes so a paused/completed run
# continues on the SAME version instead of whatever is current by then.
COMPONENT_VERSION_METADATA_KEY = "agno_component_version"

# Run-metadata keys recording the dispatch lineage a run belongs to: every
# component already running in this dispatch tree, oldest first, each entry
# "<type>:<id>" (membership is the cycle test), and the number of runner
# dispatches that produced it (the depth test). Two keys, because the lineage
# carries callers as well as targets, so its length is NOT the hop count.
# Written by StudioRunnerTools/StudioTools on dispatch, read back by the nested
# run's own runner tools. Runtime-owned: a caller or a stored config may never
# supply either.
DISPATCH_CHAIN_METADATA_KEY = "agno_dispatch_chain"
DISPATCH_DEPTH_METADATA_KEY = "agno_dispatch_depth"

# Every run-metadata key the runtime owns. Component metadata is merged OVER
# call-site metadata, so a stored config carrying one of these would overwrite
# the value the runtime just wrote: a forged version stamp would continue a
# paused run on the wrong version, and a forged (or emptied) dispatch lineage
# would reset the cycle guard on every hop and re-open unbounded self-dispatch.
RESERVED_RUN_METADATA_KEYS = frozenset(
    {COMPONENT_VERSION_METADATA_KEY, DISPATCH_CHAIN_METADATA_KEY, DISPATCH_DEPTH_METADATA_KEY}
)


def strip_reserved_run_metadata(metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A component's stored metadata without the keys the runtime owns.

    Configs are user-supplied and round-trip through the catalog, so the
    reserved keys are stripped where they enter the object rather than trusted
    not to be there (see ``RESERVED_RUN_METADATA_KEYS`` for what each forgery
    would do).
    """
    if not isinstance(metadata, dict) or not RESERVED_RUN_METADATA_KEYS.intersection(metadata):
        return metadata
    cleaned = {key: value for key, value in metadata.items() if key not in RESERVED_RUN_METADATA_KEYS}
    return cleaned or None


def restore_reserved_run_metadata(
    metadata: Optional[Dict[str, Any]], stored_run_metadata: Any
) -> Optional[Dict[str, Any]]:
    """Caller metadata for a resume, with the paused run's reserved keys restored.

    The runtime-owned keys describe the run being resumed -- its dispatch
    lineage, hop count and version pin -- and are persisted on the paused run
    row. A resume that rebuilt them from caller input would present a nested
    run as top-level, resetting the dispatch guard one approval at a time, so
    the stored values win and caller-supplied reserved keys are dropped the
    way every other seam drops them."""
    stored = stored_run_metadata if isinstance(stored_run_metadata, dict) else {}
    restored = {key: stored[key] for key in RESERVED_RUN_METADATA_KEYS if key in stored}
    cleaned = strip_reserved_run_metadata(metadata)
    base = dict(cleaned) if isinstance(cleaned, dict) else {}
    base.update(restored)
    return base or None


# The columns a generic update_schedule may write. Everything else - ownership,
# provenance, trigger and lock state - moves only through dedicated primitives,
# so a name-keyed upsert can never repoint who a schedule belongs to or which
# runs wrote it. user_id stays a WHERE filter in the adapters, never a SET
# column, which is why it is not in this set.
SCHEDULE_MUTABLE_COLUMNS = frozenset(
    {
        "name",
        "description",
        "method",
        "endpoint",
        "payload",
        "cron_expr",
        "timezone",
        "timeout_seconds",
        "max_retries",
        "retry_delay_seconds",
        "enabled",
        "next_run_at",
        "disabled_reason",
    }
)


def validate_schedule_update(kwargs: dict) -> None:
    """Refuse update_schedule writes outside the mutable column set."""
    rejected = sorted(set(kwargs) - SCHEDULE_MUTABLE_COLUMNS)
    if rejected:
        raise ValueError(
            f"update_schedule cannot modify {rejected}: only {sorted(SCHEDULE_MUTABLE_COLUMNS)} are mutable; "
            "ownership, provenance, trigger and lock state move only through their dedicated APIs"
        )


@dataclass
class Schedule:
    """Model for a scheduled job."""

    id: str
    name: str
    cron_expr: str
    endpoint: str
    description: Optional[str] = None
    method: str = "POST"
    payload: Optional[Dict[str, Any]] = None
    timezone: str = "UTC"
    timeout_seconds: int = 3600
    max_retries: int = 0
    retry_delay_seconds: int = 60
    enabled: bool = True
    next_run_at: Optional[int] = None
    locked_by: Optional[str] = None
    locked_at: Optional[int] = None
    # Owner of this schedule, from the JWT sub when ``user_isolation`` is on. ``None`` for
    # system-created ones. Routes scope on this column; the executor poller fires across all users.
    user_id: Optional[str] = None
    # Which control plane manages this row: "studio" for builder-created
    # schedules, None for generic/code-registered ones. Provenance columns
    # record the exact component target and the runs that wrote the row, so
    # an operator can always answer "who scheduled this, at what".
    managed_by: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    created_by_run_id: Optional[str] = None
    created_by_session_id: Optional[str] = None
    updated_by_run_id: Optional[str] = None
    updated_by_session_id: Optional[str] = None
    # Why the schedule is disabled, when the system did it (for example
    # "target_archived:agent:analyst-v2-5"). Cleared by enable.
    disabled_reason: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    def __post_init__(self) -> None:
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.updated_at is not None:
            self.updated_at = to_epoch_s(self.updated_at)
        if self.next_run_at is not None:
            self.next_run_at = int(self.next_run_at)
        if self.locked_at is not None:
            self.locked_at = int(self.locked_at)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict. Preserves None values (important for DB updates)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "method": self.method,
            "endpoint": self.endpoint,
            "payload": self.payload,
            "cron_expr": self.cron_expr,
            "timezone": self.timezone,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "enabled": self.enabled,
            "next_run_at": self.next_run_at,
            "locked_by": self.locked_by,
            "locked_at": self.locked_at,
            "user_id": self.user_id,
            "managed_by": self.managed_by,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "created_by_run_id": self.created_by_run_id,
            "created_by_session_id": self.created_by_session_id,
            "updated_by_run_id": self.updated_by_run_id,
            "updated_by_session_id": self.updated_by_session_id,
            "disabled_reason": self.disabled_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Schedule":
        data = dict(data)
        valid_keys = {
            "id",
            "name",
            "description",
            "method",
            "endpoint",
            "payload",
            "cron_expr",
            "timezone",
            "timeout_seconds",
            "max_retries",
            "retry_delay_seconds",
            "enabled",
            "next_run_at",
            "locked_by",
            "locked_at",
            "user_id",
            "managed_by",
            "target_type",
            "target_id",
            "created_by_run_id",
            "created_by_session_id",
            "updated_by_run_id",
            "updated_by_session_id",
            "disabled_reason",
            "created_at",
            "updated_at",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class ScheduleRun:
    """Model for a single execution attempt of a schedule."""

    id: str
    schedule_id: str
    attempt: int = 1
    triggered_at: Optional[int] = None
    completed_at: Optional[int] = None
    status: str = "running"  # running | success | failed | paused | timeout
    status_code: Optional[int] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    requirements: Optional[List[Dict[str, Any]]] = None
    # Denormalised from the parent ``Schedule.user_id`` so the runs router can scope by owner
    # without a JOIN. Populated by the executor when it creates the run.
    user_id: Optional[str] = None
    created_at: Optional[int] = None

    def __post_init__(self) -> None:
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.triggered_at is not None:
            self.triggered_at = int(self.triggered_at)
        if self.completed_at is not None:
            self.completed_at = int(self.completed_at)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict. Preserves None values."""
        return {
            "id": self.id,
            "schedule_id": self.schedule_id,
            "attempt": self.attempt,
            "triggered_at": self.triggered_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "status_code": self.status_code,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "error": self.error,
            "input": self.input,
            "output": self.output,
            "requirements": self.requirements,
            "user_id": self.user_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduleRun":
        data = dict(data)
        valid_keys = {
            "id",
            "schedule_id",
            "attempt",
            "triggered_at",
            "completed_at",
            "status",
            "status_code",
            "run_id",
            "session_id",
            "error",
            "input",
            "output",
            "requirements",
            "user_id",
            "created_at",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)
