"""The verification gate: the piece of the run loop that holds the model to its verifiers.

One `VerificationGate` is created per run-function invocation (inside the retry loop, so a
model-level retry starts with a fresh window) and drives a two-step protocol at the point
where the model has stopped and its output is parsed:

    gate = VerificationGate.for_run(owner, run_response=..., run_messages=..., run_context=..., session=...)
    if gate is not None:
        gate.begin()                       # once, before the first model call
    while True:
        ... model call, response update, pause check, structured output ...
        if gate is None:
            break
        started = gate.open_attempt()      # None when the gate must not run (paused leg)
        if started is None:
            break
        # emit started.event, then:
        decision = gate.settle_attempt()   # or: await gate.asettle_attempt()
        # emit decision.event, then:
        if decision.reenter:
            raise_if_cancelled(run_response.run_id)
            continue
        break

The gate owns all bookkeeping: the persisted record on ``run_response.verification``
(resuming it across HITL pauses, restarting the budget window when an unverified run is
continued), fingerprint capture and the settled comparison baseline, the report message
appended for a re-entry, and the terminal ``RunStatus.unverified`` stamp. The caller only
emits the two events and honours ``decision.reenter``.

Exception discipline: everything that executes user code is guarded (verifiers through
GuardedVerifier/CallableVerifier, fingerprints through safe_capture), so the gate itself
never raises into the surrounding retry loop.
"""

import asyncio
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Dict, List, Optional

from agno.run.base import RunStatus
from agno.verifiers.base import _ArgMap, _is_async_callable, run_sync
from agno.verifiers.fingerprints import asafe_capture, noop_between, safe_capture
from agno.verifiers.report import _first_line, build_report
from agno.verifiers.types import Verdict, Verification, VerificationAttempt, VerificationConfig

# ---------------------------------------------------------------------------
# The check runner — shared by every mount (the agent/team gate and the
# workflow Verify step), so the per-check policy semantics exist exactly once.
# ---------------------------------------------------------------------------


@dataclass
class CheckRun:
    """One pass over a mount's checks: the stamped verdicts, in declared order."""

    verdicts: List[Verdict] = field(default_factory=list)
    # True when a check marked fatal failed: the mount must stop re-entering immediately.
    fatal_failure: bool = False

    @property
    def passed(self) -> bool:
        """Every required, non-skipped check passed (vacuously true when none gate)."""
        return all(v.passed is True for v in self.verdicts if v.gates)


def _should_run(
    v: Any, verdicts_so_far: List[Verdict], run_output: Any, run_context: Any, owner: Any, session: Any
) -> bool:
    """Evaluate a check's run_when predicate. A broken predicate runs the check: skipping a
    gate on an exception would fail open."""
    run_when = getattr(v, "run_when", None)
    if run_when is None:
        return True
    try:
        argmap = _ArgMap(run_when, label=f"verifier {getattr(v, 'name', '?')!r} run_when", extra_allowed=("verdicts",))
        args, kwargs = argmap.build(run_output, run_context, owner, session, extras={"verdicts": list(verdicts_so_far)})
        result = run_when(*args, **kwargs)
        if _is_async_callable(run_when):
            result = run_sync(result)
        return bool(result)
    except Exception:
        return True


async def _ashould_run(
    v: Any, verdicts_so_far: List[Verdict], run_output: Any, run_context: Any, owner: Any, session: Any
) -> bool:
    """Async twin of `_should_run`."""
    run_when = getattr(v, "run_when", None)
    if run_when is None:
        return True
    try:
        argmap = _ArgMap(run_when, label=f"verifier {getattr(v, 'name', '?')!r} run_when", extra_allowed=("verdicts",))
        args, kwargs = argmap.build(run_output, run_context, owner, session, extras={"verdicts": list(verdicts_so_far)})
        if _is_async_callable(run_when):
            result = await run_when(*args, **kwargs)
        else:
            result = await asyncio.to_thread(run_when, *args, **kwargs)
        return bool(result)
    except Exception:
        return True


def _stamp(verdict: Verdict, v: Any, index: int) -> Verdict:
    return verdict.named(getattr(v, "name", "") or f"verifier {index}").stamped(required=getattr(v, "required", True))


