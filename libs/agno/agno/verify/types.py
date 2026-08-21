"""Core types for agno.verify: Verdict, the attempt and verification records, limits, constants."""

import json
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Literal, Optional

# Hard cap on any single report, inclusive of the elision marker.
REPORT_CAP_BYTES = 6144

# Sits between the kept head and the kept tail of a truncated report. 16 bytes of UTF-8.
ELISION = " …[truncated] "

# Callers add this to Agent(instructions=[...]). The runner never injects it: it does not
# touch the agent, so the model learns about verification on its first continuation unless
# the caller tells it earlier.
VERIFICATION_NOTICE = (
    "Completion is checked by the host. When you believe the task is done, end your turn; checks run "
    "automatically. Do not assert success: if a check fails you will be told, with its output, and you continue "
    "working."
)

StopReason = Literal["passed", "exhausted", "timeout", "noop", "paused", "error", "cancelled"]


def _json_safe(value: Any) -> Any:
    """Coerce verifier-supplied data into something every JSON serialiser accepts. The record
    is stamped into a run row; one Path or set in a verdict must not drop the row."""
    if value is None:
        return None
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return None


def encodable(text: str) -> str:
    """`text` with any lone surrogate rendered as its escape.

    Surrogates reach a report through anything that decoded bytes with `errors="surrogateescape"`
    — a filename that is not valid UTF-8 is the common route. They cannot be UTF-8 encoded, so
    left alone they raise inside the cap and take the whole run down; and even capped they would
    fail again in the model client. Rendering them keeps the evidence readable and the run alive.
    """
    try:
        text.encode("utf-8")
        return text
    except UnicodeEncodeError:
        return text.encode("utf-8", errors="backslashreplace").decode("utf-8")


def cap_text(text: str, cap: int = REPORT_CAP_BYTES) -> str:
    """Truncate `text` to at most `cap` bytes of UTF-8, keeping the head and the tail.

    The head gets one third of the budget and the tail two thirds: test runners and compilers
    put the summary at the end and the first error at the top. The elision marker counts
    against the cap. Multi-byte characters split by the cut are dropped, never corrupted.
    """
    text = encodable(text)
    raw = text.encode("utf-8")
    if len(raw) <= cap:
        return text
    marker = ELISION.encode("utf-8")
    if cap < len(marker):
        # A cap too small for the marker degrades to a plain head cut; never exceed it.
        return raw[: max(cap, 0)].decode("utf-8", errors="ignore")
    budget = cap - len(marker)
    head_bytes = budget // 3
    tail_bytes = budget - head_bytes
    head = raw[:head_bytes].decode("utf-8", errors="ignore")
    tail = raw[len(raw) - tail_bytes :].decode("utf-8", errors="ignore") if tail_bytes else ""
    return head + ELISION + tail


@dataclass
class Verdict:
    """One verifier's decision about one attempt.

    `report` is what the model sees on failure; it is capped to REPORT_CAP_BYTES in
    `__post_init__` so no caller can exceed it. `data` is for programmatic consumers and is
    never rendered to the model.
    """

    passed: bool
    report: str = ""
    name: str = ""
    data: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            self.name = "" if self.name is None else str(self.name)
        if not isinstance(self.report, str):
            self.report = str(self.report)
        if not isinstance(self.passed, bool):
            # Only a real bool decides a run. bool("false") is True; len(failures) is truthy;
            # an exit code is truthy on failure. None of those may verify a run.
            note = (
                f"verifier set Verdict.passed to {type(self.passed).__name__} ({self.passed!r}); "
                "only a real bool decides a run, treating it as a failure"
            )
            self.report = f"{note}\n{self.report}" if self.report else note
            self.passed = False
        self.report = cap_text(self.report)

    def named(self, name: str) -> "Verdict":
        """A copy carrying `name` when this verdict has none. Never mutates in place: a
        verifier may return the same Verdict instance on every attempt."""
        if self.name:
            return self
        return replace(self, name=name)


