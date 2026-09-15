"""Core types for agno.verifiers: Verdict, the loop config, and the verification record."""

import json
import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agno.utils.serialize import json_serializer
from agno.verifiers.fingerprints import coerce_fingerprint

if TYPE_CHECKING:
    from agno.verifiers.fingerprints import StateFingerprint

# Hard cap on any single report, inclusive of the elision marker.
MAX_REPORT_BYTES = 6144

# Verifier names are identifiers in the report block, not evidence; the body carries detail.
MAX_NAME_BYTES = 120

# Sits between the kept head and the kept tail of a truncated report. 16 bytes of UTF-8.
ELISION = " …[truncated] "


class VerificationStatus(str, Enum):
    """Where a verification record stands"""

    pending = "pending"
    verified = "verified"
    unverified = "unverified"


class VerificationStopReason(str, Enum):
    """Why a concluded verification loop stopped"""

    passed = "passed"
    exhausted = "exhausted"
    timeout = "timeout"
    unchanged_state = "unchanged_state"
    fatal = "fatal"


def _json_safe(value: Any) -> Any:
    """Verifier-supplied data as plain JSON, or None when it cannot be. The record is persisted with
    the run row, so a NaN, a lone surrogate or a circular reference must not lose the row."""

    def scrub(item: Any) -> Any:
        if isinstance(item, str):
            return encodable(item)
        if isinstance(item, float) and not math.isfinite(item):
            return None
        if isinstance(item, dict):
            return {encodable(str(k)): scrub(v) for k, v in item.items()}
        if isinstance(item, (list, tuple, set, frozenset)):
            return [scrub(v) for v in item]
        return item

    if value is None:
        return None
    try:
        return json.loads(json.dumps(scrub(value), default=lambda o: scrub(json_serializer(o)), allow_nan=False))
    except (TypeError, ValueError, RecursionError):
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


