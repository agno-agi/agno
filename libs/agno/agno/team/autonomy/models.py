from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Mapping, Optional


class TeamExecutionMode(str, Enum):
    COORDINATE = "coordinate"
    BROADCAST = "broadcast"
    AUTONOMOUS = "autonomous"
    SUPERVISED = "supervised"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


class JobPhase(str, Enum):
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    SYNTHESIZE = "synthesize"
    DONE = "done"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Step:
    step_id: str
    title: str
    instructions: str
    status: StepStatus = StepStatus.PENDING
    attempt: int = 0
    max_attempts: int = 1
    assigned_to: Optional[str] = None
    run_id: Optional[str] = None
    result_summary: Optional[str] = None
    artifact_refs: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, StepStatus) else self.status
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Step":
        return cls(
            step_id=str(data.get("step_id", "")),
            title=str(data.get("title", "")),
            instructions=str(data.get("instructions", "")),
            status=StepStatus(str(data.get("status", StepStatus.PENDING.value))),
            attempt=int(data.get("attempt", 0) or 0),
            max_attempts=int(data.get("max_attempts", 1) or 1),
            assigned_to=data.get("assigned_to"),
            run_id=data.get("run_id"),
            result_summary=data.get("result_summary"),
            artifact_refs=data.get("artifact_refs"),
        )


@dataclass
class JobSnapshot:
    job_id: str
    team_id: str
    session_id: str
    user_id: Optional[str]
    goal: str

    mode: TeamExecutionMode = TeamExecutionMode.AUTONOMOUS
    status: JobStatus = JobStatus.PENDING
    phase: JobPhase = JobPhase.PLAN

    pause: Optional[Dict[str, Any]] = None

    steps: List[Step] = field(default_factory=list)
    cursor: int = 0

    budgets: Optional[Dict[str, Any]] = None
    context_digest: Optional[Dict[str, Any]] = None

    checkpoint_seq: int = 0
    created_at: int = field(default_factory=lambda: int(time()))
    updated_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode.value if isinstance(self.mode, TeamExecutionMode) else self.mode
        d["status"] = self.status.value if isinstance(self.status, JobStatus) else self.status
        d["phase"] = self.phase.value if isinstance(self.phase, JobPhase) else self.phase
        d["steps"] = [s.to_dict() if isinstance(s, Step) else s for s in self.steps]
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "JobSnapshot":
        steps_raw = data.get("steps") or []
        steps = [Step.from_dict(s) if isinstance(s, Mapping) else s for s in steps_raw]

        return cls(
            job_id=str(data.get("job_id", "")),
            team_id=str(data.get("team_id", "")),
            session_id=str(data.get("session_id", "")),
            user_id=data.get("user_id"),
            goal=str(data.get("goal", "")),
            mode=TeamExecutionMode(str(data.get("mode", TeamExecutionMode.AUTONOMOUS.value))),
            status=JobStatus(str(data.get("status", JobStatus.PENDING.value))),
            phase=JobPhase(str(data.get("phase", JobPhase.PLAN.value))),
            pause=data.get("pause"),
            steps=steps,  # type: ignore[arg-type]
            cursor=int(data.get("cursor", 0) or 0),
            budgets=data.get("budgets"),
            context_digest=data.get("context_digest"),
            checkpoint_seq=int(data.get("checkpoint_seq", 0) or 0),
            created_at=int(data.get("created_at", int(time()))),
            updated_at=data.get("updated_at"),
        )

