"""The Verify workflow step: a cross-step verification gate with evidence-driven loop-back.

A ``Verify`` in a workflow's steps list runs its checks against the previous step's
output. When every required check passes, the workflow continues. When a check fails and
loop-backs remain, the segment from the ``on_fail`` step through the step before the
``Verify`` re-runs with the evidence report attached to the re-entered step's input; when
the budget is exhausted (or ``on_fail=None`` makes it a pure gate) the step ends with
``success=False`` and the full ``Verification`` record on its ``StepOutput``, and the
workflow's ordinary routing takes over.

At workflow build time the ``[on_fail .. Verify)`` segment is absorbed into the ``Verify``
component (see ``resolve_verify_steps``), so at execution time ``Verify`` is an ordinary
composite step — the same shape as ``Loop`` — and all four workflow execution paths
(sync/async, streaming or not) drive it through the same four ``execute`` methods every
other composite implements.
"""

from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Iterator, List, Optional, Union
from uuid import uuid4

from agno.media.storage.base import AsyncMediaStorage, MediaStorage
from agno.run.agent import RunOutputEvent
from agno.run.base import RunContext
from agno.run.cancel import araise_if_cancelled, raise_if_cancelled
from agno.run.team import TeamRunOutputEvent
from agno.run.workflow import WorkflowRunOutput, WorkflowRunOutputEvent
from agno.session.workflow import WorkflowSession
from agno.utils.log import log_debug, log_warning
from agno.verifiers._gate import CheckRun, arun_checks, run_checks
from agno.verifiers.base import coerce_verifier
from agno.verifiers.fingerprints import asafe_capture, coerce_fingerprint, noop_between, safe_capture
from agno.verifiers.report import build_report
from agno.verifiers.types import Verification, VerificationAttempt
from agno.workflow.types import StepInput, StepOutput, StepType

if TYPE_CHECKING:
    from agno.registry import Registry


class _PreviousStep:
    """Default for ``on_fail``: loop back to the step immediately before the Verify.

    A sentinel type rather than None, because an explicit ``on_fail=None`` means a pure
    gate with no loop-back at all.
    """

    def __repr__(self) -> str:
        return "<previous step>"


PREVIOUS_STEP = _PreviousStep()

# How the default target serializes; None already means "pure gate".
_PREVIOUS_STEP_SERIALIZED = "__previous_step__"


