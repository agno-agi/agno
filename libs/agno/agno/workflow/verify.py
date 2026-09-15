"""The Verify workflow step: a cross-step gate that loops earlier steps back with evidence.

The checks run against the previous step's output. On failure with attempts left, the segment
from ``on_fail`` through the step before the Verify re-runs with the evidence report on its
input; when the budget is spent, or ``on_fail=None`` makes it a pure gate, the step ends with
``success=False`` and the record on its StepOutput. ``resolve_verify_steps`` absorbs the
segment at prepare time, so at execution a Verify is an ordinary composite like ``Loop``.
"""

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Union
from uuid import uuid4

from agno.exceptions import RunCancelledException
from agno.media.storage.base import AsyncMediaStorage, MediaStorage
from agno.run.agent import RunOutputEvent
from agno.run.base import RunContext
from agno.run.cancel import araise_if_cancelled, raise_if_cancelled
from agno.run.team import TeamRunOutputEvent
from agno.run.workflow import (
    VerifyAttemptCompletedEvent,
    VerifyAttemptStartedEvent,
    VerifyExecutionCompletedEvent,
    VerifyExecutionStartedEvent,
    WorkflowRunOutput,
    WorkflowRunOutputEvent,
)
from agno.session.workflow import WorkflowSession
from agno.utils.log import log_debug
from agno.utils.verifiers import (
    require_sync_verifiers,
    verifier_to_dict,
    verifiers_from_dict,
    warn_stop_on_unchanged_state_not_restored,
)
from agno.verifiers._gate import VerifierResults, arun_checks, run_checks
from agno.verifiers.base import coerce_verifier
from agno.verifiers.fingerprints import asafe_capture, coerce_fingerprint, safe_capture, state_unchanged
from agno.verifiers.report import build_report
from agno.verifiers.types import Verification, VerificationAttempt, VerificationStatus, VerificationStopReason
from agno.workflow.step import UnresolvableCallableError, get_deepest_content_from_step_output
from agno.workflow.types import HumanReview, OnError, StepInput, StepOutput, StepType

if TYPE_CHECKING:
    from agno.registry import Registry


class UnresolvedVerifyError(UnresolvableCallableError):
    """Raised when a Verify executes without ever absorbing its loop-back segment.

    Containers that tolerate ordinary step failures re-raise this one: recording it
    as a step output would let the run complete ungated.
    """