def run_checks(
    verifiers: List[Any],
    run_output: Any,
    run_context: Any = None,
    owner: Any = None,
    session: Any = None,
) -> CheckRun:
    """Run coerced checks in declared order, no short-circuit, honouring per-check policy:
    `run_when` skips (recorded, non-gating), `rerun` retries the check itself before
    trusting a failure, `required=False` reports without gating, `fatal` flags the run as
    not worth re-entering."""
    result = CheckRun()
    for index, v in enumerate(verifiers):
        required = getattr(v, "required", True)
        if not _should_run(v, result.verdicts, run_output, run_context, owner, session):
            result.verdicts.append(
                Verdict(
                    passed=True, name=getattr(v, "name", "") or f"verifier {index}", required=required, skipped=True
                )
            )
            continue
        tries = 1 + max(int(getattr(v, "rerun", 0) or 0), 0)
        verdict = None
        for _ in range(tries):
            verdict = v.verify(run_output=run_output, run_context=run_context, owner=owner, session=session)
            if verdict.passed is True:
                break
        verdict = _stamp(verdict, v, index)  # type: ignore[arg-type]
        result.verdicts.append(verdict)
        if getattr(v, "fatal", False) and verdict.passed is not True:
            result.fatal_failure = True
    return result


async def arun_checks(
    verifiers: List[Any],
    run_output: Any,
    run_context: Any = None,
    owner: Any = None,
    session: Any = None,
) -> CheckRun:
    """Async twin of `run_checks`."""
    result = CheckRun()
    for index, v in enumerate(verifiers):
        required = getattr(v, "required", True)
        if not await _ashould_run(v, result.verdicts, run_output, run_context, owner, session):
            result.verdicts.append(
                Verdict(
                    passed=True, name=getattr(v, "name", "") or f"verifier {index}", required=required, skipped=True
                )
            )
            continue
        tries = 1 + max(int(getattr(v, "rerun", 0) or 0), 0)
        verdict = None
        for _ in range(tries):
            verdict = await v.averify(run_output=run_output, run_context=run_context, owner=owner, session=session)
            if verdict.passed is True:
                break
        verdict = _stamp(verdict, v, index)  # type: ignore[arg-type]
        result.verdicts.append(verdict)
        if getattr(v, "fatal", False) and verdict.passed is not True:
            result.fatal_failure = True
    return result


@dataclass
class AttemptStarted:
    """What `open_attempt` hands back: the started event, ready to emit."""

    event: Any


@dataclass
class GateDecision:
    """What `settle_attempt` hands back.

    ``reenter`` means the report was appended to the run's messages and the model must be
    called again. When it is False the loop is over: the run is verified (``passed``) or the
    gate already stamped ``RunStatus.unverified`` on the run_response.
    """

    reenter: bool
    passed: bool
    event: Any


def _filtered_len(messages: List[Any]) -> int:
    """Index the attempt starts at, in the add_to_agent_memory view that becomes
    ``RunOutput.messages``."""
    return sum(1 for m in messages if getattr(m, "add_to_agent_memory", True))