@dataclass
class VerifierLimits:
    """When the runner stops continuing.

    `max_continuations` counts continuations after the first attempt, so the total number of
    attempts is one more. `timeout_s` is a wall clock started before the first attempt and
    checked only between attempts: a running attempt or verifier is never interrupted, so the
    run may overshoot by one attempt. `stop_on_noop` requires a fingerprint and ends the run
    as unverified when a failed attempt changed nothing.
    """

    max_continuations: int = 3
    timeout_s: Optional[float] = None
    stop_on_noop: bool = False


@dataclass
class VerificationAttempt:
    """One attempt inside one verified run: the first run or one continuation.

    Not the same unit as `agno.environments.AttemptResult`, which is one whole run of a task.
    `run_id` is this attempt's RunOutput.run_id; each continuation is a forked sibling run
    with its own id. The fork carries the lineage with it, so the RunOutput a verifier is
    handed on attempt N lists the tool calls of every earlier attempt as well as its own: a
    check written as "did it call deploy()?" answers for the verified run as a whole, not for
    the last attempt. Scope such a check to the world it changed, not to the call list. `fingerprint` is captured after the attempt's run and before its
    verifiers; None means no fingerprint was configured or the capture failed, and None
    never compares equal to anything, so `noop` is False whenever either side is unknown.
    """

    index: int
    run_id: Optional[str]
    status: str
    verdicts: List[Verdict] = field(default_factory=list)
    fingerprint: Optional[str] = None
    noop: bool = False
    metrics: Optional[Any] = None

    @property
    def passed(self) -> bool:
        return bool(self.verdicts) and all(v.passed is True for v in self.verdicts)

    def to_dict(self) -> Dict[str, Any]:
        metrics = self.metrics
        if metrics is not None and hasattr(metrics, "to_dict"):
            metrics = metrics.to_dict()
        return {
            "index": self.index,
            "run_id": self.run_id,
            "status": self.status,
            "verdicts": [
                {"name": v.name, "passed": v.passed, "report": v.report, "data": _json_safe(v.data)}
                for v in self.verdicts
            ],
            "fingerprint": self.fingerprint,
            "noop": self.noop,
            "metrics": metrics,
        }


@dataclass
class Verification:
    """The record of a verified run.

    `status` is "pending" only in the snapshot stamped on a RunOutput mid-loop; a returned
    record is "verified" or "unverified". The shape is designed so a run-loop integration can
    attach it to a RunOutput unchanged.
    """

    status: Literal["pending", "verified", "unverified"]
    stop_reason: Optional[StopReason]
    attempts: List[VerificationAttempt] = field(default_factory=list)
    baseline_fingerprint: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.status == "verified"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "stop_reason": self.stop_reason,
            "attempts": [a.to_dict() for a in self.attempts],
            "baseline_fingerprint": self.baseline_fingerprint,
        }


@dataclass
class VerifiedRun:
    """What `run_verified` returns: the final attempt's RunOutput and the verification record.

    `output.status` is RunStatus.completed even when `verification.status` is "unverified".
    Read `VerifiedRun.status`, not `output.status`. The returned VerifiedRun is the only place
    the final verdict exists; persisted run rows carry at most an in-progress snapshot in
    `metadata["verification"]`. `output` is the final attempt's run, which for a continued run
    is a forked sibling of the first attempt with its own run_id; `output.metrics` covers that
    attempt only, so sum `attempts[*].metrics` for the cost of the whole run.
    """

    output: Any
    verification: Verification

    @property
    def status(self) -> Literal["verified", "unverified"]:
        return "verified" if self.verification.status == "verified" else "unverified"

    @property
    def passed(self) -> bool:
        return self.verification.passed

    @property
    def stop_reason(self) -> StopReason:
        return self.verification.stop_reason or "exhausted"

    @property
    def attempts(self) -> List[VerificationAttempt]:
        return self.verification.attempts
