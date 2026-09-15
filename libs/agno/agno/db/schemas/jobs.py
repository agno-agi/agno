"""Schema for the durable job queue.

One row per accepted background run. The row IS the durable acceptance: once
it commits, the run will be executed (or terminally failed, visibly) by
whichever worker claims it - across process crashes and deploys.

Jobs are fully serializable (no closures) so any process can execute them.
``attempt`` doubles as a generation counter: terminal writes are fenced on
``(locked_by, attempt)`` so a zombie executor that finishes after its job was
reclaimed has its write discarded.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from agno.utils.dttm import now_epoch_s, to_epoch_s


class QueueWriteOutcome(str, Enum):
    """Why a fenced queue write did or did not land.

    A bare bool/None could not distinguish "another worker legitimately owns
    this ticket" (benign - our claim was reclaimed) from "the store could not
    settle the write" (a real fault that leaves the ticket RUNNING). The
    worker logs those very differently, and only the second one needs to be
    loud.
    """

    APPLIED = "applied"  # the mutation landed
    FENCED = "fenced"  # not the claim holder / wrong attempt / not running - someone else owns it
    MISSING = "missing"  # no such job record
    CONTENDED = "contended"  # optimistic-concurrency retries exhausted (the write did NOT land)


# Lifecycle: queued -> running -> completed | failed | cancelled | paused
# running with a stale lock is claimable again while attempt < max_attempts;
# otherwise the sweep moves it to failed without executing.
# paused: the execution leg ended awaiting HITL input. NOT terminal: a
# continue CAS-flips the SAME ticket paused -> queued (continue_job) with the
# continuation inputs merged into the payload - one row per run, ever
# (id == run_id is load-bearing across poll/resume/cancel/idempotency).
# cancel reaches paused tickets too (paused -> cancelled).
JOB_STATUSES = ("queued", "running", "completed", "failed", "cancelled", "paused")


@dataclass
class QueuedJob:
    """One accepted background run awaiting or undergoing execution."""

    id: str  # == run_id, so poll/resume endpoints key identically
    component_type: str  # "agent" | "team" | "workflow"
    component_id: str
    session_id: str
    # What kind of work this ticket carries. Runs are the only type today; the
    # column exists so other AgentOS job types (e.g. knowledge ingestion) can
    # ride the same queue without a schema migration.
    job_type: str = "run"
    # Claim affinity: workers claim only jobs whose deployment_id is None or
    # equals their QueueConfig.deployment_id. Stamped at enqueue; a
    # continuation CAS never touches it (the leg inherits the submit's home).
    deployment_id: Optional[str] = None
    user_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)  # serialized run params
    status: str = "queued"
    attempt: int = 0
    max_attempts: int = 1
    idempotency_key: Optional[str] = None  # unique when set; dedupes resubmits
    available_at: Optional[int] = None  # now, or future for retry backoff
    locked_by: Optional[str] = None
    locked_at: Optional[int] = None
    error: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None
    completed_at: Optional[int] = None

    def __post_init__(self) -> None:
        now = now_epoch_s()
        self.created_at = now if self.created_at is None else to_epoch_s(self.created_at)
        self.available_at = now if self.available_at is None else int(self.available_at)
        if self.updated_at is not None:
            self.updated_at = to_epoch_s(self.updated_at)
        if self.locked_at is not None:
            self.locked_at = int(self.locked_at)
        if self.completed_at is not None:
            self.completed_at = int(self.completed_at)
        if self.status not in JOB_STATUSES:
            raise ValueError(f"Invalid job queue status {self.status!r}; expected one of {JOB_STATUSES}")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict. Preserves None values (important for DB updates)."""
        return {
            "id": self.id,
            "component_type": self.component_type,
            "component_id": self.component_id,
            "session_id": self.session_id,
            "job_type": self.job_type,
            "deployment_id": self.deployment_id,
            "user_id": self.user_id,
            "payload": self.payload,
            "status": self.status,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "idempotency_key": self.idempotency_key,
            "available_at": self.available_at,
            "locked_by": self.locked_by,
            "locked_at": self.locked_at,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QueuedJob":
        valid_keys = {
            "id",
            "component_type",
            "component_id",
            "session_id",
            "job_type",
            "deployment_id",
            "user_id",
            "payload",
            "status",
            "attempt",
            "max_attempts",
            "idempotency_key",
            "available_at",
            "locked_by",
            "locked_at",
            "error",
            "created_at",
            "updated_at",
            "completed_at",
        }
        filtered = {k: v for k, v in dict(data).items() if k in valid_keys}
        return cls(**filtered)
