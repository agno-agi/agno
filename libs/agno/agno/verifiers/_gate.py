"""The verification gate: the piece of the run loop that holds the model to its verifiers.

One gate is created per run-function invocation. ``begin()`` opens the budget window before
the first model call; after each model stop ``open_attempt()`` and ``settle_attempt()`` run the
checks and decide whether the model re-enters. The gate owns the persisted record, the
fingerprint baseline, the report message and the terminal ``RunStatus.unverified`` stamp; the
callers (``verify_response`` and its async and streaming versions) only emit the two events. Everything that runs
user code is guarded, so the gate never raises into the surrounding retry loop.
"""

import asyncio
from dataclasses import dataclass, field, replace
from time import monotonic
from typing import Any, Dict, List, Optional

from agno.models.message import Message
from agno.run.base import RunStatus
from agno.utils.events import (
    create_team_verification_completed_event,
    create_team_verification_started_event,
    create_verification_completed_event,
    create_verification_started_event,
)
from agno.utils.log import log_debug
from agno.utils.verifiers import resolve_verification
from agno.verifiers.base import CoercedVerifier, coerce_verifier, is_async_callable, verifier_args
from agno.verifiers.fingerprints import asafe_capture, safe_capture, state_unchanged
from agno.verifiers.report import build_report
from agno.verifiers.types import (
    Verdict,
    Verification,
    VerificationAttempt,
    VerificationConfig,
    VerificationStatus,
    VerificationStopReason,
)

# ---------------------------------------------------------------------------
# The check runner, shared by the agent/team gate and the workflow Verify step
# ---------------------------------------------------------------------------


@dataclass
class VerifierResults:
    """One pass over a mount's checks: the stamped verdicts, in declared order."""

    verdicts: List[Verdict] = field(default_factory=list)
    # True when a stop_on_failure check (or a fatal verdict) failed: the mount must stop re-entering immediately.
    fatal_failure: bool = False

    @property
    def passed(self) -> bool:
        """Every required, non-skipped check passed; an attempt on which no check ran cannot."""
        ran = [v for v in self.verdicts if not v.skipped]
        return bool(ran) and all(v.passed is True for v in ran if v.required)


def _should_run(
    v: Any, verdicts_so_far: List[Verdict], run_output: Any, run_context: Any, owner: Any, session: Any
) -> bool:
    """Evaluate a check's run_condition predicate. A broken predicate runs the check: skipping a
    gate on an exception would fail open.
    """
    run_condition = v.run_condition
    if run_condition is None:
        return True
    try:
        kwargs = verifier_args(run_condition, run_output, run_context, owner, session, verdicts=list(verdicts_so_far))
        return bool(run_condition(**kwargs))
    except (Exception, SystemExit):
        return True


async def _ashould_run(
    v: Any, verdicts_so_far: List[Verdict], run_output: Any, run_context: Any, owner: Any, session: Any
) -> bool:
    """Async version of `_should_run`."""
    run_condition = v.run_condition
    if run_condition is None:
        return True
    try:
        kwargs = verifier_args(run_condition, run_output, run_context, owner, session, verdicts=list(verdicts_so_far))
        if is_async_callable(run_condition):
            result = await run_condition(**kwargs)
        else:
            result = await asyncio.to_thread(run_condition, **kwargs)
        return bool(result)
    except (Exception, SystemExit):
        return True


def _stamp(verdict: Verdict, name: str, v: "CoercedVerifier") -> Verdict:
    # skipped=False unconditionally: only the loop's run_condition branch records a skip, so a
    # returned skipped=True cannot pass a required failure. The loop's name wins.
    if verdict.name != name:
        verdict = replace(verdict, name=name)
    return verdict.stamped(required=v.required, skipped=False)


def _check_names(verifiers: List[Any]) -> List[str]:
    """Display names in declared order, made distinct so two checks called `tests` are told apart."""
    names: List[str] = []
    seen: Dict[str, int] = {}
    for index, v in enumerate(verifiers):
        name = getattr(v, "name", "") or f"verifier {index}"
        seen[name] = seen.get(name, 0) + 1
        names.append(name if seen[name] == 1 else f"{name} #{seen[name]}")
    return names