def cap_text(text: str, cap: int = MAX_REPORT_BYTES) -> str:
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

    `report` is what the model sees on failure; it is capped to MAX_REPORT_BYTES in
    `__post_init__` so no caller can exceed it. `detail` is for programmatic consumers and is
    never rendered to the model. `required` and `skipped` are stamped by the loop from the
    check's policy: an advisory (required=False) failure is reported but never gates the
    outcome, and a skipped check (its run_condition said no) is recorded without running. A check
    cannot skip itself: the loop stamps skipped=False onto any verdict a check returned,
    because a returned skipped=True on a failure would pass the attempt vacuously.
    """

    passed: bool
    report: str = ""
    name: str = ""
    detail: Optional[Dict[str, Any]] = None
    # A failure retrying cannot fix (a harness error); the verifier sets it
    fatal: bool = False
    required: bool = True
    skipped: bool = False

    def __post_init__(self) -> None:
        self.name = cap_text(self.name, MAX_NAME_BYTES)
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

    def stamped(self, required: bool, skipped: bool) -> "Verdict":
        """A copy carrying the loop's stamp: the check's `required` policy and the loop's
        own knowledge of whether the check ran. Never mutates in place."""
        if self.required == required and self.skipped == skipped:
            return self
        return replace(self, required=required, skipped=skipped)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "report": self.report,
            "detail": _json_safe(self.detail),
            "required": self.required,
            "skipped": self.skipped,
            "fatal": self.fatal,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Verdict":
        return cls(
            passed=data.get("passed", False),
            report=data.get("report", ""),
            name=data.get("name", ""),
            detail=data.get("detail"),
            required=data.get("required", True),
            skipped=data.get("skipped", False),
            fatal=data.get("fatal", False),
        )


@dataclass
class VerificationConfig:
    """Shared-loop budget and options for ``Agent(verifiers=...)`` and ``Team(verifiers=...)``.

    One model re-entry serves every verifier, so the budget and the clock are properties of
    the loop; per-check configuration lives on the verifier. ``max_attempts`` counts model
    attempts, the first included. ``timeout`` is checked between attempts only, so a run may
    overshoot by one attempt plus one verifier pass. ``stop_on_unchanged_state`` requires ``fingerprint``
    and ends a failed attempt that changed nothing as unverified. ``add_verification_to_context`` names the
    checks in the system message, so a check named for its expected answer gives it away.
    """

    max_attempts: int = 3
    timeout: Optional[float] = None
    stop_on_unchanged_state: bool = False
    fingerprint: Optional["StateFingerprint"] = None
    add_verification_to_context: bool = True

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("VerificationConfig.max_attempts must be at least 1")
        if self.stop_on_unchanged_state and self.fingerprint is None:
            raise ValueError("VerificationConfig(stop_on_unchanged_state=True) requires a fingerprint")
        if self.fingerprint is not None:
            self.fingerprint = coerce_fingerprint(self.fingerprint)


@dataclass
class VerificationAttempt:
    """One model attempt inside one verified run.

    ``verdicts`` is empty only when the run left the loop before the checks ran (paused, error,
    cancelled). ``fingerprint`` is captured after the model stopped and before the checks ran;
    ``compared_against`` is the baseline settled after the previous attempt's checks, so a
    check's own artifacts are never charged to the model as work, and None never compares
    equal. ``message_index`` is where this attempt starts in ``RunOutput.messages``.
    """

    index: int
    verdicts: List[Verdict] = field(default_factory=list)
    fingerprint: Optional[str] = None
    compared_against: Optional[str] = None
    state_unchanged: bool = False
    message_index: int = 0

    @property
    def passed(self) -> bool:
        """Every required, non-skipped check passed. Advisory failures and skipped checks
        never gate; an attempt whose checks are all advisory passes with warnings on record.
        An attempt on which no check ran at all cannot pass: it verified nothing."""
        ran = [v for v in self.verdicts if not v.skipped]
        return bool(ran) and all(v.passed is True for v in ran if v.required)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "verdicts": [v.to_dict() for v in self.verdicts],
            # A user fingerprint may carry a lone surrogate, which the run row cannot store
            "fingerprint": encodable(self.fingerprint) if self.fingerprint is not None else None,
            "compared_against": encodable(self.compared_against) if self.compared_against is not None else None,
            "state_unchanged": self.state_unchanged,
            "message_index": self.message_index,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationAttempt":
        return cls(
            index=data.get("index", 0),
            verdicts=[Verdict.from_dict(v) for v in data.get("verdicts") or []],
            fingerprint=data.get("fingerprint"),
            compared_against=data.get("compared_against"),
            state_unchanged=data.get("state_unchanged", False),
            message_index=data.get("message_index", 0),
        )


@dataclass
class Verification:
    """The verification record of one run, carried on `RunOutput.verification`.

    `status` is "pending" while the loop is open (and on a run that left it paused, errored
    or cancelled before concluding); a concluded record is "verified" or "unverified". The
    record describes the run's last gated attempt window, not a mirror of RunStatus: a later
    continuation by an owner without verifiers can complete the run while the record still
    reads "unverified" - genuine audit history, healed by the next gated continuation.
    `stop_reason` is "passed" iff verified. `budget_baseline` is the number of attempts made
    before the current continuation window: continuing a run that ended unverified restarts
    the attempt budget for the new user instruction while keeping the full attempt history,
    so the budget check is `len(attempts) - budget_baseline >= max_attempts`.
    `baseline_fingerprint` is the baseline the open attempt compares against; it rides a HITL
    pause so the resumed attempt is compared against the state from before the pause.
    """

    status: VerificationStatus = VerificationStatus.pending
    stop_reason: Optional[VerificationStopReason] = None
    attempts: List[VerificationAttempt] = field(default_factory=list)
    baseline_fingerprint: Optional[str] = None
    budget_baseline: int = 0

    def __post_init__(self) -> None:
        # A plain string (a hand-built record) becomes the member; an unknown value raises.
        self.status = VerificationStatus(self.status)
        if self.stop_reason is not None:
            self.stop_reason = VerificationStopReason(self.stop_reason)

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.verified

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "stop_reason": self.stop_reason.value if self.stop_reason is not None else None,
            "attempts": [a.to_dict() for a in self.attempts],
            "baseline_fingerprint": encodable(self.baseline_fingerprint)
            if self.baseline_fingerprint is not None
            else None,
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
