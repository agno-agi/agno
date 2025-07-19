import inspect
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Union

from agno.run.response import RunResponseEvent
from agno.run.team import TeamRunResponseEvent
from agno.run.v2.workflow import (
    LoopExecutionCompletedEvent,
    LoopExecutionStartedEvent,
    LoopIterationCompletedEvent,
    LoopIterationStartedEvent,
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
class Loop:
    """A loop of steps that execute in order"""

    steps: WorkflowSteps

    name: Optional[str] = None
    description: Optional[str] = None

    max_iterations: int = 3  # Default to 3
    end_condition: Optional[Callable[[List[StepOutput]], bool]] = None

    def __init__(
        self,
        steps: WorkflowSteps,
        name: Optional[str] = None,
        description: Optional[str] = None,
        max_iterations: int = 3,
        end_condition: Optional[Callable[[List[StepOutput]], bool]] = None,
    ):
        self.steps = steps
        self.name = name
        self.description = description
        self.max_iterations = max_iterations
        self.end_condition = end_condition

    def _prepare_steps(self):
        """Prepare the steps for execution - mirrors workflow logic"""
        from agno.agent.agent import Agent
        from agno.team.team import Team
        from agno.workflow.v2.condition import Condition
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
        loop_step_outputs: Optional[Dict[str, StepOutput]] = None,
    ) -> StepInput:
        """Helper to update step input from step outputs (handles both single and multiple outputs)"""
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
        if loop_step_outputs:
            updated_previous_step_outputs.update(loop_step_outputs)

        return StepInput(
            message=step_input.message,
            previous_step_content=previous_step_content,
            previous_step_outputs=updated_previous_step_outputs,
            additional_data=step_input.additional_data,
            images=current_images + all_images,
            videos=current_videos + all_videos,
            audio=current_audio + all_audio,
        )

    def execute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[StepOutput]:
        """Execute loop steps with iteration control - mirrors workflow execution logic"""
        # Use workflow logger for loop orchestration
        log_debug(f"Loop Start: {self.name}", center=True, symbol="=")

        # Prepare steps first
        self._prepare_steps()

        all_results = []
        iteration = 0

        while iteration < self.max_iterations:
            # Execute all steps in this iteration - mirroring workflow logic
            iteration_results: List[StepOutput] = []
            current_step_input = step_input
            loop_step_outputs = {}  # Track outputs within this loop iteration

            for i, step in enumerate(self.steps):
                step_output = step.execute(current_step_input, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]

                # Handle both single StepOutput and List[StepOutput] (from Loop/Condition steps)
                if isinstance(step_output, list):
                    # This is a step that returns multiple outputs (Loop, Condition etc.)
                    iteration_results.extend(step_output)
                    if step_output:  # Add last output to loop tracking
                        step_name = getattr(step, "name", f"step_{i + 1}")
                        loop_step_outputs[step_name] = step_output[-1]

                        if any(output.stop for output in step_output):
                            logger.info(f"Early termination requested by step {step_name}")
                            break
                else:
                    # Single StepOutput
                    iteration_results.append(step_output)
                    step_name = getattr(step, "name", f"step_{i + 1}")
                    loop_step_outputs[step_name] = step_output

                    if step_output.stop:
                        logger.info(f"Early termination requested by step {step_name}")
                        break

                # Update step input for next step
                current_step_input = self._update_step_input_from_outputs(
                    current_step_input, step_output, loop_step_outputs
                )

            all_results.append(iteration_results)
            iteration += 1

            # Check end condition
            if self.end_condition and callable(self.end_condition):
                try:
                    should_break = self.end_condition(iteration_results)
                    if should_break:
                        break
                except Exception as e:
                    logger.warning(f"End condition evaluation failed: {e}")
                    # Continue with loop if end condition fails

        log_debug(f"Loop End: {self.name} ({iteration} iterations)", center=True, symbol="=")

        # Return flattened results from all iterations
        flattened_results = []
        for iteration_results in all_results:
            flattened_results.extend(iteration_results)

        return flattened_results

    def execute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[Union[int, tuple]] = None,
    ) -> Iterator[Union[WorkflowRunResponseEvent, StepOutput]]:
        """Execute loop steps with streaming support - mirrors workflow execution logic"""
        log_debug(f"Loop Start: {self.name}", center=True, symbol="=")

        # Prepare steps first
        self._prepare_steps()

        if stream_intermediate_steps and workflow_run_response:
            # Yield loop started event
            yield LoopExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                max_iterations=self.max_iterations,
            )

        all_results = []
        iteration = 0
        early_termination = False

        while iteration < self.max_iterations:
            log_debug(f"Loop iteration {iteration + 1}/{self.max_iterations}")

            if stream_intermediate_steps and workflow_run_response:
                # Yield iteration started event
                yield LoopIterationStartedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    iteration=iteration + 1,
                    max_iterations=self.max_iterations,
                )

            # Execute all steps in this iteration - mirroring workflow logic
            iteration_results = []
            current_step_input = step_input
            loop_step_outputs = {}

            for i, step in enumerate(self.steps):
                step_outputs_for_iteration = []

                # Loop children always get sequential sub-indices: parent_index.1, parent_index.2, etc.
                if step_index is None or isinstance(step_index, int):
                    # Loop is a main step
                    composite_step_index = (step_index if step_index is not None else 0, i)
                else:
                    # Loop is a nested step - extend the tuple
                    composite_step_index = step_index + (i,)

                # Stream step execution
                for event in step.execute_stream(  # type: ignore[union-attr]
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=composite_step_index,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs_for_iteration.append(event)
                        iteration_results.append(event)
                    else:
                        # Yield other events (streaming content, step events, etc.)
                        yield event

                # Update loop_step_outputs with this step's output
                if step_outputs_for_iteration:
                    step_name = getattr(step, "name", f"step_{i + 1}")
                    if len(step_outputs_for_iteration) == 1:
                        loop_step_outputs[step_name] = step_outputs_for_iteration[0]

                        if step_outputs_for_iteration[0].stop:
                            logger.info(f"Early termination requested by step {step_name}")
                            early_termination = True
                            break  # Break out of step loop

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_iteration[0], loop_step_outputs
                        )
                    else:
                        # Use last output
                        loop_step_outputs[step_name] = step_outputs_for_iteration[-1]

                        if any(output.stop for output in step_outputs_for_iteration):
                            logger.info(f"Early termination requested by step {step_name}")
                            early_termination = True
                            break  # Break out of step loop

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_iteration, loop_step_outputs
                        )

            all_results.append(iteration_results)

            # Check end condition
            should_continue = True
            if self.end_condition and callable(self.end_condition):
                try:
                    should_break = self.end_condition(iteration_results)
                    should_continue = not should_break
                    log_debug(f"End condition returned: {should_break}, should_continue: {should_continue}")
                except Exception as e:
                    logger.warning(f"End condition evaluation failed: {e}")

            if early_termination:
                should_continue = False
                log_debug(f"Loop ending early due to step termination request at iteration {iteration}")

            if stream_intermediate_steps and workflow_run_response:
                # Yield iteration completed event
                yield LoopIterationCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    iteration=iteration + 1,
                    max_iterations=self.max_iterations,
                    iteration_results=iteration_results,
                    should_continue=should_continue,
                )

            iteration += 1

            if not should_continue:
                log_debug(f"Loop ending early due to end_condition at iteration {iteration}")
                break

        log_debug(f"Loop End: {self.name} ({iteration} iterations)", center=True, symbol="=")

        if stream_intermediate_steps and workflow_run_response:
            # Yield loop completed event
            yield LoopExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                total_iterations=iteration,
                max_iterations=self.max_iterations,
                all_results=all_results,
            )

        for iteration_results in all_results:
            for step_output in iteration_results:
                yield step_output

    async def aexecute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[StepOutput]:
        """Execute loop steps asynchronously with iteration control - mirrors workflow execution logic"""
        # Use workflow logger for async loop orchestration
        log_debug(f"Loop Start: {self.name}", center=True, symbol="=")

        # Prepare steps first
        self._prepare_steps()

        all_results = []
        iteration = 0

        while iteration < self.max_iterations:
            # Execute all steps in this iteration - mirroring workflow logic
            iteration_results: List[StepOutput] = []
            current_step_input = step_input
            loop_step_outputs = {}  # Track outputs within this loop iteration

            for i, step in enumerate(self.steps):
                step_output = await step.aexecute(current_step_input, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]

                # Handle both single StepOutput and List[StepOutput] (from Loop/Condition steps)
                if isinstance(step_output, list):
                    # This is a step that returns multiple outputs (Loop, Condition etc.)
                    iteration_results.extend(step_output)
                    if step_output:  # Add last output to loop tracking
                        step_name = getattr(step, "name", f"step_{i + 1}")
                        loop_step_outputs[step_name] = step_output[-1]

                        if any(output.stop for output in step_output):
                            logger.info(f"Early termination requested by step {step_name}")
                            break
                else:
                    # Single StepOutput
                    iteration_results.append(step_output)
                    step_name = getattr(step, "name", f"step_{i + 1}")
                    loop_step_outputs[step_name] = step_output

                    if step_output.stop:
                        logger.info(f"Early termination requested by step {step_name}")
                        break

                # Update step input for next step
                current_step_input = self._update_step_input_from_outputs(
                    current_step_input, step_output, loop_step_outputs
                )

            all_results.append(iteration_results)
            iteration += 1

            # Check end condition
            if self.end_condition and callable(self.end_condition):
                try:
                    if inspect.iscoroutinefunction(self.end_condition):
                        should_break = await self.end_condition(iteration_results)
                    else:
                        should_break = self.end_condition(iteration_results)
                    if should_break:
                        break
                except Exception as e:
                    logger.warning(f"End condition evaluation failed: {e}")

        # Use workflow logger for async loop completion
        log_debug(f"Async Loop End: {self.name} ({iteration} iterations)", center=True, symbol="=")

        # Return flattened results from all iterations
        flattened_results = []
        for iteration_results in all_results:
            flattened_results.extend(iteration_results)

        return flattened_results

    async def aexecute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[Union[int, tuple]] = None,
    ) -> AsyncIterator[Union[WorkflowRunResponseEvent, TeamRunResponseEvent, RunResponseEvent, StepOutput]]:
        """Execute loop steps with async streaming support - mirrors workflow execution logic"""
        log_debug(f"Loop Start: {self.name}", center=True, symbol="=")

        # Prepare steps first
        self._prepare_steps()

        if stream_intermediate_steps and workflow_run_response:
            # Yield loop started event
            yield LoopExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                max_iterations=self.max_iterations,
            )

        all_results = []
        iteration = 0
        early_termination = False

        while iteration < self.max_iterations:
            log_debug(f"Async loop iteration {iteration + 1}/{self.max_iterations}")

            if stream_intermediate_steps and workflow_run_response:
                # Yield iteration started event
                yield LoopIterationStartedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    iteration=iteration + 1,
                    max_iterations=self.max_iterations,
                )

            # Execute all steps in this iteration - mirroring workflow logic
            iteration_results = []
            current_step_input = step_input
            loop_step_outputs = {}  # Track outputs within this loop iteration

            for i, step in enumerate(self.steps):
                step_outputs_for_iteration = []

                # Loop children always get sequential sub-indices: parent_index.1, parent_index.2, etc.
                if step_index is None or isinstance(step_index, int):
                    # Loop is a main step
                    composite_step_index = (step_index if step_index is not None else 0, i)
                else:
                    # Loop is a nested step - extend the tuple
                    composite_step_index = step_index + (i,)

                # Stream step execution - mirroring workflow logic
                async for event in step.aexecute_stream(  # type: ignore[union-attr]
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=composite_step_index,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs_for_iteration.append(event)
                        iteration_results.append(event)
                    else:
                        # Yield other events (streaming content, step events, etc.)
                        yield event

                # Update loop_step_outputs with this step's output
                if step_outputs_for_iteration:
                    step_name = getattr(step, "name", f"step_{i + 1}")
                    if len(step_outputs_for_iteration) == 1:
                        loop_step_outputs[step_name] = step_outputs_for_iteration[0]

                        if step_outputs_for_iteration[0].stop:
                            logger.info(f"Early termination requested by step {step_name}")
                            early_termination = True
                            break  # Break out of step loop

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_iteration[0], loop_step_outputs
                        )
                    else:
                        # Use last output
                        loop_step_outputs[step_name] = step_outputs_for_iteration[-1]

                        if any(output.stop for output in step_outputs_for_iteration):
                            logger.info(f"Early termination requested by step {step_name}")
                            early_termination = True
                            break  # Break out of step loop

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_iteration, loop_step_outputs
                        )

            all_results.append(iteration_results)

            # Check end condition
            should_continue = True
            if self.end_condition and callable(self.end_condition):
                try:
                    if inspect.iscoroutinefunction(self.end_condition):
                        should_break = await self.end_condition(iteration_results)
                    else:
                        should_break = self.end_condition(iteration_results)
                    should_continue = not should_break
                    log_debug(f"End condition returned: {should_break}, should_continue: {should_continue}")
                except Exception as e:
                    logger.warning(f"End condition evaluation failed: {e}")

            if early_termination:
                should_continue = False
                log_debug(f"Loop ending early due to step termination request at iteration {iteration}")

            if stream_intermediate_steps and workflow_run_response:
                # Yield iteration completed event
                yield LoopIterationCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    iteration=iteration + 1,
                    max_iterations=self.max_iterations,
                    iteration_results=iteration_results,
                    should_continue=should_continue,
                )

            iteration += 1

            if not should_continue:
                log_debug(f"Loop ending early due to end_condition at iteration {iteration}")
                break

        log_debug(f"Loop End: {self.name} ({iteration} iterations)", center=True, symbol="=")

        if stream_intermediate_steps and workflow_run_response:
            # Yield loop completed event
            yield LoopExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                total_iterations=iteration,
                max_iterations=self.max_iterations,
                all_results=all_results,
            )

        for iteration_results in all_results:
            for step_output in iteration_results:
                yield step_output