class Verify:
    """A verification gate between workflow steps.

    Args:
        checks: The checks to run — bare callables, shipped verifiers
            (``ShellVerifier``/``ScorerVerifier``), protocol objects, or ``check()``
            wrappers. Coerced once here, so a bad entry fails at construction.
        on_fail: The step to loop back to on failure — a step name or index from the same
            steps list, strictly before the Verify. Defaults to the immediately preceding
            step. ``None`` makes the Verify a pure gate: one check pass, no loop-back.
        max_rounds: Loop-backs allowed. The first pass through the checks is not a round,
            so the checks run at most ``max_rounds + 1`` times.
        stop_on_noop: With a fingerprint, a failed round that changed nothing ends the
            loop as unverified instead of spending further rounds.
        fingerprint: Optional world-state fingerprint captured around each round.
        name: Step name; defaults to "verify".
    """

    def __init__(
        self,
        checks: Union[List[Any], Any],
        on_fail: Any = PREVIOUS_STEP,
        max_rounds: int = 2,
        stop_on_noop: bool = False,
        fingerprint: Optional[Any] = None,
        name: Optional[str] = None,
    ):
        if not isinstance(checks, (list, tuple)):
            checks = [checks]
        if not checks:
            raise ValueError("Verify requires at least one check")
        self._verifiers = [coerce_verifier(entry) for entry in checks]
        if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or max_rounds < 0:
            raise ValueError(f"Verify max_rounds must be a non-negative int, got {max_rounds!r}")
        if not (on_fail is None or isinstance(on_fail, (str, _PreviousStep)) or self._is_index(on_fail)):
            raise TypeError(f"Verify on_fail must be a step name, a step index, or None; got {type(on_fail).__name__}")
        if stop_on_noop and fingerprint is None:
            raise ValueError("Verify(stop_on_noop=True) requires a fingerprint")
        self.max_rounds = max_rounds
        self.stop_on_noop = stop_on_noop
        self.fingerprint = coerce_fingerprint(fingerprint) if fingerprint is not None else None
        self.name: str = name or "verify"
        self.description: Optional[str] = None
        self.on_fail = on_fail
        # The absorbed loop-back segment, filled by resolve_verify_steps. A pure gate has
        # no segment and needs no resolution.
        self.steps: List[Any] = []
        self._resolved: bool = on_fail is None
        # The owning Workflow, when known; handed to the checks as their owner.
        self._workflow: Optional[Any] = None

    @staticmethod
    def _is_index(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        if isinstance(self.on_fail, _PreviousStep):
            on_fail_data: Any = _PREVIOUS_STEP_SERIALIZED
        else:
            on_fail_data = self.on_fail
        return {
            "type": "Verify",
            "name": self.name,
            "description": self.description,
            "verifiers": [getattr(v, "name", "") or "verifier" for v in self._verifiers],
            "on_fail": on_fail_data,
            "max_rounds": self.max_rounds,
            "stop_on_noop": self.stop_on_noop,
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
        from agno.workflow.condition import Condition
        from agno.workflow.loop import Loop
        from agno.workflow.parallel import Parallel
        from agno.workflow.router import Router
        from agno.workflow.step import Step, _unresolvable_callable_placeholder
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
        entries: List[Any] = []
        for verifier_name in data.get("verifiers") or []:
            fn = registry.get_function(verifier_name) if registry else None
            if fn is None:
                if registry:
                    message = f"Verify check '{verifier_name}' not found in registry"
                else:
                    message = f"Registry required to deserialize Verify check '{verifier_name}'"
                if strict:
                    from agno.exceptions import ComponentRehydrationError

                    raise ComponentRehydrationError(message)
                log_warning(message)
                fn = _unresolvable_callable_placeholder("Verify check", verifier_name)
                fn.__name__ = verifier_name  # type: ignore[attr-defined]
            entries.append(fn)

        on_fail_data = data.get("on_fail", _PREVIOUS_STEP_SERIALIZED)
        on_fail: Any = PREVIOUS_STEP if on_fail_data == _PREVIOUS_STEP_SERIALIZED else on_fail_data

        verify = cls(
            entries,
            on_fail=on_fail,
            max_rounds=data.get("max_rounds", 2),
            stop_on_noop=False,
            fingerprint=None,
            name=data.get("name"),
        )
        verify.description = data.get("description")
        if data.get("resolved"):
            verify.steps = [deserialize_step(step_data) for step_data in data.get("steps") or []]
            verify._resolved = True
        return verify

    # ------------------------------------------------------------------
    # Segment resolution
    # ------------------------------------------------------------------

    def _resolve_target_index(self, preceding: List[Any]) -> int:
        """Index of the loop-back target within the steps that precede this Verify.

        Raises ValueError when the target does not exist among them: a Verify that cannot
        reach its target must fail at build time, before any step runs.
        """
        label = self.name
        if isinstance(self.on_fail, _PreviousStep):
            if not preceding:
                raise ValueError(
                    f"Verify {label!r} has no preceding step to loop back to; pass on_fail=None for a pure gate"
                )
            return len(preceding) - 1
        if self._is_index(self.on_fail):
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
            raise ValueError(
                f"Verify {self.name!r} has an unresolved on_fail target; it must sit in a workflow steps list "
                "after the step it loops back to"
            )

    # ------------------------------------------------------------------
    # Shared round mechanics
    # ------------------------------------------------------------------

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
        if segment_step_outputs:
            updated_previous_step_outputs.update(segment_step_outputs)

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
        round_results: List[StepOutput],
        step_input: StepInput,
        workflow_run_response: Optional[WorkflowRunOutput],
    ) -> Any:
        """The object the checks judge: the checked step's executor RunOutput/TeamRunOutput
        when the workflow stored it, else the most content-bearing StepOutput available."""
        last: Optional[StepOutput] = None
        if round_results:
            last = round_results[-1]
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

    def _settle_round(
        self,
        record: Verification,
        attempt: VerificationAttempt,
        check_run: CheckRun,
        rounds_used: int,
    ) -> bool:
        """Stamp the record after one check pass. Returns True when the segment re-runs."""
        if check_run.fatal_failure:
            # A fatal check failed: re-running is pointless by the check author's own
            # declaration, whatever the remaining budget says.
            record.status = "unverified"
            record.stop_reason = "fatal"
            return False
        if check_run.passed:
            record.status = "verified"
            record.stop_reason = "passed"
            return False
        if attempt.noop and self.stop_on_noop:
            record.status = "unverified"
            record.stop_reason = "noop"
            return False
        if not self.steps or rounds_used >= self.max_rounds:
            # A pure gate has a budget of zero loop-backs; either way the budget is spent.
            record.status = "unverified"
            record.stop_reason = "exhausted"
            return False
        return True

    def _build_round_report(self, record: Verification, attempt: VerificationAttempt) -> str:
        return build_report(
            attempt,
            attempt_number=len(record.attempts),
            total_attempts=self.max_rounds + 1,
            has_fingerprint=self.fingerprint is not None,
            stop_on_noop=self.stop_on_noop,
        )

    def _reentry_input(self, step_input: StepInput, round_results: List[StepOutput], report: str) -> StepInput:
        """The re-entered segment's input: the failed round's output with the evidence
        report attached, injected as the newest previous-step output so the re-entered
        step's message carries it."""
        last = round_results[-1] if round_results else None
        prior = None
        if last is not None and isinstance(last.content, str) and last.content.strip():
            prior = last.content
        content = f"{prior}\n\n{report}" if prior else report

        outputs: Dict[str, StepOutput] = {}
        if step_input.previous_step_outputs:
            outputs.update(step_input.previous_step_outputs)
        for out in round_results:
            if out.step_name:
                outputs[out.step_name] = out
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

    def _summary(self, record: Verification) -> str:
        attempts = len(record.attempts)
        if record.passed:
            return f"Verify {self.name}: passed ({attempts} attempts)"
        failing: List[str] = []
        if record.attempts:
            failing = [v.name for v in record.attempts[-1].verdicts if v.gates and v.passed is not True]
        names = ", ".join(failing) or "checks"
        reason = record.stop_reason or "failed"
        return f"Verify {self.name}: unverified ({reason}) after {attempts} attempts: {names}"

    def _paused_output(self, step_id: str, all_results: List[StepOutput]) -> StepOutput:
        return StepOutput(
            step_name=self.name,
            step_id=step_id,
            step_type=StepType.VERIFY,
            content=f"Verify {self.name} paused at inner step",
            steps=list(all_results),
            is_paused=True,
        )

    def _stopped_output(self, step_id: str, record: Verification, all_results: List[StepOutput]) -> StepOutput:
        # An inner step requested early termination before the checks ran; the record
        # stays pending and the stop propagates like any other composite's.
        return StepOutput(
            step_name=self.name,
            step_id=step_id,
            step_type=StepType.VERIFY,
            content=f"Verify {self.name} stopped early by an inner step",
            success=all(result.success for result in all_results) if all_results else True,
            stop=True,
            steps=list(all_results),
            verification=record,
        )

    def _final_output(
        self,
        step_id: str,
        record: Verification,
        all_results: List[StepOutput],
        step_input: StepInput,
    ) -> StepOutput:
        passed = record.passed
        if all_results:
            # Downstream chaining reads the deepest nested output, so the segment's last
            # (verified) output is what the next step receives; the summary is display-only.
            content: Any = self._summary(record)
            steps: Optional[List[StepOutput]] = list(all_results)
        else:
            steps = None
            # A pure gate produced no output of its own; passing the checked content
            # through keeps the gate transparent to the next step.
            content = step_input.previous_step_content if passed else self._summary(record)
        return StepOutput(
            step_name=self.name,
            step_id=step_id,
            step_type=StepType.VERIFY,
            content=content,
            success=passed,
            steps=steps,
            verification=record,
        )

    # ------------------------------------------------------------------
    # Execution — the four workflow paths
    # ------------------------------------------------------------------

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
    ) -> StepOutput:
        """Execute the verification loop: run the segment (if any), run the checks, and
        either finish or re-enter the segment with the evidence report."""
        log_debug(f"Verify Start: {self.name}", center=True, symbol="=")
        self._require_resolved()

        step_id = str(uuid4())
        record = Verification()
        settled = safe_capture(self.fingerprint) if self.fingerprint is not None else None
        record.baseline_fingerprint = settled
        rounds_used = 0
        all_results: List[StepOutput] = []
        current_input = step_input

        while True:
            if workflow_run_response and workflow_run_response.run_id:
                raise_if_cancelled(workflow_run_response.run_id)

            round_results: List[StepOutput] = []
            stop_requested = False
            segment_input = current_input
            segment_outputs: Dict[str, StepOutput] = {}
            for i, step in enumerate(self.steps):
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
                outputs = step_output if isinstance(step_output, list) else [step_output]
                round_results.extend(outputs)
                if outputs and getattr(outputs[-1], "is_paused", False):
                    all_results.extend(round_results)
                    return self._paused_output(step_id, all_results)
                if outputs:
                    step_name = getattr(step, "name", None) or f"step_{i + 1}"
                    segment_outputs[step_name] = outputs[-1]
                    if any(output.stop for output in outputs):
                        stop_requested = True
                        break
                    segment_input = self._update_step_input_from_outputs(segment_input, step_output, segment_outputs)
            all_results.extend(round_results)
            if stop_requested:
                return self._stopped_output(step_id, record, all_results)

            attempt = VerificationAttempt(index=len(record.attempts))
            if self.fingerprint is not None:
                attempt.fingerprint = safe_capture(self.fingerprint)
                attempt.compared_against = settled
                attempt.noop = noop_between(settled, attempt.fingerprint)
            target = self._target_run_output(round_results, step_input, workflow_run_response)
            check_run = run_checks(
                self._verifiers,
                run_output=target,
                run_context=run_context,
                owner=self._workflow,
                session=workflow_session,
            )
            attempt.verdicts = check_run.verdicts
            record.attempts.append(attempt)
            if self.fingerprint is not None:
                # Settle after the checks: a check's own artefacts must not be charged to
                # the next round as the segment's work.
                settled = safe_capture(self.fingerprint)

            if not self._settle_round(record, attempt, check_run, rounds_used):
                break
            rounds_used += 1
            report = self._build_round_report(record, attempt)
            current_input = self._reentry_input(step_input, round_results, report)

        log_debug(f"Verify End: {self.name} ({len(record.attempts)} attempts)", center=True, symbol="=")
        return self._final_output(step_id, record, all_results, step_input)

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
    ) -> Iterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Streaming twin of `execute`: inner step events pass through; only the composite
        StepOutput is yielded as this step's result."""
        log_debug(f"Verify Start: {self.name}", center=True, symbol="=")
        self._require_resolved()

        step_id = str(uuid4())
        record = Verification()
        settled = safe_capture(self.fingerprint) if self.fingerprint is not None else None
        record.baseline_fingerprint = settled
        rounds_used = 0
        all_results: List[StepOutput] = []
        current_input = step_input

        while True:
            if workflow_run_response and workflow_run_response.run_id:
                raise_if_cancelled(workflow_run_response.run_id)

            round_results: List[StepOutput] = []
            stop_requested = False
            segment_input = current_input
            segment_outputs: Dict[str, StepOutput] = {}
            for i, step in enumerate(self.steps):
                if step_index is None or isinstance(step_index, int):
                    composite_step_index: Union[int, tuple] = (step_index if step_index is not None else 0, i)
                else:
                    composite_step_index = step_index + (i,)

                step_outputs_for_step: List[StepOutput] = []
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
                        round_results.append(event)
                    else:
                        yield event

                if step_outputs_for_step and getattr(step_outputs_for_step[-1], "is_paused", False):
                    all_results.extend(round_results)
                    yield self._paused_output(step_id, all_results)
                    return
                if step_outputs_for_step:
                    step_name = getattr(step, "name", None) or f"step_{i + 1}"
                    segment_outputs[step_name] = step_outputs_for_step[-1]
                    if any(output.stop for output in step_outputs_for_step):
                        stop_requested = True
                        break
                    chained = step_outputs_for_step[0] if len(step_outputs_for_step) == 1 else step_outputs_for_step
                    segment_input = self._update_step_input_from_outputs(segment_input, chained, segment_outputs)
            all_results.extend(round_results)
            if stop_requested:
                yield self._stopped_output(step_id, record, all_results)
                return

            attempt = VerificationAttempt(index=len(record.attempts))
            if self.fingerprint is not None:
                attempt.fingerprint = safe_capture(self.fingerprint)
                attempt.compared_against = settled
                attempt.noop = noop_between(settled, attempt.fingerprint)
            target = self._target_run_output(round_results, step_input, workflow_run_response)
            check_run = run_checks(
                self._verifiers,
                run_output=target,
                run_context=run_context,
                owner=self._workflow,
                session=workflow_session,
            )
            attempt.verdicts = check_run.verdicts
            record.attempts.append(attempt)
            if self.fingerprint is not None:
                settled = safe_capture(self.fingerprint)

            if not self._settle_round(record, attempt, check_run, rounds_used):
                break
            rounds_used += 1
            report = self._build_round_report(record, attempt)
            current_input = self._reentry_input(step_input, round_results, report)

        log_debug(f"Verify End: {self.name} ({len(record.attempts)} attempts)", center=True, symbol="=")
        yield self._final_output(step_id, record, all_results, step_input)

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
    ) -> StepOutput:
        """Async twin of `execute`."""
        log_debug(f"Verify Start: {self.name}", center=True, symbol="=")
        self._require_resolved()

        step_id = str(uuid4())
        record = Verification()
        settled = await asafe_capture(self.fingerprint) if self.fingerprint is not None else None
        record.baseline_fingerprint = settled
        rounds_used = 0
        all_results: List[StepOutput] = []
        current_input = step_input

        while True:
            if workflow_run_response and workflow_run_response.run_id:
                await araise_if_cancelled(workflow_run_response.run_id)

            round_results: List[StepOutput] = []
            stop_requested = False
            segment_input = current_input
            segment_outputs: Dict[str, StepOutput] = {}
            for i, step in enumerate(self.steps):
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
                outputs = step_output if isinstance(step_output, list) else [step_output]
                round_results.extend(outputs)
                if outputs and getattr(outputs[-1], "is_paused", False):
                    all_results.extend(round_results)
                    return self._paused_output(step_id, all_results)
                if outputs:
                    step_name = getattr(step, "name", None) or f"step_{i + 1}"
                    segment_outputs[step_name] = outputs[-1]
                    if any(output.stop for output in outputs):
                        stop_requested = True
                        break
                    segment_input = self._update_step_input_from_outputs(segment_input, step_output, segment_outputs)
            all_results.extend(round_results)
            if stop_requested:
                return self._stopped_output(step_id, record, all_results)

            attempt = VerificationAttempt(index=len(record.attempts))
            if self.fingerprint is not None:
                attempt.fingerprint = await asafe_capture(self.fingerprint)
                attempt.compared_against = settled
                attempt.noop = noop_between(settled, attempt.fingerprint)
            target = self._target_run_output(round_results, step_input, workflow_run_response)
            check_run = await arun_checks(
                self._verifiers,
                run_output=target,
                run_context=run_context,
                owner=self._workflow,
                session=workflow_session,
            )
            attempt.verdicts = check_run.verdicts
            record.attempts.append(attempt)
            if self.fingerprint is not None:
                settled = await asafe_capture(self.fingerprint)

            if not self._settle_round(record, attempt, check_run, rounds_used):
                break
            rounds_used += 1
            report = self._build_round_report(record, attempt)
            current_input = self._reentry_input(step_input, round_results, report)

        log_debug(f"Verify End: {self.name} ({len(record.attempts)} attempts)", center=True, symbol="=")
        return self._final_output(step_id, record, all_results, step_input)

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
    ) -> AsyncIterator[Union[WorkflowRunOutputEvent, TeamRunOutputEvent, RunOutputEvent, StepOutput]]:
        """Async streaming twin of `execute`."""
        log_debug(f"Verify Start: {self.name}", center=True, symbol="=")
        self._require_resolved()

        step_id = str(uuid4())
        record = Verification()
        settled = await asafe_capture(self.fingerprint) if self.fingerprint is not None else None
        record.baseline_fingerprint = settled
        rounds_used = 0
        all_results: List[StepOutput] = []
        current_input = step_input

        while True:
            if workflow_run_response and workflow_run_response.run_id:
                await araise_if_cancelled(workflow_run_response.run_id)

            round_results: List[StepOutput] = []
            stop_requested = False
            segment_input = current_input
            segment_outputs: Dict[str, StepOutput] = {}
            for i, step in enumerate(self.steps):
                if step_index is None or isinstance(step_index, int):
                    composite_step_index: Union[int, tuple] = (step_index if step_index is not None else 0, i)
                else:
                    composite_step_index = step_index + (i,)

                step_outputs_for_step: List[StepOutput] = []
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
                        round_results.append(event)
                    else:
                        yield event

                if step_outputs_for_step and getattr(step_outputs_for_step[-1], "is_paused", False):
                    all_results.extend(round_results)
                    yield self._paused_output(step_id, all_results)
                    return
                if step_outputs_for_step:
                    step_name = getattr(step, "name", None) or f"step_{i + 1}"
                    segment_outputs[step_name] = step_outputs_for_step[-1]
                    if any(output.stop for output in step_outputs_for_step):
                        stop_requested = True
                        break
                    chained = step_outputs_for_step[0] if len(step_outputs_for_step) == 1 else step_outputs_for_step
                    segment_input = self._update_step_input_from_outputs(segment_input, chained, segment_outputs)
            all_results.extend(round_results)
            if stop_requested:
                yield self._stopped_output(step_id, record, all_results)
                return

            attempt = VerificationAttempt(index=len(record.attempts))
            if self.fingerprint is not None:
                attempt.fingerprint = await asafe_capture(self.fingerprint)
                attempt.compared_against = settled
                attempt.noop = noop_between(settled, attempt.fingerprint)
            target = self._target_run_output(round_results, step_input, workflow_run_response)
            check_run = await arun_checks(
                self._verifiers,
                run_output=target,
                run_context=run_context,
                owner=self._workflow,
                session=workflow_session,
            )
            attempt.verdicts = check_run.verdicts
            record.attempts.append(attempt)
            if self.fingerprint is not None:
                settled = await asafe_capture(self.fingerprint)

            if not self._settle_round(record, attempt, check_run, rounds_used):
                break
            rounds_used += 1
            report = self._build_round_report(record, attempt)
            current_input = self._reentry_input(step_input, round_results, report)

        log_debug(f"Verify End: {self.name} ({len(record.attempts)} attempts)", center=True, symbol="=")
        yield self._final_output(step_id, record, all_results, step_input)


def resolve_verify_steps(steps: List[Any], owner: Any = None) -> List[Any]:
    """Absorb each Verify's loop-back segment out of a prepared steps list.

    For every Verify with a loop-back target, the steps from the target through the one
    just before the Verify move inside it, so the Verify can re-run them with the evidence
    report. Called from every container's step preparation; idempotent, because an
    already-resolved Verify is left alone and its former segment is no longer in the list.
    Raises ValueError when a target does not exist before its Verify — at build time,
    before any step runs.
    """
    resolved: List[Any] = []
    for entry in steps:
        if not isinstance(entry, Verify):
            resolved.append(entry)
            continue
        if owner is not None and entry._workflow is None:
            entry._workflow = owner
        if entry._resolved:
            resolved.append(entry)
            continue
        target_index = entry._resolve_target_index(resolved)
        entry.steps = resolved[target_index:]
        del resolved[target_index:]
        entry._resolved = True
        resolved.append(entry)
    return resolved
