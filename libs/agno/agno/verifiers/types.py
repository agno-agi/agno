"""Core types for agno.verifiers: Verdict, the loop config, and the verification record."""

import json
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

if TYPE_CHECKING:
    from agno.verifiers.fingerprints import StateFingerprint

# Hard cap on any single report, inclusive of the elision marker.
REPORT_CAP_BYTES = 6144

# Sits between the kept head and the kept tail of a truncated report. 16 bytes of UTF-8.
ELISION = " …[truncated] "

StopReason = Literal["passed", "exhausted", "timeout", "noop", "fatal"]


def _json_safe(value: Any) -> Any:
    """Coerce verifier-supplied data into something every JSON serialiser accepts. The record
    is persisted with the run row; one Path or set in a verdict must not drop the row."""
    if value is None:
        return None
    try:
        # allow_nan=False: NaN/Infinity survive Python's json round-trip but are invalid
        # JSON, so a downstream store would reject the whole run row.
        return json.loads(json.dumps(value, default=str, allow_nan=False))
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
    never rendered to the model. `required` and `skipped` are stamped by the loop from the
    check's policy: an advisory (required=False) failure is reported but never gates the
    outcome, and a skipped check (its run_when said no) is recorded without running.
    """

    passed: bool
    report: str = ""
    name: str = ""
    data: Optional[Dict[str, Any]] = None
    required: bool = True
    skipped: bool = False

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

    @property
    def gates(self) -> bool:
        """Whether this verdict counts toward the outcome: required and actually run."""
        return self.required and not self.skipped

    def named(self, name: str) -> "Verdict":
        """A copy carrying `name` when this verdict has none. Never mutates in place: a
        verifier may return the same Verdict instance on every attempt."""
        if self.name:
            return self
        return replace(self, name=name)

    def stamped(self, required: bool) -> "Verdict":
        """A copy carrying the check's policy. Never mutates in place."""
        if self.required == required:
            return self
        return replace(self, required=required)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "report": self.report,
            "data": _json_safe(self.data),
            "required": self.required,
            "skipped": self.skipped,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Verdict":
        return cls(
            passed=data.get("passed", False),
            report=data.get("report", ""),
            name=data.get("name", ""),
            data=data.get("data"),
            required=data.get("required", True),
            skipped=data.get("skipped", False),
        )


@dataclass
class VerificationConfig:
    """Shared-loop budget and options for `Agent(verifiers=...)` / `Team(verifiers=...)`.

    Holds only what is shared by all verifiers on the agent: one model re-entry serves every
    verifier, so the attempt budget and the wall clock are properties of the loop, not of any
    one check. Per-check configuration (a shell command's timeout, a scorer's threshold)
    lives on the verifier instance itself.

    `max_attempts` counts model attempts in total, the first included. `timeout_s` is a wall
    clock measured from the first model call and checked only between attempts: a running
    model call or verifier is never interrupted, so the run may overshoot by one attempt plus
    one verifier pass. `stop_on_noop` requires `fingerprint` and ends a FAILED attempt whose
    world state is unchanged as unverified — an agent that "completes" without changing the
    world is the commonest lie. `add_notice` appends the verification paragraph to the
    system message so the model knows completion is checked before its first attempt.
    """

    max_attempts: int = 3
    timeout_s: Optional[float] = None
    stop_on_noop: bool = False
    fingerprint: Optional["StateFingerprint"] = None
    add_notice: bool = True

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("VerificationConfig.max_attempts must be at least 1")
        if self.stop_on_noop and self.fingerprint is None:
            raise ValueError("VerificationConfig(stop_on_noop=True) requires a fingerprint")
        if self.fingerprint is not None:
            # Coerce here so a capture-only fingerprint object gets its async twin derived;
            # uncoerced, the async legs fail the capture and noop detection is silently inert.
            from agno.verifiers.fingerprints import coerce_fingerprint

            self.fingerprint = coerce_fingerprint(self.fingerprint)


@dataclass
class VerificationAttempt:
    """One model attempt inside one verified run.

    `verdicts` is empty only when the run left the loop before this attempt's verifiers ran
    (paused, error, cancelled). `fingerprint` is captured after the attempt's model stopped
    and before its verifiers ran: it is the state the verifiers judged. `compared_against` is
    the baseline `noop` was decided against — the run's baseline for the first attempt, and
    for later attempts a capture SETTLED after the previous attempt's verifiers ran, so a
    verifier's own artefacts (a `.pytest_cache`, a formatter pass) are never charged to the
    model as work. None never compares equal to anything, so `noop` is False whenever either
    side is unknown. `message_index` is the index in `RunOutput.messages` of the first
    message of this attempt; slice `messages[a.message_index : next_a.message_index]` for one
    attempt's transcript.
    """

    index: int
    verdicts: List[Verdict] = field(default_factory=list)
    fingerprint: Optional[str] = None
    compared_against: Optional[str] = None
    noop: bool = False
    message_index: int = 0

    @property
    def passed(self) -> bool:
        """Every required, non-skipped check passed. Advisory failures and skipped checks
        never gate; an attempt whose checks are all advisory passes with warnings on record."""
        return bool(self.verdicts) and all(v.passed is True for v in self.verdicts if v.gates)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "fingerprint": self.fingerprint,
            "compared_against": self.compared_against,
            "noop": self.noop,
            "message_index": self.message_index,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationAttempt":
        return cls(
            index=data.get("index", 0),
            verdicts=[Verdict.from_dict(v) for v in data.get("verdicts") or []],
            fingerprint=data.get("fingerprint"),
            compared_against=data.get("compared_against"),
            noop=data.get("noop", False),
            message_index=data.get("message_index", 0),
        )


@dataclass
class Verification:
    """The verification record of one run, carried on `RunOutput.verification`.

    `status` is "pending" while the loop is open (and on a run that left it paused, errored
    or cancelled before concluding); a concluded record is "verified" or "unverified". The
    record describes the run's LAST GATED attempt window, not a mirror of RunStatus: a later
    continuation by an owner without verifiers can complete the run while the record still
    reads "unverified" - genuine audit history, healed by the next gated continuation.
    `stop_reason` is "passed" iff verified. `budget_baseline` is the number of attempts made
    before the current continuation window: continuing a run that ended unverified restarts
    the attempt budget for the new user instruction while keeping the full attempt history,
    so the budget check is `len(attempts) - budget_baseline >= max_attempts`.
    """

    status: Literal["pending", "verified", "unverified"] = "pending"
    stop_reason: Optional[StopReason] = None
    attempts: List[VerificationAttempt] = field(default_factory=list)
    baseline_fingerprint: Optional[str] = None
    budget_baseline: int = 0

    @property
    def passed(self) -> bool:
        return self.status == "verified"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "stop_reason": self.stop_reason,
            "attempts": [a.to_dict() for a in self.attempts],
            "baseline_fingerprint": self.baseline_fingerprint,
            "budget_baseline": self.budget_baseline,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Verification":
        return cls(
            status=data.get("status", "pending"),
            stop_reason=data.get("stop_reason"),
            attempts=[VerificationAttempt.from_dict(a) for a in data.get("attempts") or []],
            baseline_fingerprint=data.get("baseline_fingerprint"),
            budget_baseline=data.get("budget_baseline", 0),
        )
