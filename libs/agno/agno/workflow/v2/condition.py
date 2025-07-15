import inspect
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Union

from agno.run.response import RunResponseEvent
from agno.run.team import TeamRunResponseEvent
from agno.run.v2.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    WorkflowRunResponse,
    WorkflowRunResponseEvent,
)
from agno.utils.log import log_debug, logger
from agno.workflow.v2.step import Step
from agno.workflow.v2.types import StepInput, StepOutput

WorkflowSteps = List[
    Union[
        Callable[
            [StepInput], Union[StepOutput, Awaitable[StepOutput], Iterator[StepOutput], AsyncIterator[StepOutput]]
        ],
        Step,
        "Steps",  # type: ignore # noqa: F821
        "Loop",  # type: ignore # noqa: F821
        "Parallel",  # type: ignore # noqa: F821
        "Condition",  # type: ignore # noqa: F821
        "Router",  # type: ignore # noqa: F821
    ]
]


@dataclass
class Condition:
    """A condition that executes a step (or list of steps) if the condition is met"""

    # Evaluator should only return boolean
    evaluator: Union[
        Callable[[StepInput], bool],
        Callable[[StepInput], Awaitable[bool]],
        bool,
    ]
    steps: WorkflowSteps

    name: Optional[str] = None
    description: Optional[str] = None

    def _prepare_steps(self):
        """Prepare the steps for execution - mirrors workflow logic"""
        from agno.agent.agent import Agent
        from agno.team.team import Team
        from agno.workflow.v2.loop import Loop
        from agno.workflow.v2.parallel import Parallel
        from agno.workflow.v2.router import Router
        from agno.workflow.v2.step import Step
        from agno.workflow.v2.steps import Steps

        prepared_steps: WorkflowSteps = []
        for step in self.steps:
            if callable(step) and hasattr(step, "__name__"):
                prepared_steps.append(Step(name=step.__name__, description="User-defined callable step", executor=step))
            elif isinstance(step, Agent):
                prepared_steps.append(Step(name=step.name, description=step.description, agent=step))
            elif isinstance(step, Team):
                prepared_steps.append(Step(name=step.name, description=step.description, team=step))
            elif isinstance(step, (Step, Steps, Loop, Parallel, Condition, Router)):
                prepared_steps.append(step)
            else:
                raise ValueError(f"Invalid step type: {type(step).__name__}")

        self.steps = prepared_steps

    def _update_step_input_from_outputs(
        self,
        step_input: StepInput,
        step_outputs: Union[StepOutput, List[StepOutput]],
        condition_step_outputs: Optional[Dict[str, StepOutput]] = None,
    ) -> StepInput:
        """Helper to update step input from step outputs - mirrors Loop logic"""
        current_images = step_input.images or []
        current_videos = step_input.videos or []
        current_audio = step_input.audio or []

        if isinstance(step_outputs, list):
            all_images = sum([out.images or [] for out in step_outputs], [])
            all_videos = sum([out.videos or [] for out in step_outputs], [])
            all_audio = sum([out.audio or [] for out in step_outputs], [])
            # Use the last output's content for chaining
            previous_step_content = step_outputs[-1].content if step_outputs else None
        else:
            # Single output
            all_images = step_outputs.images or []
            all_videos = step_outputs.videos or []
            all_audio = step_outputs.audio or []
            previous_step_content = step_outputs.content

        updated_previous_step_outputs = {}
        if step_input.previous_step_outputs:
            updated_previous_step_outputs.update(step_input.previous_step_outputs)
        if condition_step_outputs:
            updated_previous_step_outputs.update(condition_step_outputs)

        return StepInput(
            message=step_input.message,
            previous_step_content=previous_step_content,
            previous_step_outputs=updated_previous_step_outputs,
            additional_data=step_input.additional_data,
            images=current_images + all_images,
            videos=current_videos + all_videos,
            audio=current_audio + all_audio,
        )

    def _evaluate_condition(self, step_input: StepInput) -> bool:
        """Evaluate the condition and return boolean result"""
        if isinstance(self.evaluator, bool):
            return self.evaluator

        if callable(self.evaluator):
            result = self.evaluator(step_input)

            if isinstance(result, bool):
                return result
            else:
                logger.warning(f"Condition evaluator returned unexpected type: {type(result)}, expected bool")
                return False

        return False

    async def _aevaluate_condition(self, step_input: StepInput) -> bool:
        """Async version of condition evaluation"""
        if isinstance(self.evaluator, bool):
            return self.evaluator

        if callable(self.evaluator):
            if inspect.iscoroutinefunction(self.evaluator):
                result = await self.evaluator(step_input)
            else:
                result = self.evaluator(step_input)

            if isinstance(result, bool):
                return result
            else:
                logger.warning(f"Condition evaluator returned unexpected type: {type(result)}, expected bool")
                return False

        return False

    def execute(
        self, step_input: StepInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> List[StepOutput]:
        """Execute the condition and its steps with sequential chaining if condition is true"""
        log_debug(f"Condition Start: {self.name}", center=True, symbol="-")

        self._prepare_steps()

        # Evaluate the condition
        condition_result = self._evaluate_condition(step_input)
        log_debug(f"Condition {self.name} evaluated to: {condition_result}")

        if not condition_result:
            log_debug(f"Condition {self.name} not met, skipping {len(self.steps)} steps")
            return []

        log_debug(f"Condition {self.name} met, executing {len(self.steps)} steps")
        all_results: List[StepOutput] = []
        current_step_input = step_input
        condition_step_outputs = {}

        for i, step in enumerate(self.steps):
            try:
                step_output = step.execute(current_step_input, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]

                # Handle both single StepOutput and List[StepOutput] (from Loop/Condition/Router steps)
                if isinstance(step_output, list):
                    all_results.extend(step_output)
                    if step_output:
                        step_name = getattr(step, "name", f"step_{i}")
                        log_debug(f"Executing condition step {i + 1}/{len(self.steps)}: {step_name}")

                        condition_step_outputs[step_name] = step_output[-1]

                        if any(output.stop for output in step_output):
                            logger.info(f"Early termination requested by condition step {step_name}")
                            break
                else:
                    all_results.append(step_output)
                    step_name = getattr(step, "name", f"step_{i}")
                    condition_step_outputs[step_name] = step_output

                    if step_output.stop:
                        logger.info(f"Early termination requested by condition step {step_name}")
                        break

                step_name = getattr(step, "name", f"step_{i}")
                log_debug(f"Condition step {step_name} completed")

                current_step_input = self._update_step_input_from_outputs(
                    current_step_input, step_output, condition_step_outputs
                )

            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Condition step {step_name} failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                all_results.append(error_output)
                break

        log_debug(f"Condition End: {self.name} ({len(all_results)} results)", center=True, symbol="-")
        return all_results

    def execute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[Union[int, tuple]] = None,
    ) -> Iterator[Union[WorkflowRunResponseEvent, StepOutput]]:
        """Execute the condition with streaming support - mirrors Loop logic"""
        log_debug(f"Condition Start: {self.name}", center=True, symbol="-")

        self._prepare_steps()

        # Evaluate the condition
        condition_result = self._evaluate_condition(step_input)
        log_debug(f"Condition {self.name} evaluated to: {condition_result}")

        if stream_intermediate_steps and workflow_run_response:
            # Yield condition started event
            yield ConditionExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                condition_result=condition_result,
            )

        if not condition_result:
            if stream_intermediate_steps and workflow_run_response:
                # Yield condition completed event for empty case
                yield ConditionExecutionCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    condition_result=False,
                    executed_steps=0,
                    step_results=[],
                )
            return

        log_debug(f"Condition {self.name} met, executing {len(self.steps)} steps")
        all_results = []
        current_step_input = step_input
        condition_step_outputs = {}

        for i, step in enumerate(self.steps):
            try:
                step_outputs_for_step = []

                # Create child index for each step within condition
                if step_index is None or isinstance(step_index, int):
                    # Condition is a main step - child steps get x.1, x.2, x.3 format
                    child_step_index = (step_index if step_index is not None else 1, i)
                else:
                    # Condition is already a child step - child steps get same parent number: x.y, x.y, x.y
                    child_step_index = step_index

                # Stream step execution
                for event in step.execute_stream(  # type: ignore[union-attr]
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=child_step_index,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs_for_step.append(event)
                        all_results.append(event)
                    else:
                        # Yield other events (streaming content, step events, etc.)
                        yield event

                step_name = getattr(step, "name", f"step_{i}")
                log_debug(f"Condition step {step_name} streaming completed")

                if step_outputs_for_step:
                    if len(step_outputs_for_step) == 1:
                        condition_step_outputs[step_name] = step_outputs_for_step[0]

                        if step_outputs_for_step[0].stop:
                            logger.info(f"Early termination requested by condition step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step[0], condition_step_outputs
                        )
                    else:
                        # Use last output
                        condition_step_outputs[step_name] = step_outputs_for_step[-1]

                        if any(output.stop for output in step_outputs_for_step):
                            logger.info(f"Early termination requested by condition step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step, condition_step_outputs
                        )

            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Condition step {step_name} streaming failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                all_results.append(error_output)
                break

        log_debug(f"Condition End: {self.name} ({len(all_results)} results)", center=True, symbol="-")
        if stream_intermediate_steps and workflow_run_response:
            # Yield condition completed event
            yield ConditionExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                condition_result=True,
                executed_steps=len(self.steps),
                step_results=all_results,
            )

        for result in all_results:
            yield result

    async def aexecute(
        self, step_input: StepInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> List[StepOutput]:
        """Async execute the condition and its steps with sequential chaining"""
        log_debug(f"Condition Start: {self.name}", center=True, symbol="-")

        self._prepare_steps()

        # Evaluate the condition
        condition_result = await self._aevaluate_condition(step_input)
        log_debug(f"Condition {self.name} evaluated to: {condition_result}")

        if not condition_result:
            log_debug(f"Condition {self.name} not met, skipping {len(self.steps)} steps")
            return []

        log_debug(f"Condition {self.name} met, executing {len(self.steps)} steps")

        # Chain steps sequentially like Loop does
        all_results: List[StepOutput] = []
        current_step_input = step_input
        condition_step_outputs = {}

        for i, step in enumerate(self.steps):
            try:
                step_output = await step.aexecute(current_step_input, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]

                # Handle both single StepOutput and List[StepOutput]
                if isinstance(step_output, list):
                    all_results.extend(step_output)
                    if step_output:
                        step_name = getattr(step, "name", f"step_{i}")
                        condition_step_outputs[step_name] = step_output[-1]

                        if any(output.stop for output in step_output):
                            logger.info(f"Early termination requested by condition step {step_name}")
                            break
                else:
                    all_results.append(step_output)
                    step_name = getattr(step, "name", f"step_{i}")
                    condition_step_outputs[step_name] = step_output

                    if step_output.stop:
                        logger.info(f"Early termination requested by condition step {step_name}")
                        break

                step_name = getattr(step, "name", f"step_{i}")
                log_debug(f"Condition step {step_name} async completed")

                current_step_input = self._update_step_input_from_outputs(
                    current_step_input, step_output, condition_step_outputs
                )

            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Condition step {step_name} async failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                all_results.append(error_output)
                break

        log_debug(f"Condition End: {self.name} ({len(all_results)} results)", center=True, symbol="-")
        return all_results

    async def aexecute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[Union[int, tuple]] = None,
    ) -> AsyncIterator[Union[WorkflowRunResponseEvent, TeamRunResponseEvent, RunResponseEvent, StepOutput]]:
        """Async execute the condition with streaming support - mirrors Loop logic"""
        log_debug(f"Condition Start: {self.name}", center=True, symbol="-")

        self._prepare_steps()

        # Evaluate the condition
        condition_result = await self._aevaluate_condition(step_input)
        log_debug(f"Condition {self.name} evaluated to: {condition_result}")

        if stream_intermediate_steps and workflow_run_response:
            # Yield condition started event
            yield ConditionExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                condition_result=condition_result,
            )

        if not condition_result:
            if stream_intermediate_steps and workflow_run_response:
                # Yield condition completed event for empty case
                yield ConditionExecutionCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    condition_result=False,
                    executed_steps=0,
                    step_results=[],
                )
            return

        log_debug(f"Condition {self.name} met, executing {len(self.steps)} steps")

        # Chain steps sequentially like Loop does
        all_results = []
        current_step_input = step_input
        condition_step_outputs = {}

        for i, step in enumerate(self.steps):
            try:
                step_outputs_for_step = []

                # Create child index for each step within condition
                if step_index is None or isinstance(step_index, int):
                    # Condition is a main step - child steps get x.1, x.2, x.3 format
                    child_step_index = (step_index if step_index is not None else 1, i)
                else:
                    # Condition is already a child step - child steps get same parent number: x.y, x.y, x.y
                    child_step_index = step_index

                # Stream step execution - mirroring Loop logic
                async for event in step.aexecute_stream(  # type: ignore[union-attr]
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=child_step_index,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs_for_step.append(event)
                        all_results.append(event)
                    else:
                        # Yield other events (streaming content, step events, etc.)
                        yield event

                step_name = getattr(step, "name", f"step_{i}")
                log_debug(f"Condition step {step_name} async streaming completed")

                if step_outputs_for_step:
                    if len(step_outputs_for_step) == 1:
                        condition_step_outputs[step_name] = step_outputs_for_step[0]

                        if step_outputs_for_step[0].stop:
                            logger.info(f"Early termination requested by condition step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step[0], condition_step_outputs
                        )
                    else:
                        # Use last output
                        condition_step_outputs[step_name] = step_outputs_for_step[-1]

                        if any(output.stop for output in step_outputs_for_step):
                            logger.info(f"Early termination requested by condition step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step, condition_step_outputs
                        )

            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Condition step {step_name} async streaming failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                all_results.append(error_output)
                break

        log_debug(f"Condition End: {self.name} ({len(all_results)} results)", center=True, symbol="-")

        if stream_intermediate_steps and workflow_run_response:
            # Yield condition completed event
            yield ConditionExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                condition_result=True,
                executed_steps=len(self.steps),
                step_results=all_results,
            )

        for result in all_results:
            yield result