def _fatal(v: Any, verdict: Verdict) -> bool:
    # A verdict marks itself fatal for a harness error (the check's own command missing).
    # An advisory check never gates the outcome, so it never ends the run either.
    return v.required and (v.stop_on_failure or verdict.fatal)


def run_checks(
    verifiers: List[Any],
    run_output: Any,
    run_context: Any = None,
    owner: Any = None,
    session: Any = None,
) -> VerifierResults:
    """Run coerced checks in declared order, no short-circuit, honoring per-check policy:
    `run_condition` skips (recorded, non-gating), `max_retries` retries the check itself before
    trusting a failure, `required=False` reports without gating, `stop_on_failure` flags the run as
    not worth re-entering.
    """
    result = VerifierResults()
    for name, v in zip(_check_names(verifiers), verifiers):
        required = v.required
        if not _should_run(v, result.verdicts, run_output, run_context, owner, session):
            result.verdicts.append(Verdict(passed=True, name=name, required=required, skipped=True))
            continue
        verdict = v.verify(run_output=run_output, run_context=run_context, owner=owner, session=session)
        for _ in range(v.max_retries):
            if verdict.passed is True:
                break
            verdict = v.verify(run_output=run_output, run_context=run_context, owner=owner, session=session)
        verdict = _stamp(verdict, name, v)
        result.verdicts.append(verdict)
        if verdict.passed is not True and _fatal(v, verdict):
            result.fatal_failure = True
    return result