class VerificationGate:
    def __init__(
        self,
        owner: Any,
        run_response: Any,
        run_messages: Any,
        run_context: Any,
        session: Any,
        verifiers: List[Any],
        config: VerificationConfig,
        team_mode: bool = False,
        resume: bool = True,
    ) -> None:
        self.owner = owner
        self.run_response = run_response
        self.run_messages = run_messages
        self.run_context = run_context
        self.session = session
        self.verifiers = verifiers
        self.config = config
        self.team_mode = team_mode
        self.resume = resume
        self._t0: Optional[float] = None
        self._settled: Optional[str] = None
        self._attempt_start: int = 0
        self._open: Optional[VerificationAttempt] = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def for_run(
        cls,
        owner: Any,
        run_response: Any,
        run_messages: Any,
        run_context: Any,
        session: Any,
        resume: bool,
        team_mode: bool = False,
    ) -> Optional["VerificationGate"]:
        """The gate for this run, or None when the owner has no verifiers configured.

        The verifier list is coerced fresh on every run (about 25 microseconds for five
        checks): a cached list goes stale the moment the owner's ``verifiers`` is mutated,
        and a stale gate fails open. The constructor's eager coercion remains purely as
        fail-fast validation. ``resume`` says whether a record already on the run_response
        is continued (the continue paths: HITL resumes, continue-in-place) or reset (the
        run paths: a model-level retry must start a fresh window, not resurrect attempts
        whose message indices point into the discarded transcript).
        """
        raw = getattr(owner, "verifiers", None)
        if not raw:
            return None
        from agno.verifiers.base import coerce_verifier

        verifiers = [coerce_verifier(v) for v in raw]
        config = getattr(owner, "verification", None) or VerificationConfig()
        return cls(
            owner=owner,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            session=session,
            verifiers=verifiers,
            config=config,
            team_mode=team_mode,
            resume=resume,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def begin(self) -> None:
        """Once, before the first model call: bind or resume the record, start the clock,
        capture the comparison baseline.

        A record already on the run_response is resumed: a "pending" one continues where a
        HITL pause left it (the budget holds across the pause); an "unverified" one means
        the caller is continuing a run that already exhausted its budget — the history is
        kept and the budget window restarts for the new instruction. The baseline for the
        first no-op comparison is captured NOW, not inherited: a continuation starts from
        the world as it stands.
        """
        record = getattr(self.run_response, "verification", None)
        if record is None or not isinstance(record, Verification) or not self.resume:
            # The run paths never resume: a pre-existing record there can only be a
            # model-level retry's leftover, whose attempts index a discarded transcript.
            record = Verification()
            self.run_response.verification = record
        if record.status == "unverified":
            record.status = "pending"
            record.stop_reason = None
            record.budget_baseline = len(record.attempts)
        self._t0 = monotonic()
        if self.config.fingerprint is not None:
            self._settled = safe_capture(self.config.fingerprint)
            if record.baseline_fingerprint is None:
                record.baseline_fingerprint = self._settled
        self._attempt_start = _filtered_len(self.run_messages.messages)

    async def abegin(self) -> None:
        """Async twin of `begin`."""
        record = getattr(self.run_response, "verification", None)
        if record is None or not isinstance(record, Verification) or not self.resume:
            # The run paths never resume: a pre-existing record there can only be a
            # model-level retry's leftover, whose attempts index a discarded transcript.
            record = Verification()
            self.run_response.verification = record
        if record.status == "unverified":
            record.status = "pending"
            record.stop_reason = None
            record.budget_baseline = len(record.attempts)
        self._t0 = monotonic()
        if self.config.fingerprint is not None:
            self._settled = await asafe_capture(self.config.fingerprint)
            if record.baseline_fingerprint is None:
                record.baseline_fingerprint = self._settled
        self._attempt_start = _filtered_len(self.run_messages.messages)

    # ------------------------------------------------------------------
    # One attempt
    # ------------------------------------------------------------------

    def _paused(self) -> bool:
        # The stream loops reach the gate before their own pause handling, so the gate
        # checks for a paused tool itself; verifiers must never run on a paused attempt.
        if getattr(self.run_response, "is_paused", False):
            return True
        return any(getattr(t, "is_paused", False) for t in getattr(self.run_response, "tools", None) or [])

    def _record(self) -> Verification:
        record = self.run_response.verification
        if record is None or not isinstance(record, Verification):
            record = Verification()
            self.run_response.verification = record
        return record

    def _attempt_number(self, record: Verification) -> int:
        """1-based position of the CURRENT attempt within the budget window."""
        return len(record.attempts) - record.budget_baseline + 1

    def open_attempt(self) -> Optional[AttemptStarted]:
        """Build this attempt and hand back the started event — or None when the gate must
        not run (the model paused for HITL; the pause leg persists the pending record)."""
        if self._paused():
            return None
        record = self._record()
        self._open = VerificationAttempt(index=len(record.attempts), message_index=self._attempt_start)
        event = self._build_started_event(self._attempt_number(record))
        return AttemptStarted(event=event)

    def settle_attempt(self) -> GateDecision:
        """Capture, verify, settle, decide. Sync path: async verifier halves run through the
        package's bridge inside their adapters."""
        record = self._record()
        attempt = self._open
        assert attempt is not None, "settle_attempt called without open_attempt"
        self._open = None
        if self.config.fingerprint is not None:
            attempt.fingerprint = safe_capture(self.config.fingerprint)
            attempt.compared_against = self._settled
            attempt.noop = noop_between(self._settled, attempt.fingerprint)
        check_run = run_checks(
            self.verifiers,
            run_output=self.run_response,
            run_context=self.run_context,
            owner=self.owner,
            session=self.session,
        )
        attempt.verdicts = check_run.verdicts
        record.attempts.append(attempt)
        decision = self._decide(record, attempt, fatal_failure=check_run.fatal_failure)
        if decision.reenter and self.config.fingerprint is not None:
            # Settle AFTER the verifiers: their artefacts (a .pytest_cache, a formatter
            # pass) must not be charged to the model as the next attempt's work. Only a
            # re-entry needs the baseline; a terminal attempt's capture would be waste.
            self._settled = safe_capture(self.config.fingerprint)
        return decision

    async def asettle_attempt(self) -> GateDecision:
        """Async twin of `settle_attempt`."""
        record = self._record()
        attempt = self._open
        assert attempt is not None, "asettle_attempt called without open_attempt"
        self._open = None
        if self.config.fingerprint is not None:
            attempt.fingerprint = await asafe_capture(self.config.fingerprint)
            attempt.compared_against = self._settled
            attempt.noop = noop_between(self._settled, attempt.fingerprint)
        check_run = await arun_checks(
            self.verifiers,
            run_output=self.run_response,
            run_context=self.run_context,
            owner=self.owner,
            session=self.session,
        )
        attempt.verdicts = check_run.verdicts
        record.attempts.append(attempt)
        decision = self._decide(record, attempt, fatal_failure=check_run.fatal_failure)
        if decision.reenter and self.config.fingerprint is not None:
            self._settled = await asafe_capture(self.config.fingerprint)
        return decision

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _decide(self, record: Verification, attempt: VerificationAttempt, fatal_failure: bool = False) -> GateDecision:
        attempts_used = len(record.attempts) - record.budget_baseline
        passed = attempt.passed
        reenter = False
        if fatal_failure:
            # A fatal check failed: retrying is pointless by the author's own declaration,
            # whatever the remaining budget says.
            record.status = "unverified"
            record.stop_reason = "fatal"
        elif passed:
            record.status = "verified"
            record.stop_reason = "passed"
        elif attempt.noop and self.config.stop_on_noop:
            record.status = "unverified"
            record.stop_reason = "noop"
        elif (
            self.config.timeout_s is not None
            and self._t0 is not None
            and monotonic() - self._t0 >= self.config.timeout_s
        ):
            record.status = "unverified"
            record.stop_reason = "timeout"
        elif attempts_used >= self.config.max_attempts:
            record.status = "unverified"
            record.stop_reason = "exhausted"
        else:
            reenter = True
            report = build_report(
                attempt,
                attempt_number=attempts_used,
                total_attempts=self.config.max_attempts,
                has_fingerprint=self.config.fingerprint is not None,
                stop_on_noop=self.config.stop_on_noop,
            )
            from agno.models.message import Message

            # Default flags, deliberately: the report is part of the run's real transcript
            # (persisted, replayed into later history). temporary=True would strip it before
            # persistence and the record's message_index slicing would lie.
            self.run_messages.messages.append(Message(role="user", content=report))
            self._attempt_start = _filtered_len(self.run_messages.messages)
        if record.status == "unverified":
            self.run_response.status = RunStatus.unverified
        event = self._build_completed_event(
            attempt_number=attempts_used,
            passed=passed,
            verdicts=attempt.verdicts,
            noop=attempt.noop,
            stop_reason=record.stop_reason if record.status != "pending" else None,
        )
        return GateDecision(reenter=reenter, passed=passed, event=event)

    def _verdict_payload(self, verdicts: List[Verdict]) -> List[Dict[str, Any]]:
        return [
            {
                "name": v.name,
                "passed": v.passed,
                "summary": _first_line(v.report),
                "required": v.required,
                "skipped": v.skipped,
            }
            for v in verdicts
        ]

    def _build_started_event(self, attempt_number: int) -> Any:
        if self.team_mode:
            from agno.utils.events import create_team_verification_started_event

            return create_team_verification_started_event(
                self.run_response, attempt=attempt_number, max_attempts=self.config.max_attempts
            )
        from agno.utils.events import create_verification_started_event

        return create_verification_started_event(
            self.run_response, attempt=attempt_number, max_attempts=self.config.max_attempts
        )

    def _build_completed_event(
        self,
        attempt_number: int,
        passed: bool,
        verdicts: List[Verdict],
        noop: bool,
        stop_reason: Optional[str],
    ) -> Any:
        payload = self._verdict_payload(verdicts)
        if self.team_mode:
            from agno.utils.events import create_team_verification_completed_event

            return create_team_verification_completed_event(
                self.run_response,
                attempt=attempt_number,
                max_attempts=self.config.max_attempts,
                passed=passed,
                verdicts=payload,
                noop=noop,
                stop_reason=stop_reason,
            )
        from agno.utils.events import create_verification_completed_event

        return create_verification_completed_event(
            self.run_response,
            attempt=attempt_number,
            max_attempts=self.config.max_attempts,
            passed=passed,
            verdicts=payload,
            noop=noop,
            stop_reason=stop_reason,
        )
