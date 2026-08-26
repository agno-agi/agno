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

from dataclasses import dataclass
from time import monotonic
from typing import Any, Dict, List, Optional

from agno.run.base import RunStatus
from agno.verifiers.fingerprints import asafe_capture, noop_between, safe_capture
from agno.verifiers.report import _first_line, build_report
from agno.verifiers.types import Verdict, Verification, VerificationAttempt, VerificationConfig


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
    ) -> None:
        self.owner = owner
        self.run_response = run_response
        self.run_messages = run_messages
        self.run_context = run_context
        self.session = session
        self.verifiers = verifiers
        self.config = config
        self.team_mode = team_mode
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
        team_mode: bool = False,
    ) -> Optional["VerificationGate"]:
        """The gate for this run, or None when the owner has no verifiers configured."""
        raw = getattr(owner, "verifiers", None)
        if not raw:
            return None
        verifiers = getattr(owner, "_verifiers", None)
        if not verifiers:
            # A deep-copied owner (team member clones, reasoning agents) keeps its public
            # fields but not the private coerced list; rebuild it so a copy is never
            # silently ungated.
            from agno.verifiers.base import coerce_verifier

            verifiers = [coerce_verifier(v) for v in raw]
            try:
                owner._verifiers = verifiers
            except Exception:
                pass
        config = getattr(owner, "verification", None) or VerificationConfig()
        return cls(
            owner=owner,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            session=session,
            verifiers=list(verifiers),
            config=config,
            team_mode=team_mode,
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
        if record is None or not isinstance(record, Verification):
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
        if record is None or not isinstance(record, Verification):
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
        attempt.verdicts = self._run_verifiers_sync()
        record.attempts.append(attempt)
        if self.config.fingerprint is not None:
            # Settle AFTER the verifiers: their artefacts (a .pytest_cache, a formatter
            # pass) must not be charged to the model as the next attempt's work.
            self._settled = safe_capture(self.config.fingerprint)
        return self._decide(record, attempt)

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
        attempt.verdicts = await self._run_verifiers_async()
        record.attempts.append(attempt)
        if self.config.fingerprint is not None:
            self._settled = await asafe_capture(self.config.fingerprint)
        return self._decide(record, attempt)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _run_verifiers_sync(self) -> List[Verdict]:
        verdicts: List[Verdict] = []
        for index, v in enumerate(self.verifiers):
            verdict = v.verify(
                run_output=self.run_response,
                run_context=self.run_context,
                owner=self.owner,
                session=self.session,
            )
            verdicts.append(verdict.named(getattr(v, "name", "") or f"verifier {index}"))
        return verdicts

    async def _run_verifiers_async(self) -> List[Verdict]:
        verdicts: List[Verdict] = []
        for index, v in enumerate(self.verifiers):
            verdict = await v.averify(
                run_output=self.run_response,
                run_context=self.run_context,
                owner=self.owner,
                session=self.session,
            )
            verdicts.append(verdict.named(getattr(v, "name", "") or f"verifier {index}"))
        return verdicts

    def _decide(self, record: Verification, attempt: VerificationAttempt) -> GateDecision:
        attempts_used = len(record.attempts) - record.budget_baseline
        passed = attempt.passed
        reenter = False
        if passed:
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
        return [{"name": v.name, "passed": v.passed, "summary": _first_line(v.report)} for v in verdicts]

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