@dataclass
class Verify:
    """A verification gate between workflow steps.

    Args:
        checks: The checks to run — bare callables, shipped verifiers
            (``ShellVerifier``/``ScorerVerifier``), protocol objects, or ``verifier()``
            wrappers. Coerced once here, so a bad entry fails at construction.
        on_fail: The step to loop back to on failure — a step name or index from the same
            steps list, strictly before the Verify. Defaults to ``"previous"``, the immediately
            preceding step; a step literally named "previous" must be targeted by index.
            ``None`` makes the Verify a pure gate: one check pass, no loop-back.
        max_attempts: Total passes through the checks, the first one included; each failed
            attempt with budget left loops the segment back once.
        stop_on_unchanged_state: With a fingerprint, a failed attempt that changed nothing ends
            the loop as unverified instead of spending further attempts.
        fingerprint: Optional world-state fingerprint captured around each attempt.
        stop_on_unverified: When True and the step ends unverified, the StepOutput
            carries ``stop=True`` so the workflow skips every downstream step. Default
            False: the workflow's ordinary routing decides what an unverified result
            means.
        name: Step name; defaults to "verify".
    """

    name: str = "verify"
    description: Optional[str] = None
    on_fail: Optional[Union[str, int]] = "previous"
    max_attempts: int = 3
    stop_on_unchanged_state: bool = False
    fingerprint: Optional[Any] = None
    stop_on_unverified: bool = False
    # The absorbed loop-back segment, filled by resolve_verify_steps; a pure gate has none
    steps: List[Any] = field(default_factory=list)

    def __init__(
        self,
        checks: Union[List[Any], Any],
        on_fail: Optional[Union[str, int]] = "previous",
        max_attempts: int = 3,
        stop_on_unchanged_state: bool = False,
        fingerprint: Optional[Any] = None,
        stop_on_unverified: bool = False,
        name: Optional[str] = None,
    ):
        if not isinstance(checks, (list, tuple)):
            raise TypeError(f"Verify checks must be a list of callables or Verifiers, got {type(checks).__name__}")
        if not checks:
            raise ValueError("Verify requires at least one check")
        self._verifiers = [coerce_verifier(entry) for entry in checks]
        if max_attempts < 1:
            raise ValueError(f"Verify max_attempts must be a positive int, got {max_attempts!r}")
        if stop_on_unchanged_state and fingerprint is None:
            raise ValueError("Verify(stop_on_unchanged_state=True) requires a fingerprint")
        self.max_attempts = max_attempts
        self.stop_on_unchanged_state = stop_on_unchanged_state
        self.fingerprint = coerce_fingerprint(fingerprint) if fingerprint is not None else None
        self.stop_on_unverified = bool(stop_on_unverified)
        self.name: str = name or "verify"
        self.description: Optional[str] = None
        self.on_fail = on_fail
        # The absorbed loop-back segment, filled by resolve_verify_steps. A pure gate has
        # no segment and needs no resolution.
        self.steps: List[Any] = []
        self._resolved: bool = on_fail is None
        # The owning Workflow, when known; handed to the checks as their owner.
        self._workflow: Optional[Any] = None

    def __deepcopy__(self, memo: Dict[int, Any]) -> "Verify":
        # A deep copy is a fresh mount: the owning workflow re-binds it at its next prepare
        cls = self.__class__
        new = cls.__new__(cls)
        memo[id(self)] = new
        for key, value in self.__dict__.items():
            if key == "_workflow":
                new._workflow = None
            else:
                setattr(new, key, copy.deepcopy(value, memo))
        return new

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "Verify",
            "name": self.name,
            "description": self.description,
            # Per-check policy rides along with the name so an advisory or flaky-tolerant
            # check does not come back as a plain required one. run_condition is a callable and
            # never serializes.
            "verifiers": [verifier_to_dict(v) for v in self._verifiers],
            "on_fail": self.on_fail,
            "max_attempts": self.max_attempts,
            "stop_on_unchanged_state": self.stop_on_unchanged_state,
            "stop_on_unverified": self.stop_on_unverified,
            "resolved": self._resolved,
            "steps": [step.to_dict() for step in self.steps if hasattr(step, "to_dict")],
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        registry: Optional["Registry"] = None,
        db: Optional[Any] = None,
        links: Optional[List[Dict[str, Any]]] = None,
        strict: bool = False,
        branch_suffix: str = "",
    ) -> "Verify":
        """Rebuild a Verify from its serialized form.

        Check callables come back through the registry by name; the serialized per-check
        policy (required/max_retries/stop_on_failure) is re-applied to each rehydrated wrapper. A
        ``run_condition`` predicate is a callable and does not round-trip: a restored check
        runs on every attempt. A ShellVerifier rebuilds from its serialized command.
        ``stop_on_unchanged_state`` degrades to False with a warning when the fingerprint cannot be
        restored, because unchanged-state detection without a fingerprint would silently never fire.
        """
        from agno.workflow.condition import Condition
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.router import Router
        from agno.workflow.step import Step
        from agno.workflow.steps import Steps

        def deserialize_step(step_data: Dict[str, Any]) -> Any:
            step_type = step_data.get("type", "Step")
            if step_type == "Loop":
                return Loop.from_dict(
                    step_data, registry=registry, db=db, links=links, strict=strict, branch_suffix=branch_suffix
                )
            elif step_type == "Parallel":
                return Parallel.from_dict(
                    step_data, registry=registry, db=db, links=links, strict=strict, branch_suffix=branch_suffix
                )
            elif step_type == "Steps":
                return Steps.from_dict(
                    step_data, registry=registry, db=db, links=links, strict=strict, branch_suffix=branch_suffix
                )
            elif step_type == "Condition":
                return Condition.from_dict(
                    step_data, registry=registry, db=db, links=links, strict=strict, branch_suffix=branch_suffix
                )
            elif step_type == "Router":
                return Router.from_dict(
                    step_data, registry=registry, db=db, links=links, strict=strict, branch_suffix=branch_suffix
                )
            elif step_type == "Verify":
                return cls.from_dict(
                    step_data, registry=registry, db=db, links=links, strict=strict, branch_suffix=branch_suffix
                )
            else:
                return Step.from_dict(
                    step_data, registry=registry, db=db, links=links, strict=strict, branch_suffix=branch_suffix
                )

        # Verifier callables never serialize; only registry-referenced ones come back. A
        # miss degrades to a placeholder whose failure keeps the gate closed rather than
        # silently ungating the workflow.
        entries = verifiers_from_dict(data.get("verifiers"), registry, strict)

        verify = cls(
            entries,
            on_fail=data.get("on_fail", "previous"),
            max_attempts=data.get("max_attempts", 3),
            stop_on_unchanged_state=False,
            fingerprint=None,
            stop_on_unverified=bool(data.get("stop_on_unverified", False)),
            name=data.get("name"),
        )
        if data.get("stop_on_unchanged_state"):
            warn_stop_on_unchanged_state_not_restored("Verify", repr(verify.name))
        verify.description = data.get("description")
        if data.get("resolved"):
            verify.steps = [deserialize_step(step_data) for step_data in data.get("steps") or []]
            verify._resolved = True
        return verify

    def _resolve_target_index(self, preceding: List[Any]) -> int:
        """Index of the loop-back target within the steps that precede this Verify.

        Raises ValueError when the target does not exist among them: a Verify that cannot
        reach its target must fail at build time, before any step runs.
        """
        label = self.name
        if self.on_fail == "previous":
            if not preceding:
                raise ValueError(
                    f"Verify {label!r} has no preceding step to loop back to; pass on_fail=None for a pure gate"
                )
            return len(preceding) - 1
        if isinstance(self.on_fail, int) and not isinstance(self.on_fail, bool):
            if not (0 <= self.on_fail < len(preceding)):
                raise ValueError(
                    f"Verify {label!r} on_fail index {self.on_fail} does not name a step before it "
                    f"({len(preceding)} preceding steps)"
                )
            return self.on_fail
        for index, candidate in enumerate(preceding):
            if getattr(candidate, "name", None) == self.on_fail:
                return index
        raise ValueError(f"Verify {label!r} on_fail step {self.on_fail!r} is not a step before it")

    def _require_resolved(self) -> None:
        if not self._resolved:
            raise UnresolvedVerifyError(
                f"Verify {self.name!r} has an unresolved on_fail target; it must sit in a workflow steps list "
                "after the step it loops back to"
            )

    def _update_step_input_from_outputs(
        self,
        step_input: StepInput,
        step_outputs: Union[StepOutput, List[StepOutput]],
        segment_step_outputs: Optional[Dict[str, StepOutput]] = None,
    ) -> StepInput:
        """Chain one segment step's output into the next step's input, media included."""
        current_images = step_input.images or []
        current_videos = step_input.videos or []
        current_audio = step_input.audio or []

        if isinstance(step_outputs, list):
            all_images = sum([out.images or [] for out in step_outputs], [])
            all_videos = sum([out.videos or [] for out in step_outputs], [])
            all_audio = sum([out.audio or [] for out in step_outputs], [])
            previous_step_content = step_outputs[-1].content if step_outputs else None
        else:
            all_images = step_outputs.images or []
            all_videos = step_outputs.videos or []
            all_audio = step_outputs.audio or []
            previous_step_content = step_outputs.content

        updated_previous_step_outputs: Dict[str, StepOutput] = {}
        if step_input.previous_step_outputs:
            updated_previous_step_outputs.update(step_input.previous_step_outputs)
        # The re-entry evidence is the first segment step's input only; once a segment
        # step has produced this attempt's output, that output must be the newest entry,
        # which is what the next step reads as its previous step.
        updated_previous_step_outputs.pop(self.name, None)
        for name, output in (segment_step_outputs or {}).items():
            updated_previous_step_outputs.pop(name, None)
            updated_previous_step_outputs[name] = output

        return StepInput(
            input=step_input.input,
            previous_step_content=previous_step_content,
            previous_step_outputs=updated_previous_step_outputs,
            additional_data=step_input.additional_data,
            images=current_images + all_images,
            videos=current_videos + all_videos,
            audio=current_audio + all_audio,
        )

    def _target_run_output(
        self,
        attempt_results: List[StepOutput],
        step_input: StepInput,
        workflow_run_response: Optional[WorkflowRunOutput],
    ) -> Any:
        """The object the checks judge: the checked step's executor RunOutput/TeamRunOutput
        when the workflow stored it, else the most content-bearing StepOutput available."""
        last: Optional[StepOutput] = None
        if attempt_results:
            last = attempt_results[-1]
        elif step_input.previous_step_outputs:
            last = list(step_input.previous_step_outputs.values())[-1]
        if last is None:
            return None
        target: Any = last
        # A composite output nests the real work; the deepest nested output is the one
        # whose executor actually produced the content.
        while getattr(target, "steps", None):
            target = target.steps[-1]
        run_id = getattr(target, "step_run_id", None)
        if run_id and workflow_run_response is not None:
            for run in reversed(workflow_run_response.step_executor_runs or []):
                if getattr(run, "run_id", None) == run_id:
                    return run
        return target

    def _new_attempt(
        self, record: Verification, fingerprint: Optional[str], settled: Optional[str]
    ) -> VerificationAttempt:
        attempt = VerificationAttempt(index=len(record.attempts))
        if self.fingerprint is not None:
            attempt.fingerprint = fingerprint
            attempt.compared_against = settled
            attempt.state_unchanged = state_unchanged(settled, fingerprint)
        return attempt

    def _settle_attempt(self, record: Verification, attempt: VerificationAttempt, check_run: VerifierResults) -> bool:
        """Stamp the record after one check pass. Returns True when the segment re-runs."""
        if check_run.fatal_failure:
            # A stop_on_failure check failed: the author declared that retrying cannot fix it,
            # whatever the remaining budget says.
            record.status = VerificationStatus.unverified
            record.stop_reason = VerificationStopReason.fatal
            return False
        if check_run.passed:
            record.status = VerificationStatus.verified
            record.stop_reason = VerificationStopReason.passed
            return False
        if attempt.state_unchanged and self.stop_on_unchanged_state:
            record.status = VerificationStatus.unverified
            record.stop_reason = VerificationStopReason.unchanged_state
            return False
        if not self.steps or len(record.attempts) >= self.max_attempts:
            # A pure gate has a budget of one attempt; either way the budget is spent.
            record.status = VerificationStatus.unverified
            record.stop_reason = VerificationStopReason.exhausted
            return False
        return True

    def _judge(
        self,
        record: Verification,
        attempt: VerificationAttempt,
        attempt_results: List[StepOutput],
        step_input: StepInput,
        workflow_run_response: Optional[WorkflowRunOutput],
        run_context: Optional[RunContext],
        workflow_session: Optional[WorkflowSession],
    ) -> bool:
        """Run the checks over this attempt's output and settle the record. Returns True
        when the segment re-runs."""
        target = self._target_run_output(attempt_results, step_input, workflow_run_response)
        check_run = run_checks(
            self._verifiers,
            run_output=target,
            run_context=run_context,
            owner=self._workflow,
            session=workflow_session,
        )
        attempt.verdicts = check_run.verdicts
        record.attempts.append(attempt)
        return self._settle_attempt(record, attempt, check_run)

    async def _ajudge(
        self,
        record: Verification,
        attempt: VerificationAttempt,
        attempt_results: List[StepOutput],
        step_input: StepInput,
        workflow_run_response: Optional[WorkflowRunOutput],
        run_context: Optional[RunContext],
        workflow_session: Optional[WorkflowSession],
    ) -> bool:
        """Async version of `_judge`."""
        target = self._target_run_output(attempt_results, step_input, workflow_run_response)
        check_run = await arun_checks(
            self._verifiers,
            run_output=target,
            run_context=run_context,
            owner=self._workflow,
            session=workflow_session,
        )
        attempt.verdicts = check_run.verdicts
        record.attempts.append(attempt)
        return self._settle_attempt(record, attempt, check_run)

    def _build_attempt_report(self, record: Verification, attempt: VerificationAttempt) -> str:
        return build_report(
            attempt,
            attempt_number=len(record.attempts),
            total_attempts=self.max_attempts,
            has_fingerprint=self.fingerprint is not None,
            stop_on_unchanged_state=self.stop_on_unchanged_state,
        )

    def _reentry_input(self, step_input: StepInput, attempt_results: List[StepOutput], report: str) -> StepInput:
        """The re-entered segment's input: the original task, the failed attempt's output
        and the evidence report, injected as the newest previous-step output so the
        re-entered step's message carries all three."""
        last = attempt_results[-1] if attempt_results else None
        prior = None
        if last is not None and isinstance(last.content, str) and last.content.strip():
            prior = last.content
        # The re-entered step reads only the newest previous-step output as its message,
        # so the task text must ride along or the attempt would see just its own draft.
        task = step_input.get_input_as_string()
        content = "\n\n".join(part for part in (task, prior, report) if part)

        outputs: Dict[str, StepOutput] = {}
        if step_input.previous_step_outputs:
            outputs.update(step_input.previous_step_outputs)
        for out in attempt_results:
            if out.step_name:
                outputs.pop(out.step_name, None)
                outputs[out.step_name] = out
        # The evidence must be the newest entry: assigning an existing key keeps its old
        # position, and a resumed or looped segment already carries this gate's name.
        outputs.pop(self.name, None)
        outputs[self.name] = StepOutput(
            step_name=self.name,
            step_type=StepType.VERIFY,
            content=content,
            success=False,
        )
        return StepInput(
            input=step_input.input,
            previous_step_content=content,
            previous_step_outputs=outputs,
            additional_data=step_input.additional_data,
            images=step_input.images,
            videos=step_input.videos,
            audio=step_input.audio,
            files=step_input.files,
            workflow_session=step_input.workflow_session,
        )

    def _failed_segment_output(self, step: Any, index: int, error: Exception) -> StepOutput:
        """A failed StepOutput for a segment step that raised, so the gate judges the failure
        instead of the workflow surfacing a crash (segment steps carry on_error=skip)."""
        step_name = getattr(step, "name", None) or f"step_{index + 1}"
        return StepOutput(
            step_name=step_name,
            step_id=getattr(step, "step_id", None),
            step_type=StepType.STEP,
            content=f"Step {step_name} failed: {error}",
            success=False,
            error=str(error),
        )

    def _summary(self, record: Verification) -> str:
        attempts = len(record.attempts)
        if record.passed:
            return f"Verify {self.name}: passed ({attempts} attempts)"
        failing: List[str] = []
        if record.attempts:
            failing = [v.name for v in record.attempts[-1].verdicts if v.gates and v.passed is not True]
        names = ", ".join(failing) or "checks"
        reason = record.stop_reason.value if record.stop_reason is not None else "failed"
        return f"Verify {self.name}: unverified ({reason}) after {attempts} attempts: {names}"

    def _paused_output(
        self,
        step_id: str,
        attempt_outputs: List[List[StepOutput]],
        record: Optional[Verification] = None,
        step_index: Optional[Union[int, tuple]] = None,
        parent_step_id: Optional[str] = None,
    ) -> StepOutput:
        # The record rides the paused output so a resume can restore the budget window and
        # the attempts already concluded; without it a resumed gate would start blind.
        # The current attempt's outputs stay on `steps`, where the resume reads them back.
        # The stream placement rides along so the resumed events sit where the pre-pause ones did.
        return StepOutput(
            step_name=self.name,
            step_id=step_id,
            step_type=StepType.VERIFY,
            content=f"Verify {self.name} paused at inner step",
            steps=list(attempt_outputs[-1]) if attempt_outputs else [],
            previous_attempts=[list(r) for r in attempt_outputs[:-1]] or None,
            is_paused=True,
            verification=record,
            step_index=step_index,
            parent_step_id=parent_step_id,
        )

    def _stopped_output(
        self, step_id: str, record: Verification, attempt_outputs: List[List[StepOutput]]
    ) -> StepOutput:
        # An inner step requested early termination before the checks ran; the record
        # stays pending, so the gate has not verified anything.
        return StepOutput(
            step_name=self.name,
            step_id=step_id,
            step_type=StepType.VERIFY,
            content=f"Verify {self.name} stopped early by an inner step",
            success=False,
            stop=True,
            steps=list(attempt_outputs[-1]) if attempt_outputs else [],
            previous_attempts=[list(r) for r in attempt_outputs[:-1]] or None,
            verification=record,
        )

    def _final_output(
        self,
        step_id: str,
        record: Verification,
        attempt_outputs: List[List[StepOutput]],
        step_input: StepInput,
    ) -> StepOutput:
        passed = record.passed
        last_attempt = attempt_outputs[-1] if attempt_outputs else []
        error: Optional[str] = None
        if last_attempt:
            # Downstream chaining reads the deepest nested output, so only the attempt the
            # checks judged last sits on `steps`; earlier attempts are kept under `previous_attempts`.
            # The summary is display-only.
            content: Any = self._summary(record)
            steps: Optional[List[StepOutput]] = list(last_attempt)
            success = passed and all(result.success for result in last_attempt)
        else:
            steps = None
            success = passed
            # A pure gate has no output of its own: forward the checked content (the deepest
            # nested content after a composite), as a plain Step resolves its own input
            if step_input.previous_step_outputs:
                content = get_deepest_content_from_step_output(list(step_input.previous_step_outputs.values())[-1])
            else:
                content = step_input.previous_step_content
            if not passed:
                # Unverified, the summary is the error; with nothing judged it is the content too
                error = self._summary(record)
                if content is None:
                    content = error
        return StepOutput(
            step_name=self.name,
            step_id=step_id,
            step_type=StepType.VERIFY,
            content=content,
            success=success,
            error=error,
            steps=steps,
            previous_attempts=[list(r) for r in attempt_outputs[:-1]] or None,
            # An unverified end can halt the pipeline outright when the gate was told to;
            # the workflow's ordinary stop propagation skips every downstream step.
            stop=bool(self.stop_on_unverified and not passed),
            verification=record,
        )

    def _event_fields(
        self,
        workflow_run_response: WorkflowRunOutput,
        step_id: str,
        step_index: Optional[Union[int, tuple]],
        parent_step_id: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "run_id": workflow_run_response.run_id or "",
            "workflow_name": workflow_run_response.workflow_name or "",
            "workflow_id": workflow_run_response.workflow_id or "",
            "session_id": workflow_run_response.session_id or "",
            "step_name": self.name,
            "step_index": step_index,
            "step_id": step_id,
            "parent_step_id": parent_step_id,
        }

    def _started_event(self, fields: Dict[str, Any]) -> VerifyExecutionStartedEvent:
        return VerifyExecutionStartedEvent(max_attempts=self.max_attempts, **fields)

    def _attempt_started_event(self, fields: Dict[str, Any], attempt: int) -> VerifyAttemptStartedEvent:
        return VerifyAttemptStartedEvent(attempt=attempt, max_attempts=self.max_attempts, **fields)

    def _attempt_completed_event(
        self, fields: Dict[str, Any], record: Verification, should_continue: bool
    ) -> VerifyAttemptCompletedEvent:
        return VerifyAttemptCompletedEvent(
            attempt=len(record.attempts),
            max_attempts=self.max_attempts,
            passed=record.passed,
            should_continue=should_continue,
            verification=record.to_dict(),
            **fields,
        )

    def _completed_event(self, fields: Dict[str, Any], record: Verification) -> VerifyExecutionCompletedEvent:
        return VerifyExecutionCompletedEvent(
            total_attempts=len(record.attempts),
            max_attempts=self.max_attempts,
            status=record.status.value,
            stop_reason=record.stop_reason.value if record.stop_reason is not None else None,
            verification=record.to_dict(),
            **fields,
        )

    def execute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        store_executor_outputs: bool = True,
        workflow_media_storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        _resume_record: Optional[Verification] = None,
        _resume_history: Optional[List[List[StepOutput]]] = None,
        _resume_step_id: Optional[str] = None,
    ) -> StepOutput:
        """Execute the verification loop: run the segment (if any), run the checks, and
        either finish or re-enter the segment with the evidence report.

        The underscore parameters seed a loop resumed after a HITL pause: the record with
        its concluded attempts and the outputs of the attempts already produced.
        """
        log_debug(f"Verify Start: {self.name}", center=True, symbol="=")
        self._require_resolved()
        require_sync_verifiers(self._verifiers, self.fingerprint)

        step_id = _resume_step_id or str(uuid4())
        record = _resume_record if _resume_record is not None else Verification()
        settled = safe_capture(self.fingerprint) if self.fingerprint is not None else None
        record.baseline_fingerprint = settled
        attempt_outputs: List[List[StepOutput]] = [list(r) for r in (_resume_history or [])]
        current_input = step_input

        while True:
            if workflow_run_response and workflow_run_response.run_id:
                raise_if_cancelled(workflow_run_response.run_id)

            attempt_results: List[StepOutput] = []
            attempt_outputs.append(attempt_results)
            stop_requested = False
            segment_input = current_input
            segment_outputs: Dict[str, StepOutput] = {}
            for i, step in enumerate(self.steps):
                try:
                    step_output = step.execute(
                        segment_input,
                        session_id=session_id,
                        user_id=user_id,
                        workflow_run_response=workflow_run_response,
                        store_executor_outputs=store_executor_outputs,
                        workflow_media_storage=workflow_media_storage,
                        run_context=run_context,
                        session_state=session_state,
                        workflow_session=workflow_session,
                        add_workflow_history_to_steps=add_workflow_history_to_steps,
                        num_history_runs=num_history_runs,
                        background_tasks=background_tasks,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                    )
                except RunCancelledException:
                    raise
                except UnresolvableCallableError:
                    raise
                except Exception as e:
                    step_output = self._failed_segment_output(step, i, e)
                outputs = step_output if isinstance(step_output, list) else [step_output]
                attempt_results.extend(outputs)
                if outputs and getattr(outputs[-1], "is_paused", False):
                    return self._paused_output(step_id, attempt_outputs, record=record)
                if outputs:
                    step_name = getattr(step, "name", None) or f"step_{i + 1}"
                    segment_outputs[step_name] = outputs[-1]
                    if any(output.stop for output in outputs):
                        stop_requested = True
                        break
                    segment_input = self._update_step_input_from_outputs(segment_input, step_output, segment_outputs)
            if stop_requested:
                return self._stopped_output(step_id, record, attempt_outputs)

            fingerprint = safe_capture(self.fingerprint) if self.fingerprint is not None else None
            attempt = self._new_attempt(record, fingerprint, settled)
            reenter = self._judge(
                record,
                attempt,
                attempt_results,
                step_input,
                workflow_run_response,
                run_context,
                workflow_session,
            )
            if not reenter:
                break
            if self.fingerprint is not None:
                # Settle after the checks, and only when the segment re-runs: a check's
                # own artifacts must not be charged to the next attempt as the segment's
                # work, and a terminal attempt needs no further baseline.
                settled = safe_capture(self.fingerprint)
                record.baseline_fingerprint = settled
            log_debug(
                f"Verify {self.name}: re-entering segment (attempt {len(record.attempts) + 1}/{self.max_attempts})"
            )
            report = self._build_attempt_report(record, attempt)
            current_input = self._reentry_input(step_input, attempt_results, report)

        log_debug(f"Verify End: {self.name} ({len(record.attempts)} attempts)", center=True, symbol="=")
        return self._final_output(step_id, record, attempt_outputs, step_input)

    def execute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_events: bool = False,
        stream_executor_events: bool = True,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        step_index: Optional[Union[int, tuple]] = None,
        store_executor_outputs: bool = True,
        workflow_media_storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        parent_step_id: Optional[str] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        _resume_record: Optional[Verification] = None,
        _resume_history: Optional[List[List[StepOutput]]] = None,
        _resume_step_id: Optional[str] = None,
    ) -> Iterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Streaming version of `execute`: inner step events pass through; only the composite
        StepOutput is yielded as this step's result."""
        log_debug(f"Verify Start: {self.name}", center=True, symbol="=")
        self._require_resolved()
        require_sync_verifiers(self._verifiers, self.fingerprint)

        step_id = _resume_step_id or str(uuid4())
        record = _resume_record if _resume_record is not None else Verification()
        settled = safe_capture(self.fingerprint) if self.fingerprint is not None else None
        record.baseline_fingerprint = settled
        attempt_outputs: List[List[StepOutput]] = [list(r) for r in (_resume_history or [])]
        current_input = step_input
        emit = bool(stream_events and workflow_run_response)
        fields = (
            self._event_fields(workflow_run_response, step_id, step_index, parent_step_id)
            if workflow_run_response
            else {}
        )
        if emit and _resume_record is None:
            yield self._started_event(fields)

        while True:
            if workflow_run_response and workflow_run_response.run_id:
                raise_if_cancelled(workflow_run_response.run_id)
            if emit:
                yield self._attempt_started_event(fields, len(record.attempts) + 1)

            attempt_results: List[StepOutput] = []
            attempt_outputs.append(attempt_results)
            stop_requested = False
            segment_input = current_input
            segment_outputs: Dict[str, StepOutput] = {}
            for i, step in enumerate(self.steps):
                if step_index is None or isinstance(step_index, int):
                    composite_step_index: Union[int, tuple] = (step_index if step_index is not None else 0, i)
                else:
                    composite_step_index = step_index + (i,)

                step_outputs_for_step: List[StepOutput] = []
                try:
                    for event in step.execute_stream(
                        segment_input,
                        session_id=session_id,
                        user_id=user_id,
                        stream_events=stream_events,
                        stream_executor_events=stream_executor_events,
                        workflow_run_response=workflow_run_response,
                        step_index=composite_step_index,
                        store_executor_outputs=store_executor_outputs,
                        workflow_media_storage=workflow_media_storage,
                        run_context=run_context,
                        session_state=session_state,
                        parent_step_id=step_id,
                        workflow_session=workflow_session,
                        add_workflow_history_to_steps=add_workflow_history_to_steps,
                        num_history_runs=num_history_runs,
                        background_tasks=background_tasks,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                    ):
                        if isinstance(event, StepOutput):
                            step_outputs_for_step.append(event)
                            attempt_results.append(event)
                        else:
                            yield event
                except RunCancelledException:
                    raise
                except UnresolvableCallableError:
                    raise
                except Exception as e:
                    failed = self._failed_segment_output(step, i, e)
                    step_outputs_for_step.append(failed)
                    attempt_results.append(failed)

                if step_outputs_for_step and getattr(step_outputs_for_step[-1], "is_paused", False):
                    yield self._paused_output(
                        step_id, attempt_outputs, record=record, step_index=step_index, parent_step_id=parent_step_id
                    )
                    return
                if step_outputs_for_step:
                    step_name = getattr(step, "name", None) or f"step_{i + 1}"
                    segment_outputs[step_name] = step_outputs_for_step[-1]
                    if any(output.stop for output in step_outputs_for_step):
                        stop_requested = True
                        break
                    chained = step_outputs_for_step[0] if len(step_outputs_for_step) == 1 else step_outputs_for_step
                    segment_input = self._update_step_input_from_outputs(segment_input, chained, segment_outputs)
            if stop_requested:
                yield self._stopped_output(step_id, record, attempt_outputs)
                return

            fingerprint = safe_capture(self.fingerprint) if self.fingerprint is not None else None
            attempt = self._new_attempt(record, fingerprint, settled)
            reenter = self._judge(
                record,
                attempt,
                attempt_results,
                step_input,
                workflow_run_response,
                run_context,
                workflow_session,
            )
            if emit:
                yield self._attempt_completed_event(fields, record, reenter)
            if not reenter:
                break
            if self.fingerprint is not None:
                # Settled only on re-entry: a terminal attempt needs no further baseline.
                settled = safe_capture(self.fingerprint)
                record.baseline_fingerprint = settled
            log_debug(
                f"Verify {self.name}: re-entering segment (attempt {len(record.attempts) + 1}/{self.max_attempts})"
            )
            report = self._build_attempt_report(record, attempt)
            current_input = self._reentry_input(step_input, attempt_results, report)

        log_debug(f"Verify End: {self.name} ({len(record.attempts)} attempts)", center=True, symbol="=")
        if emit:
            yield self._completed_event(fields, record)
        yield self._final_output(step_id, record, attempt_outputs, step_input)

    async def aexecute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        store_executor_outputs: bool = True,
        workflow_media_storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        _resume_record: Optional[Verification] = None,
        _resume_history: Optional[List[List[StepOutput]]] = None,
        _resume_step_id: Optional[str] = None,
    ) -> StepOutput:
        """Async version of `execute`."""
        log_debug(f"Verify Start: {self.name}", center=True, symbol="=")
        self._require_resolved()

        step_id = _resume_step_id or str(uuid4())
        record = _resume_record if _resume_record is not None else Verification()
        settled = await asafe_capture(self.fingerprint) if self.fingerprint is not None else None
        record.baseline_fingerprint = settled
        attempt_outputs: List[List[StepOutput]] = [list(r) for r in (_resume_history or [])]
        current_input = step_input

        while True:
            if workflow_run_response and workflow_run_response.run_id:
                await araise_if_cancelled(workflow_run_response.run_id)

            attempt_results: List[StepOutput] = []
            attempt_outputs.append(attempt_results)
            stop_requested = False
            segment_input = current_input
            segment_outputs: Dict[str, StepOutput] = {}
            for i, step in enumerate(self.steps):
                try:
                    step_output = await step.aexecute(
                        segment_input,
                        session_id=session_id,
                        user_id=user_id,
                        workflow_run_response=workflow_run_response,
                        store_executor_outputs=store_executor_outputs,
                        workflow_media_storage=workflow_media_storage,
                        run_context=run_context,
                        session_state=session_state,
                        workflow_session=workflow_session,
                        add_workflow_history_to_steps=add_workflow_history_to_steps,
                        num_history_runs=num_history_runs,
                        background_tasks=background_tasks,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                    )
                except RunCancelledException:
                    raise
                except UnresolvableCallableError:
                    raise
                except Exception as e:
                    step_output = self._failed_segment_output(step, i, e)
                outputs = step_output if isinstance(step_output, list) else [step_output]
                attempt_results.extend(outputs)
                if outputs and getattr(outputs[-1], "is_paused", False):
                    return self._paused_output(step_id, attempt_outputs, record=record)
                if outputs:
                    step_name = getattr(step, "name", None) or f"step_{i + 1}"
                    segment_outputs[step_name] = outputs[-1]
                    if any(output.stop for output in outputs):
                        stop_requested = True
                        break
                    segment_input = self._update_step_input_from_outputs(segment_input, step_output, segment_outputs)
            if stop_requested:
                return self._stopped_output(step_id, record, attempt_outputs)

            fingerprint = await asafe_capture(self.fingerprint) if self.fingerprint is not None else None
            attempt = self._new_attempt(record, fingerprint, settled)
            reenter = await self._ajudge(
                record,
                attempt,
                attempt_results,
                step_input,
                workflow_run_response,
                run_context,
                workflow_session,
            )
            if not reenter:
                break
            if self.fingerprint is not None:
                # Settled only on re-entry: a terminal attempt needs no further baseline.
                settled = await asafe_capture(self.fingerprint)
                record.baseline_fingerprint = settled
            log_debug(
                f"Verify {self.name}: re-entering segment (attempt {len(record.attempts) + 1}/{self.max_attempts})"
            )
            report = self._build_attempt_report(record, attempt)
            current_input = self._reentry_input(step_input, attempt_results, report)

        log_debug(f"Verify End: {self.name} ({len(record.attempts)} attempts)", center=True, symbol="=")
        return self._final_output(step_id, record, attempt_outputs, step_input)

    async def aexecute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_events: bool = False,
        stream_executor_events: bool = True,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        step_index: Optional[Union[int, tuple]] = None,
        store_executor_outputs: bool = True,
        workflow_media_storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        parent_step_id: Optional[str] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        _resume_record: Optional[Verification] = None,
        _resume_history: Optional[List[List[StepOutput]]] = None,
        _resume_step_id: Optional[str] = None,
    ) -> AsyncIterator[Union[WorkflowRunOutputEvent, TeamRunOutputEvent, RunOutputEvent, StepOutput]]:
        """Async streaming version of `execute`."""
        log_debug(f"Verify Start: {self.name}", center=True, symbol="=")
        self._require_resolved()

        step_id = _resume_step_id or str(uuid4())
        record = _resume_record if _resume_record is not None else Verification()
        settled = await asafe_capture(self.fingerprint) if self.fingerprint is not None else None
        record.baseline_fingerprint = settled
        attempt_outputs: List[List[StepOutput]] = [list(r) for r in (_resume_history or [])]
        current_input = step_input
        emit = bool(stream_events and workflow_run_response)
        fields = (
            self._event_fields(workflow_run_response, step_id, step_index, parent_step_id)
            if workflow_run_response
            else {}
        )
        if emit and _resume_record is None:
            yield self._started_event(fields)

        while True:
            if workflow_run_response and workflow_run_response.run_id:
                await araise_if_cancelled(workflow_run_response.run_id)
            if emit:
                yield self._attempt_started_event(fields, len(record.attempts) + 1)

            attempt_results: List[StepOutput] = []
            attempt_outputs.append(attempt_results)
            stop_requested = False
            segment_input = current_input
            segment_outputs: Dict[str, StepOutput] = {}
            for i, step in enumerate(self.steps):
                if step_index is None or isinstance(step_index, int):
                    composite_step_index: Union[int, tuple] = (step_index if step_index is not None else 0, i)
                else:
                    composite_step_index = step_index + (i,)

                step_outputs_for_step: List[StepOutput] = []
                try:
                    async for event in step.aexecute_stream(
                        segment_input,
                        session_id=session_id,
                        user_id=user_id,
                        stream_events=stream_events,
                        stream_executor_events=stream_executor_events,
                        workflow_run_response=workflow_run_response,
                        step_index=composite_step_index,
                        store_executor_outputs=store_executor_outputs,
                        workflow_media_storage=workflow_media_storage,
                        run_context=run_context,
                        session_state=session_state,
                        parent_step_id=step_id,
                        workflow_session=workflow_session,
                        add_workflow_history_to_steps=add_workflow_history_to_steps,
                        num_history_runs=num_history_runs,
                        background_tasks=background_tasks,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                    ):
                        if isinstance(event, StepOutput):
                            step_outputs_for_step.append(event)
                            attempt_results.append(event)
                        else:
                            yield event
                except RunCancelledException:
                    raise
                except UnresolvableCallableError:
                    raise
                except Exception as e:
                    failed = self._failed_segment_output(step, i, e)
                    step_outputs_for_step.append(failed)
                    attempt_results.append(failed)

                if step_outputs_for_step and getattr(step_outputs_for_step[-1], "is_paused", False):
                    yield self._paused_output(
                        step_id, attempt_outputs, record=record, step_index=step_index, parent_step_id=parent_step_id
                    )
                    return
                if step_outputs_for_step:
                    step_name = getattr(step, "name", None) or f"step_{i + 1}"
                    segment_outputs[step_name] = step_outputs_for_step[-1]
                    if any(output.stop for output in step_outputs_for_step):
                        stop_requested = True
                        break
                    chained = step_outputs_for_step[0] if len(step_outputs_for_step) == 1 else step_outputs_for_step
                    segment_input = self._update_step_input_from_outputs(segment_input, chained, segment_outputs)
            if stop_requested:
                yield self._stopped_output(step_id, record, attempt_outputs)
                return

            fingerprint = await asafe_capture(self.fingerprint) if self.fingerprint is not None else None
            attempt = self._new_attempt(record, fingerprint, settled)
            reenter = await self._ajudge(
                record,
                attempt,
                attempt_results,
                step_input,
                workflow_run_response,
                run_context,
                workflow_session,
            )
            if emit:
                yield self._attempt_completed_event(fields, record, reenter)
            if not reenter:
                break
            if self.fingerprint is not None:
                # Settled only on re-entry: a terminal attempt needs no further baseline.
                settled = await asafe_capture(self.fingerprint)
                record.baseline_fingerprint = settled
            log_debug(
                f"Verify {self.name}: re-entering segment (attempt {len(record.attempts) + 1}/{self.max_attempts})"
            )
            report = self._build_attempt_report(record, attempt)
            current_input = self._reentry_input(step_input, attempt_results, report)

        log_debug(f"Verify End: {self.name} ({len(record.attempts)} attempts)", center=True, symbol="=")
        if emit:
            yield self._completed_event(fields, record)
        yield self._final_output(step_id, record, attempt_outputs, step_input)

    def _find_paused_self(self, workflow_run_response: Optional[WorkflowRunOutput]) -> Optional[StepOutput]:
        """The paused composite output this gate produced, from the persisted run. A gate
        nested in a container (Steps, Condition, Loop iterations) pauses inside the
        container's wrapper output, so the search walks nested step results, newest first.
        When none is found the resume starts a fresh record - the checks still run, which is
        the fail-closed direction."""
        results = getattr(workflow_run_response, "step_results", None) or []
        self_id = getattr(self, "step_id", None)

        def matches(output: Any) -> bool:
            if not getattr(output, "is_paused", False):
                return False
            if getattr(output, "step_type", None) not in (
                StepType.VERIFY,
                "Verify",
                getattr(StepType.VERIFY, "value", None),
            ):
                return False
            output_id = getattr(output, "step_id", None)
            # Exact step identity outranks the name where both sides carry one; a Verify has
            # no step id of its own, so the name is what it is matched by.
            if self_id and output_id:
                return output_id == self_id
            return getattr(output, "step_name", None) == self.name

        def walk(outputs: Any) -> Optional[StepOutput]:
            for output in reversed(list(outputs)):
                if matches(output):
                    return output
                nested = getattr(output, "steps", None)
                if nested:
                    found = walk(nested)
                    if found is not None:
                        return found
            return None

        return walk(results)

    def _segment_index_for(self, step_req: Any, continued_output: StepOutput) -> int:
        """Which absorbed segment step the resumed executor belongs to. Exact step identity
        outranks executor identity: one agent may be reused across several segment steps."""
        if step_req is not None:
            from agno.workflow.workflow import find_inner_step_by_executor

            inner = find_inner_step_by_executor(
                self,
                executor_id=getattr(step_req, "executor_id", None),
                executor_name=getattr(step_req, "executor_name", None),
                step_id=getattr(step_req, "step_id", None),
            )
            if inner is not None:
                for index, step in enumerate(self.steps):
                    if step is inner:
                        return index
        name = getattr(continued_output, "step_name", None)
        if name:
            for index, step in enumerate(self.steps):
                if getattr(step, "name", None) == name:
                    return index
        return len(self.steps) - 1 if self.steps else 0

    @staticmethod
    def _resume_identity(
        state: Dict[str, Any], step_index: Optional[Union[int, tuple]], parent_step_id: Optional[str]
    ) -> Tuple[str, Optional[Union[int, tuple]], Optional[str]]:
        """The gate's step_id and stream placement for a resume: the paused placeholder's own,
        so events after the pause sit where the ones before it did; the seam's values otherwise."""
        paused = state.get("paused")
        if paused is None:
            return str(uuid4()), step_index, parent_step_id
        return (
            paused.step_id or str(uuid4()),
            paused.step_index if paused.step_index is not None else step_index,
            paused.parent_step_id if paused.parent_step_id is not None else parent_step_id,
        )

    def _resume_state(
        self,
        continued_output: StepOutput,
        step_req: Any,
        step_input: StepInput,
        workflow_run_response: Optional[WorkflowRunOutput],
        run_context: Optional[RunContext],
    ) -> Dict[str, Any]:
        """Everything a resume leg needs from the persisted pause: the record, the earlier
        attempts' outputs, the paused attempt's outputs up to the resumed step, and the index to continue from."""
        paused = self._find_paused_self(workflow_run_response)
        paused_record = getattr(paused, "verification", None) if paused is not None else None
        record: Verification = paused_record if isinstance(paused_record, Verification) else Verification()
        history: List[List[StepOutput]] = [list(r) for r in (getattr(paused, "previous_attempts", None) or [])]
        prior_results: List[StepOutput] = list(getattr(paused, "steps", None) or [])
        # The continued output takes the paused placeholder's place, so a later pause does
        # not carry the stale placeholder forward.
        if prior_results and getattr(prior_results[-1], "is_paused", False):
            prior_results.pop()
        resume_index = self._segment_index_for(step_req, continued_output)

        segment_outputs: Dict[str, StepOutput] = {o.step_name: o for o in prior_results if o.step_name}
        resumed_name = (
            continued_output.step_name
            or (getattr(self.steps[resume_index], "name", None) if self.steps else None)
            or f"step_{resume_index + 1}"
        )
        segment_outputs[resumed_name] = continued_output
        return {
            "paused": paused,
            "record": record,
            "history": history,
            "attempt_results": prior_results + [continued_output],
            "segment_outputs": segment_outputs,
            "segment_input": self._update_step_input_from_outputs(step_input, continued_output, segment_outputs),
            "resume_index": resume_index,
            "session_id": getattr(workflow_run_response, "session_id", None),
            "user_id": getattr(run_context, "user_id", None),
            "session_state": getattr(run_context, "session_state", None),
        }

    def continue_from_paused(
        self,
        continued_output: StepOutput,
        step_req: Any = None,
        step_input: Optional[StepInput] = None,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        workflow_session: Optional[WorkflowSession] = None,
        run_context: Optional[RunContext] = None,
        store_executor_outputs: bool = True,
        workflow_media_storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> StepOutput:
        """Finish this gate's job after an inner executor resumed from a HITL pause.

        The workflow's resume seam continues only the paused executor; handed its output,
        this runs the rest of the absorbed segment, then the checks, and loops attempts as
        normal - so a pause can never carry a run past the gate unverified. The record
        resumes from the paused composite output (budget window intact), and the resumed
        attempt is compared against the fingerprint baseline stored on it before the pause.
        """
        self._require_resolved()
        require_sync_verifiers(self._verifiers, self.fingerprint)
        step_input = step_input if step_input is not None else StepInput(input=None)
        state = self._resume_state(continued_output, step_req, step_input, workflow_run_response, run_context)
        record: Verification = state["record"]
        attempt_results: List[StepOutput] = state["attempt_results"]
        attempt_outputs: List[List[StepOutput]] = state["history"] + [attempt_results]
        segment_outputs: Dict[str, StepOutput] = state["segment_outputs"]
        seg_input: StepInput = state["segment_input"]
        step_id, step_index, parent_step_id = self._resume_identity(state, None, None)
        if getattr(continued_output, "is_paused", False):
            # The executor paused again: the gate re-wraps the pause with its record so
            # the next resume finds the same budget window.
            return self._paused_output(
                step_id, attempt_outputs, record=record, step_index=step_index, parent_step_id=parent_step_id
            )

        for index in range(state["resume_index"] + 1, len(self.steps)):
            step = self.steps[index]
            try:
                step_output = step.execute(
                    seg_input,
                    session_id=state["session_id"],
                    user_id=state["user_id"],
                    workflow_run_response=workflow_run_response,
                    store_executor_outputs=store_executor_outputs,
                    workflow_media_storage=workflow_media_storage,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    run_context=run_context,
                    session_state=state["session_state"],
                    workflow_session=workflow_session,
                    background_tasks=background_tasks,
                )
            except RunCancelledException:
                raise
            except UnresolvableCallableError:
                raise
            except Exception as e:
                step_output = self._failed_segment_output(step, index, e)
            outputs = step_output if isinstance(step_output, list) else [step_output]
            attempt_results.extend(outputs)
            if outputs and getattr(outputs[-1], "is_paused", False):
                return self._paused_output(
                    step_id, attempt_outputs, record=record, step_index=step_index, parent_step_id=parent_step_id
                )
            if outputs:
                step_name = getattr(step, "name", None) or f"step_{index + 1}"
                segment_outputs[step_name] = outputs[-1]
                if any(output.stop for output in outputs):
                    return self._stopped_output(step_id, record, attempt_outputs)
                seg_input = self._update_step_input_from_outputs(seg_input, step_output, segment_outputs)

        fingerprint = safe_capture(self.fingerprint) if self.fingerprint is not None else None
        attempt = self._new_attempt(record, fingerprint, record.baseline_fingerprint)
        reenter = self._judge(
            record,
            attempt,
            attempt_results,
            step_input,
            workflow_run_response,
            run_context,
            workflow_session,
        )
        if not reenter:
            log_debug(f"Verify End (resumed): {self.name} ({len(record.attempts)} attempts)", center=True, symbol="=")
            return self._final_output(step_id, record, attempt_outputs, step_input)

        report = self._build_attempt_report(record, attempt)
        reentry = self._reentry_input(step_input, attempt_results, report)
        return self.execute(
            reentry,
            session_id=state["session_id"],
            user_id=state["user_id"],
            workflow_run_response=workflow_run_response,
            store_executor_outputs=store_executor_outputs,
            workflow_media_storage=workflow_media_storage,
            add_workflow_history_to_steps=add_workflow_history_to_steps,
            num_history_runs=num_history_runs,
            run_context=run_context,
            session_state=state["session_state"],
            workflow_session=workflow_session,
            background_tasks=background_tasks,
            _resume_record=record,
            _resume_history=attempt_outputs,
            _resume_step_id=step_id,
        )

    async def acontinue_from_paused(
        self,
        continued_output: StepOutput,
        step_req: Any = None,
        step_input: Optional[StepInput] = None,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        workflow_session: Optional[WorkflowSession] = None,
        run_context: Optional[RunContext] = None,
        store_executor_outputs: bool = True,
        workflow_media_storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> StepOutput:
        """Async version of `continue_from_paused`."""
        self._require_resolved()
        step_input = step_input if step_input is not None else StepInput(input=None)
        state = self._resume_state(continued_output, step_req, step_input, workflow_run_response, run_context)
        record: Verification = state["record"]
        attempt_results: List[StepOutput] = state["attempt_results"]
        attempt_outputs: List[List[StepOutput]] = state["history"] + [attempt_results]
        segment_outputs: Dict[str, StepOutput] = state["segment_outputs"]
        seg_input: StepInput = state["segment_input"]
        step_id, step_index, parent_step_id = self._resume_identity(state, None, None)
        if getattr(continued_output, "is_paused", False):
            # The executor paused again: the gate re-wraps the pause with its record so
            # the next resume finds the same budget window.
            return self._paused_output(
                step_id, attempt_outputs, record=record, step_index=step_index, parent_step_id=parent_step_id
            )

        for index in range(state["resume_index"] + 1, len(self.steps)):
            step = self.steps[index]
            try:
                step_output = await step.aexecute(
                    seg_input,
                    session_id=state["session_id"],
                    user_id=state["user_id"],
                    workflow_run_response=workflow_run_response,
                    store_executor_outputs=store_executor_outputs,
                    workflow_media_storage=workflow_media_storage,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    run_context=run_context,
                    session_state=state["session_state"],
                    workflow_session=workflow_session,
                    background_tasks=background_tasks,
                )
            except RunCancelledException:
                raise
            except UnresolvableCallableError:
                raise
            except Exception as e:
                step_output = self._failed_segment_output(step, index, e)
            outputs = step_output if isinstance(step_output, list) else [step_output]
            attempt_results.extend(outputs)
            if outputs and getattr(outputs[-1], "is_paused", False):
                return self._paused_output(
                    step_id, attempt_outputs, record=record, step_index=step_index, parent_step_id=parent_step_id
                )
            if outputs:
                step_name = getattr(step, "name", None) or f"step_{index + 1}"
                segment_outputs[step_name] = outputs[-1]
                if any(output.stop for output in outputs):
                    return self._stopped_output(step_id, record, attempt_outputs)
                seg_input = self._update_step_input_from_outputs(seg_input, step_output, segment_outputs)

        fingerprint = await asafe_capture(self.fingerprint) if self.fingerprint is not None else None
        attempt = self._new_attempt(record, fingerprint, record.baseline_fingerprint)
        reenter = await self._ajudge(
            record,
            attempt,
            attempt_results,
            step_input,
            workflow_run_response,
            run_context,
            workflow_session,
        )
        if not reenter:
            log_debug(f"Verify End (resumed): {self.name} ({len(record.attempts)} attempts)", center=True, symbol="=")
            return self._final_output(step_id, record, attempt_outputs, step_input)

        report = self._build_attempt_report(record, attempt)
        reentry = self._reentry_input(step_input, attempt_results, report)
        return await self.aexecute(
            reentry,
            session_id=state["session_id"],
            user_id=state["user_id"],
            workflow_run_response=workflow_run_response,
            store_executor_outputs=store_executor_outputs,
            workflow_media_storage=workflow_media_storage,
            add_workflow_history_to_steps=add_workflow_history_to_steps,
            num_history_runs=num_history_runs,
            run_context=run_context,
            session_state=state["session_state"],
            workflow_session=workflow_session,
            background_tasks=background_tasks,
            _resume_record=record,
            _resume_history=attempt_outputs,
            _resume_step_id=step_id,
        )

    def continue_from_paused_stream(
        self,
        continued_output: StepOutput,
        step_req: Any = None,
        step_input: Optional[StepInput] = None,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        workflow_session: Optional[WorkflowSession] = None,
        run_context: Optional[RunContext] = None,
        store_executor_outputs: bool = True,
        workflow_media_storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
        stream_events: bool = False,
        stream_executor_events: bool = True,
        step_index: Optional[Union[int, tuple]] = None,
        parent_step_id: Optional[str] = None,
    ) -> Iterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Streaming version of `continue_from_paused`: inner step events pass through and the
        attempt's Verify events are emitted, so a resumed stream reads like a fresh one."""
        self._require_resolved()
        require_sync_verifiers(self._verifiers, self.fingerprint)
        step_input = step_input if step_input is not None else StepInput(input=None)
        state = self._resume_state(continued_output, step_req, step_input, workflow_run_response, run_context)
        record: Verification = state["record"]
        attempt_results: List[StepOutput] = state["attempt_results"]
        attempt_outputs: List[List[StepOutput]] = state["history"] + [attempt_results]
        segment_outputs: Dict[str, StepOutput] = state["segment_outputs"]
        seg_input: StepInput = state["segment_input"]
        step_id, step_index, parent_step_id = self._resume_identity(state, step_index, parent_step_id)
        emit = bool(stream_events and workflow_run_response)
        fields = (
            self._event_fields(workflow_run_response, step_id, step_index, parent_step_id)
            if workflow_run_response
            else {}
        )
        if getattr(continued_output, "is_paused", False):
            yield self._paused_output(
                step_id, attempt_outputs, record=record, step_index=step_index, parent_step_id=parent_step_id
            )
            return

        for index in range(state["resume_index"] + 1, len(self.steps)):
            step = self.steps[index]
            if step_index is None or isinstance(step_index, int):
                composite_step_index: Union[int, tuple] = (step_index if step_index is not None else 0, index)
            else:
                composite_step_index = step_index + (index,)
            step_outputs_for_step: List[StepOutput] = []
            try:
                for event in step.execute_stream(
                    seg_input,
                    session_id=state["session_id"],
                    user_id=state["user_id"],
                    stream_events=stream_events,
                    stream_executor_events=stream_executor_events,
                    workflow_run_response=workflow_run_response,
                    step_index=composite_step_index,
                    store_executor_outputs=store_executor_outputs,
                    workflow_media_storage=workflow_media_storage,
                    run_context=run_context,
                    session_state=state["session_state"],
                    parent_step_id=step_id,
                    workflow_session=workflow_session,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    background_tasks=background_tasks,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs_for_step.append(event)
                        attempt_results.append(event)
                    else:
                        yield event
            except RunCancelledException:
                raise
            except UnresolvableCallableError:
                raise
            except Exception as e:
                failed = self._failed_segment_output(step, index, e)
                step_outputs_for_step.append(failed)
                attempt_results.append(failed)
            if step_outputs_for_step and getattr(step_outputs_for_step[-1], "is_paused", False):
                yield self._paused_output(
                    step_id, attempt_outputs, record=record, step_index=step_index, parent_step_id=parent_step_id
                )
                return
            if step_outputs_for_step:
                step_name = getattr(step, "name", None) or f"step_{index + 1}"
                segment_outputs[step_name] = step_outputs_for_step[-1]
                if any(output.stop for output in step_outputs_for_step):
                    yield self._stopped_output(step_id, record, attempt_outputs)
                    return
                chained = step_outputs_for_step[0] if len(step_outputs_for_step) == 1 else step_outputs_for_step
                seg_input = self._update_step_input_from_outputs(seg_input, chained, segment_outputs)

        fingerprint = safe_capture(self.fingerprint) if self.fingerprint is not None else None
        attempt = self._new_attempt(record, fingerprint, record.baseline_fingerprint)
        reenter = self._judge(
            record,
            attempt,
            attempt_results,
            step_input,
            workflow_run_response,
            run_context,
            workflow_session,
        )
        if emit:
            yield self._attempt_completed_event(fields, record, reenter)
        if not reenter:
            log_debug(f"Verify End (resumed): {self.name} ({len(record.attempts)} attempts)", center=True, symbol="=")
            if emit:
                yield self._completed_event(fields, record)
            yield self._final_output(step_id, record, attempt_outputs, step_input)
            return

        report = self._build_attempt_report(record, attempt)
        reentry = self._reentry_input(step_input, attempt_results, report)
        yield from self.execute_stream(
            reentry,
            session_id=state["session_id"],
            user_id=state["user_id"],
            stream_events=stream_events,
            stream_executor_events=stream_executor_events,
            workflow_run_response=workflow_run_response,
            step_index=step_index,
            parent_step_id=parent_step_id,
            store_executor_outputs=store_executor_outputs,
            workflow_media_storage=workflow_media_storage,
            run_context=run_context,
            session_state=state["session_state"],
            workflow_session=workflow_session,
            add_workflow_history_to_steps=add_workflow_history_to_steps,
            num_history_runs=num_history_runs,
            background_tasks=background_tasks,
            _resume_record=record,
            _resume_history=attempt_outputs,
            _resume_step_id=step_id,
        )

    async def acontinue_from_paused_stream(
        self,
        continued_output: StepOutput,
        step_req: Any = None,
        step_input: Optional[StepInput] = None,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        workflow_session: Optional[WorkflowSession] = None,
        run_context: Optional[RunContext] = None,
        store_executor_outputs: bool = True,
        workflow_media_storage: Optional[Union[MediaStorage, AsyncMediaStorage]] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
        stream_events: bool = False,
        stream_executor_events: bool = True,
        step_index: Optional[Union[int, tuple]] = None,
        parent_step_id: Optional[str] = None,
    ) -> AsyncIterator[Union[WorkflowRunOutputEvent, TeamRunOutputEvent, RunOutputEvent, StepOutput]]:
        """Async version of `continue_from_paused_stream`."""
        self._require_resolved()
        step_input = step_input if step_input is not None else StepInput(input=None)
        state = self._resume_state(continued_output, step_req, step_input, workflow_run_response, run_context)
        record: Verification = state["record"]
        attempt_results: List[StepOutput] = state["attempt_results"]
        attempt_outputs: List[List[StepOutput]] = state["history"] + [attempt_results]
        segment_outputs: Dict[str, StepOutput] = state["segment_outputs"]
        seg_input: StepInput = state["segment_input"]
        step_id, step_index, parent_step_id = self._resume_identity(state, step_index, parent_step_id)
        emit = bool(stream_events and workflow_run_response)
        fields = (
            self._event_fields(workflow_run_response, step_id, step_index, parent_step_id)
            if workflow_run_response
            else {}
        )
        if getattr(continued_output, "is_paused", False):
            yield self._paused_output(
                step_id, attempt_outputs, record=record, step_index=step_index, parent_step_id=parent_step_id
            )
            return

        for index in range(state["resume_index"] + 1, len(self.steps)):
            step = self.steps[index]
            if step_index is None or isinstance(step_index, int):
                composite_step_index: Union[int, tuple] = (step_index if step_index is not None else 0, index)
            else:
                composite_step_index = step_index + (index,)
            step_outputs_for_step: List[StepOutput] = []
            try:
                async for event in step.aexecute_stream(
                    seg_input,
                    session_id=state["session_id"],
                    user_id=state["user_id"],
                    stream_events=stream_events,
                    stream_executor_events=stream_executor_events,
                    workflow_run_response=workflow_run_response,
                    step_index=composite_step_index,
                    store_executor_outputs=store_executor_outputs,
                    workflow_media_storage=workflow_media_storage,
                    run_context=run_context,
                    session_state=state["session_state"],
                    parent_step_id=step_id,
                    workflow_session=workflow_session,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    background_tasks=background_tasks,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs_for_step.append(event)
                        attempt_results.append(event)
                    else:
                        yield event
            except RunCancelledException:
                raise
            except UnresolvableCallableError:
                raise
            except Exception as e:
                failed = self._failed_segment_output(step, index, e)
                step_outputs_for_step.append(failed)
                attempt_results.append(failed)
            if step_outputs_for_step and getattr(step_outputs_for_step[-1], "is_paused", False):
                yield self._paused_output(
                    step_id, attempt_outputs, record=record, step_index=step_index, parent_step_id=parent_step_id
                )
                return
            if step_outputs_for_step:
                step_name = getattr(step, "name", None) or f"step_{index + 1}"
                segment_outputs[step_name] = step_outputs_for_step[-1]
                if any(output.stop for output in step_outputs_for_step):
                    yield self._stopped_output(step_id, record, attempt_outputs)
                    return
                chained = step_outputs_for_step[0] if len(step_outputs_for_step) == 1 else step_outputs_for_step
                seg_input = self._update_step_input_from_outputs(seg_input, chained, segment_outputs)

        fingerprint = await asafe_capture(self.fingerprint) if self.fingerprint is not None else None
        attempt = self._new_attempt(record, fingerprint, record.baseline_fingerprint)
        reenter = await self._ajudge(
            record,
            attempt,
            attempt_results,
            step_input,
            workflow_run_response,
            run_context,
            workflow_session,
        )
        if emit:
            yield self._attempt_completed_event(fields, record, reenter)
        if not reenter:
            log_debug(f"Verify End (resumed): {self.name} ({len(record.attempts)} attempts)", center=True, symbol="=")
            if emit:
                yield self._completed_event(fields, record)
            yield self._final_output(step_id, record, attempt_outputs, step_input)
            return

        report = self._build_attempt_report(record, attempt)
        reentry = self._reentry_input(step_input, attempt_results, report)
        async for event in self.aexecute_stream(
            reentry,
            session_id=state["session_id"],
            user_id=state["user_id"],
            stream_events=stream_events,
            stream_executor_events=stream_executor_events,
            workflow_run_response=workflow_run_response,
            step_index=step_index,
            parent_step_id=parent_step_id,
            store_executor_outputs=store_executor_outputs,
            workflow_media_storage=workflow_media_storage,
            run_context=run_context,
            session_state=state["session_state"],
            workflow_session=workflow_session,
            add_workflow_history_to_steps=add_workflow_history_to_steps,
            num_history_runs=num_history_runs,
            background_tasks=background_tasks,
            _resume_record=record,
            _resume_history=attempt_outputs,
            _resume_step_id=step_id,
        ):
            yield event


def resolve_verify_steps(steps: List[Any], owner: Any = None) -> List[Any]:
    """Absorb each Verify's loop-back segment out of a prepared steps list.

    For every Verify with a loop-back target, the steps from the target through the one
    just before the Verify move inside it, so the Verify can re-run them with the evidence
    report. Called from every container's step preparation; idempotent, because an
    already-resolved Verify is left alone and its former segment is no longer in the list.
    Raises ValueError when a target does not exist before its Verify — when the container
    prepares its steps, before any of them runs. ``owner`` is the workflow when this is its top-level list.
    """
    # A container rebuilt from raw definitions (a Router list route) re-resolves with the
    # absorbed segments still present, wherever the list puts them; keeping one would run it twice
    absorbed_ids = {
        id(item) for entry in steps if isinstance(entry, Verify) and entry._resolved for item in entry.steps
    }
    resolved: List[Any] = []
    for position, entry in enumerate(steps):
        if id(entry) in absorbed_ids:
            continue
        if not isinstance(entry, Verify):
            resolved.append(entry)
            continue
        # A resolved Verify already carries another workflow's segment and owner; reusing
        # it would run that segment (and hand that owner to the checks) in this workflow.
        if entry._resolved and owner is not None and entry._workflow is not None and entry._workflow is not owner:
            raise ValueError(
                f"Verify {entry.name!r} is already bound to another workflow; create a separate Verify per workflow"
            )
        if owner is not None and entry._workflow is None:
            entry._workflow = owner
        if entry._resolved:
            if owner is not None and entry.on_fail is None and position == 0:
                # A pure gate at the head of the workflow has nothing to judge.
                raise ValueError(
                    f"Verify {entry.name!r} is a pure gate with no step before it; a gate needs a step to check"
                )
            resolved.append(entry)
            continue
        target_index = entry._resolve_target_index(resolved)
        segment = resolved[target_index:]
        for absorbed in segment:
            _reject_verify_in_segment(entry, absorbed)
            _reject_unenforceable_step_policies(entry, absorbed)
        entry.steps = segment
        del resolved[target_index:]
        entry._resolved = True
        resolved.append(entry)
    return resolved


def _reject_verify_in_segment(entry: "Verify", absorbed: Any) -> None:
    """Refuse a loop-back segment that contains another Verify: the later gate would absorb
    the earlier one and re-run it, so one failing draft is judged by both gates per attempt."""
    if isinstance(absorbed, Verify):
        raise ValueError(
            f"Verify {entry.name!r} cannot re-run another gate, Verify {absorbed.name!r}; point on_fail after it or use on_fail=None."
        )


def _reject_unenforceable_step_policies(entry: "Verify", absorbed: Any) -> None:
    """Refuse to absorb a segment step whose step-level policies the Verify cannot honor.

    The workflow's own step loop is what enforces step-level ``human_review`` (pre-run
    confirmation, output review, ``on_error`` handling). An absorbed step runs inside the
    Verify composite and never passes through that loop again, so a confirmation or
    review gate on it would be silently stripped — fail-open. Raising here keeps the
    failure at build time. Tool-level ``requires_confirmation`` lives on the executor,
    pauses propagate through the composite, and stays allowed.
    """
    hr = getattr(absorbed, "human_review", None)
    if not isinstance(hr, HumanReview):
        return
    unenforceable = (
        hr.requires_confirmation
        or hr.requires_user_input
        or bool(hr.requires_output_review)
        or hr.requires_iteration_review
        or OnError(hr.on_error) is not OnError.skip
    )
    if unenforceable:
        raise ValueError(
            f"Verify {entry.name!r} cannot absorb step {absorbed.name!r} because its human_review policy only runs "
            "outside a Verify segment; use tool-level requires_confirmation instead."
        )