async def arun_checks(
    verifiers: List[Any],
    run_output: Any,
    run_context: Any = None,
    owner: Any = None,
    session: Any = None,
) -> VerifierResults:
    """Async version of `run_checks`."""
    result = VerifierResults()
    for name, v in zip(_check_names(verifiers), verifiers):
        required = v.required
        if not await _ashould_run(v, result.verdicts, run_output, run_context, owner, session):
            result.verdicts.append(Verdict(passed=True, name=name, required=required, skipped=True))
            continue
        verdict = await v.averify(run_output=run_output, run_context=run_context, owner=owner, session=session)
        for _ in range(v.max_retries):
            if verdict.passed is True:
                break
            verdict = await v.averify(run_output=run_output, run_context=run_context, owner=owner, session=session)
        verdict = _stamp(verdict, name, v)
        result.verdicts.append(verdict)
        if verdict.passed is not True and _fatal(v, verdict):
            result.fatal_failure = True
    return result


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
    """Index the attempt starts at, in the view that is persisted as ``RunOutput.messages``:
    add_to_agent_memory messages that are not replayed history.
    """
    return sum(1 for m in messages if getattr(m, "add_to_agent_memory", True) and not getattr(m, "from_history", False))


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
        # Whether the last settled attempt asks for a re-entry; the stream legs read it after yielding
        self.reenter: bool = False
        self.owner = owner
        self.run_response = run_response
        self.run_messages = run_messages
        self.run_context = run_context
        self.session = session
        self.verifiers = verifiers
        self.config = config
        self.team_mode = team_mode
        self.resume = resume
        self._started_at: Optional[float] = None
        self._settled: Optional[str] = None
        self._attempt_start: int = 0
        self._open: Optional[VerificationAttempt] = None
        self._reasoning: Any = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_run(
        cls,
        owner: Any,
        run_response: Any,
        run_messages: Any,
        run_context: Any,
        session: Any,
        resume: bool,
        team_mode: bool = False,
    ) -> Optional["VerificationGate"]:
        """The gate for this run, or None when the owner's runs are not verified.

        The verifiers are coerced on every run, so a mutated ``verifiers`` list is never stale.
        ``resume`` continues a record already on the run_response (HITL resumes,
        continue-in-place); the run paths reset it, so a model-level retry never resurrects
        attempts whose message indices point into the discarded transcript.
        """
        config = resolve_verification(owner)
        if config is None:
            return None
        verifiers = [coerce_verifier(v) for v in owner.verifiers]
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

    def _open_window(self) -> Verification:
        """Bind or resume the record and open a fresh budget window on it.

        A record already on the run_response is resumed: a "pending" one continues where a
        HITL pause left it (the budget holds across the pause); a settled one means the
        caller is continuing a run whose window already closed — the history is kept and the
        budget window restarts for the new instruction. A stale unverified stamp from an
        earlier window is cleared with it: this window decides the run's status afresh.
        """
        record = getattr(self.run_response, "verification", None)
        if record is None or not isinstance(record, Verification) or not self.resume:
            # The run paths never resume: a pre-existing record there can only be a
            # model-level retry's leftover, whose attempts index a discarded transcript.
            record = Verification()
            self.run_response.verification = record
        if record.status != VerificationStatus.pending:
            record.status = VerificationStatus.pending
            record.stop_reason = None
            record.budget_baseline = len(record.attempts)
            record.baseline_fingerprint = None
        if self.run_response.status == RunStatus.unverified:
            self.run_response.status = RunStatus.running
        self._started_at = monotonic()
        self._reasoning = getattr(self.run_response, "reasoning_content", None)
        self._attempt_start = _filtered_len(self.run_messages.messages)
        return record

    def begin(self) -> None:
        """Once, before the first model call: open the window, start the clock, capture the
        comparison baseline. A new window captures it from the world as it stands; a resumed HITL
        pause keeps the baseline stored before the pause, since the confirmed tools already ran
        and their changes belong to the paused attempt.
        """
        record = self._open_window()
        if self.config.fingerprint is not None:
            if record.baseline_fingerprint is None:
                record.baseline_fingerprint = safe_capture(self.config.fingerprint)
            self._settled = record.baseline_fingerprint

    async def abegin(self) -> None:
        """Async version of `begin`."""
        record = self._open_window()
        if self.config.fingerprint is not None:
            if record.baseline_fingerprint is None:
                record.baseline_fingerprint = await asafe_capture(self.config.fingerprint)
            self._settled = record.baseline_fingerprint

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
        """1-based position of the current attempt within the budget window."""
        return len(record.attempts) - record.budget_baseline + 1

    def open_attempt(self) -> Optional[Any]:
        """Build this attempt and hand back the started event — or None when the gate must
        not run (the model paused for HITL; the pause leg persists the pending record).
        """
        # The stream legs read `reenter` after this call: a paused attempt must not inherit
        # the previous attempt's re-entry and call the model over an unanswered tool call.
        self.reenter = False
        if self._paused():
            return None
        record = self._record()
        self._open = VerificationAttempt(index=len(record.attempts), message_index=self._attempt_start)
        event = self._build_started_event(self._attempt_number(record))
        return event

    def settle_attempt(self) -> GateDecision:
        """Capture, verify, settle, decide."""
        record = self._record()
        attempt = self._open
        if attempt is None:
            raise RuntimeError("settle_attempt called without open_attempt")
        self._open = None
        if self.config.fingerprint is not None:
            attempt.fingerprint = safe_capture(self.config.fingerprint)
            attempt.compared_against = self._settled
            attempt.state_unchanged = state_unchanged(self._settled, attempt.fingerprint)
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
            # Settle after the verifiers: their artifacts (a .pytest_cache, a formatter
            # pass) must not be charged to the model as the next attempt's work. Only a
            # re-entry needs the baseline; a terminal attempt's capture would be waste.
            self._settled = safe_capture(self.config.fingerprint)
            record.baseline_fingerprint = self._settled
        return decision

    async def asettle_attempt(self) -> GateDecision:
        """Async version of `settle_attempt`."""
        record = self._record()
        attempt = self._open
        if attempt is None:
            raise RuntimeError("asettle_attempt called without open_attempt")
        self._open = None
        if self.config.fingerprint is not None:
            attempt.fingerprint = await asafe_capture(self.config.fingerprint)
            attempt.compared_against = self._settled
            attempt.state_unchanged = state_unchanged(self._settled, attempt.fingerprint)
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
            record.baseline_fingerprint = self._settled
        return decision

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _decide(self, record: Verification, attempt: VerificationAttempt, fatal_failure: bool = False) -> GateDecision:
        attempts_used = len(record.attempts) - record.budget_baseline
        passed = attempt.passed
        reenter = False
        if fatal_failure:
            # A stop_on_failure check failed: the author declared that retrying cannot fix it,
            # whatever the remaining budget says.
            record.status = VerificationStatus.unverified
            record.stop_reason = VerificationStopReason.fatal
        elif passed:
            record.status = VerificationStatus.verified
            record.stop_reason = VerificationStopReason.passed
        elif attempt.state_unchanged and self.config.stop_on_unchanged_state:
            record.status = VerificationStatus.unverified
            record.stop_reason = VerificationStopReason.unchanged_state
        elif (
            self.config.timeout is not None
            and self._started_at is not None
            and monotonic() - self._started_at >= self.config.timeout
        ):
            record.status = VerificationStatus.unverified
            record.stop_reason = VerificationStopReason.timeout
        elif attempts_used >= self.config.max_attempts:
            record.status = VerificationStatus.unverified
            record.stop_reason = VerificationStopReason.exhausted
        else:
            reenter = True
            log_debug(
                f"Re-entering run {self.run_response.run_id}. Verification attempt {attempts_used} of {self.config.max_attempts} failed..."
            )
            # The text fields reset on re-entry so the caller receives the accepted attempt's
            # answer: a streamed pass appends to content and a pass with no text leaves it.
            # Media is not reset. Model-generated media lives only on these top-level lists
            # (never on the assistant Message), so a reset would lose a rejected attempt's
            # drawing for good; like tools, media accumulates across attempts, and a checkpoint
            # media_reference must never be dropped. Reasoning written once before the loop is
            # restored, not cleared.
            self.run_response.content = None
            self.run_response.citations = None
            self.run_response.model_provider_data = None
            self.run_response.reasoning_content = self._reasoning
            report = build_report(
                attempt,
                attempt_number=attempts_used,
                total_attempts=self.config.max_attempts,
                has_fingerprint=self.config.fingerprint is not None,
                stop_on_unchanged_state=self.config.stop_on_unchanged_state,
            )
            # The report is real transcript (persisted, replayed), so no temporary flag. It is
            # mirrored onto the run output's own list when that is a separate list.
            message = Message(role="user", content=report)
            self.run_messages.messages.append(message)
            mirrored = getattr(self.run_response, "messages", None)
            if isinstance(mirrored, list) and mirrored is not self.run_messages.messages:
                mirrored.append(message)
            self._attempt_start = _filtered_len(self.run_messages.messages)
        if record.status == VerificationStatus.unverified:
            self.run_response.status = RunStatus.unverified
        event = self._build_completed_event(
            attempt_number=attempts_used,
            passed=passed,
            verdicts=attempt.verdicts,
            state_unchanged=attempt.state_unchanged,
            stop_reason=record.stop_reason.value
            if record.stop_reason is not None and record.status != VerificationStatus.pending
            else None,
        )
        self.reenter = reenter
        return GateDecision(reenter=reenter, passed=passed, event=event)

    def _build_started_event(self, attempt_number: int) -> Any:
        if self.team_mode:
            return create_team_verification_started_event(
                self.run_response, attempt=attempt_number, max_attempts=self.config.max_attempts
            )
        return create_verification_started_event(
            self.run_response, attempt=attempt_number, max_attempts=self.config.max_attempts
        )

    def _build_completed_event(
        self,
        attempt_number: int,
        passed: bool,
        verdicts: List[Verdict],
        state_unchanged: bool,
        stop_reason: Optional[str],
    ) -> Any:
        if self.team_mode:
            return create_team_verification_completed_event(
                self.run_response,
                attempt=attempt_number,
                max_attempts=self.config.max_attempts,
                passed=passed,
                verdicts=list(verdicts),
                state_unchanged=state_unchanged,
                stop_reason=stop_reason,
            )
        return create_verification_completed_event(
            self.run_response,
            attempt=attempt_number,
            max_attempts=self.config.max_attempts,
            passed=passed,
            verdicts=list(verdicts),
            state_unchanged=state_unchanged,
            stop_reason=stop_reason,
        )
