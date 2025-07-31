from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Union

from agno.run.response import RunResponseEvent
from agno.run.team import TeamRunResponseEvent
from agno.run.v2.workflow import (
    StepsExecutionCompletedEvent,
    StepsExecutionStartedEvent,
    WorkflowRunResponse,
    WorkflowRunResponseEvent,
)
from agno.utils.log import log_debug, logger
from agno.workflow.v2.step import Step, StepInput, StepOutput

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
class Steps:
    """A pipeline of steps that execute in order"""

    # Steps to execute
    steps: WorkflowSteps

    # Pipeline identification
    name: Optional[str] = None
    description: Optional[str] = None

    def __init__(
        self, name: Optional[str] = None, description: Optional[str] = None, steps: Optional[List[Any]] = None
    ):  # Change to List[Any]
        self.name = name
        self.description = description
        self.steps = steps if steps else []

    def _prepare_steps(self):
        """Prepare the steps for execution - mirrors workflow logic"""
        from agno.agent.agent import Agent
        from agno.team.team import Team
        from agno.workflow.v2.condition import Condition
        from agno.workflow.v2.loop import Loop
        from agno.workflow.v2.parallel import Parallel
        from agno.workflow.v2.router import Router
        from agno.workflow.v2.step import Step

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
        steps_step_outputs: Optional[Dict[str, StepOutput]] = None,
    ) -> StepInput:
        """Helper to update step input from step outputs - mirrors Condition/Router logic"""
        current_images = step_input.images or []
        current_videos = step_input.videos or []
        current_audio = step_input.audio or []

        if isinstance(step_outputs, list):
            step_images = sum([out.images or [] for out in step_outputs], [])
            step_videos = sum([out.videos or [] for out in step_outputs], [])
            step_audio = sum([out.audio or [] for out in step_outputs], [])
            # Use the last output's content for chaining
            previous_step_content = step_outputs[-1].content if step_outputs else None
        else:
            # Single output
            step_images = step_outputs.images or []
            step_videos = step_outputs.videos or []
            step_audio = step_outputs.audio or []
            previous_step_content = step_outputs.content

        updated_previous_step_outputs = {}
        if step_input.previous_step_outputs:
            updated_previous_step_outputs.update(step_input.previous_step_outputs)
        if steps_step_outputs:
            updated_previous_step_outputs.update(steps_step_outputs)

        return StepInput(
            message=step_input.message,
            previous_step_content=previous_step_content,
            previous_step_outputs=updated_previous_step_outputs,
            additional_data=step_input.additional_data,
            images=current_images + step_images,
            videos=current_videos + step_videos,
            audio=current_audio + step_audio,
        )

    def execute(
        self, step_input: StepInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> List[StepOutput]:
        """Execute all steps in sequence and return the final result"""
        log_debug(f"Steps Start: {self.name} ({len(self.steps)} steps)", center=True, symbol="-")

        self._prepare_steps()

        if not self.steps:
            return [StepOutput(step_name=self.name or "Steps", content="No steps to execute")]

        # Track outputs and pass data between steps - following Condition/Router pattern
        all_results: List[StepOutput] = []
        current_step_input = step_input
        steps_step_outputs = {}

        try:
            for i, step in enumerate(self.steps):
                step_name = getattr(step, "name", f"step_{i + 1}")
                log_debug(f"Steps {self.name}: Executing step {i + 1}/{len(self.steps)} - {step_name}")

                # Execute step
                step_output = step.execute(current_step_input, session_id=session_id, user_id=user_id)  # type: ignore

                # Handle both single StepOutput and List[StepOutput] (from Loop/Condition/Router steps)
                if isinstance(step_output, list):
                    all_results.extend(step_output)
                    if step_output:
                        steps_step_outputs[step_name] = step_output[-1]

                        if any(output.stop for output in step_output):
                            logger.info(f"Early termination requested by step {step_name}")
                            break
                else:
                    all_results.append(step_output)
                    steps_step_outputs[step_name] = step_output

                    if step_output.stop:
                        logger.info(f"Early termination requested by step {step_name}")
                        break
                log_debug(f"Steps {self.name}: Step {step_name} completed successfully")

                # Update input for next step with proper chaining
                current_step_input = self._update_step_input_from_outputs(
                    current_step_input, step_output, steps_step_outputs
                )

            log_debug(f"Steps End: {self.name} ({len(all_results)} results)", center=True, symbol="-")
            return all_results

        except Exception as e:
            logger.error(f"Steps execution failed: {e}")
            return [
                StepOutput(
                    step_name=self.name or "Steps",
                    content=f"Steps execution failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
            ]

    def execute_stream(
        self,
        step_input: StepInput,
        workflow_run_response: WorkflowRunResponse,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        step_index: Optional[Union[int, tuple]] = None,
    ) -> Iterator[Union[WorkflowRunResponseEvent, TeamRunResponseEvent, RunResponseEvent, StepOutput]]:
        """Execute all steps in sequence with streaming support"""
        log_debug(f"Steps Start: {self.name} ({len(self.steps)} steps)", center=True, symbol="-")

        self._prepare_steps()

        if stream_intermediate_steps:
            # Yield steps execution started event
            yield StepsExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                steps_count=len(self.steps),
            )

        if not self.steps:
            yield StepOutput(step_name=self.name or "Steps", content="No steps to execute")
            return

        # Track outputs and pass data between steps - following Condition/Router pattern
        all_results = []
        current_step_input = step_input
        steps_step_outputs = {}

        try:
            for i, step in enumerate(self.steps):
                step_name = getattr(step, "name", f"step_{i + 1}")
                log_debug(f"Steps {self.name}: Executing step {i + 1}/{len(self.steps)} - {step_name}")

                step_outputs_for_step = []

                if step_index is None or isinstance(step_index, int):
                    # Steps is a main step - child steps get x.1, x.2, x.3 format
                    child_step_index = (step_index if step_index is not None else 1, i)  # Use i, not i+1
                else:
                    # Steps is already a child step - child steps get parent.1, parent.2, parent.3
                    child_step_index = step_index + (i,)  # Extend the tuple

                # Stream step execution
                for event in step.execute_stream(  # type: ignore
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

                # Update step outputs tracking and prepare input for next step
                if step_outputs_for_step:
                    if len(step_outputs_for_step) == 1:
                        steps_step_outputs[step_name] = step_outputs_for_step[0]

                        if step_outputs_for_step[0].stop:
                            logger.info(f"Early termination requested by step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step[0], steps_step_outputs
                        )
                    else:
                        # Use last output
                        steps_step_outputs[step_name] = step_outputs_for_step[-1]

                        if any(output.stop for output in step_outputs_for_step):
                            logger.info(f"Early termination requested by step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step, steps_step_outputs
                        )

            log_debug(f"Steps End: {self.name} ({len(all_results)} results)", center=True, symbol="-")

            if stream_intermediate_steps:
                # Yield steps execution completed event
                yield StepsExecutionCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name or "",
                    workflow_id=workflow_run_response.workflow_id or "",
                    session_id=workflow_run_response.session_id or "",
                    step_name=self.name,
                    step_index=step_index,
                    steps_count=len(self.steps),
                    executed_steps=len(all_results),
                    step_results=all_results,
                )

            for result in all_results:
                yield result

        except Exception as e:
            logger.error(f"Steps streaming failed: {e}")
            error_result = StepOutput(
                step_name=self.name or "Steps",
                content=f"Steps execution failed: {str(e)}",
                success=False,
                error=str(e),
            )
            yield error_result

    async def aexecute(
        self, step_input: StepInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> List[StepOutput]:
        """Execute all steps in sequence asynchronously and return the final result"""
        log_debug(f"Steps Start: {self.name} ({len(self.steps)} steps)", center=True, symbol="-")

        self._prepare_steps()

        if not self.steps:
            return [StepOutput(step_name=self.name or "Steps", content="No steps to execute")]

        # Track outputs and pass data between steps - following Condition/Router pattern
        all_results: List[StepOutput] = []
        current_step_input = step_input
        steps_step_outputs = {}

        try:
            for i, step in enumerate(self.steps):
                step_name = getattr(step, "name", f"step_{i + 1}")
                log_debug(f"Steps {self.name}: Executing async step {i + 1}/{len(self.steps)} - {step_name}")

                # Execute step
                step_output = await step.aexecute(current_step_input, session_id=session_id, user_id=user_id)  # type: ignore

                # Handle both single StepOutput and List[StepOutput] (from Loop/Condition/Router steps)
                if isinstance(step_output, list):
                    all_results.extend(step_output)
                    if step_output:
                        steps_step_outputs[step_name] = step_output[-1]

                        if any(output.stop for output in step_output):
                            logger.info(f"Early termination requested by step {step_name}")
                            break
                else:
                    all_results.append(step_output)
                    steps_step_outputs[step_name] = step_output

                    if step_output.stop:
                        logger.info(f"Early termination requested by step {step_name}")
                        break

                # Update input for next step with proper chaining
                current_step_input = self._update_step_input_from_outputs(
                    current_step_input, step_output, steps_step_outputs
                )

            log_debug(f"Steps End: {self.name} ({len(all_results)} results)", center=True, symbol="-")
            return all_results

        except Exception as e:
            logger.error(f"Async steps execution failed: {e}")
            return [
                StepOutput(
                    step_name=self.name or "Steps",
                    content=f"Steps execution failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
            ]

    async def aexecute_stream(
        self,
        step_input: StepInput,
        workflow_run_response: WorkflowRunResponse,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        step_index: Optional[Union[int, tuple]] = None,
    ) -> AsyncIterator[Union[WorkflowRunResponseEvent, TeamRunResponseEvent, RunResponseEvent, StepOutput]]:
        """Execute all steps in sequence with async streaming support"""
        log_debug(f"Steps Start: {self.name} ({len(self.steps)} steps)", center=True, symbol="-")

        self._prepare_steps()

        # Yield steps execution started event
        yield StepsExecutionStartedEvent(
            run_id=workflow_run_response.run_id or "",
            workflow_name=workflow_run_response.workflow_name or "",
            workflow_id=workflow_run_response.workflow_id or "",
            session_id=workflow_run_response.session_id or "",
            step_name=self.name,
            step_index=step_index,
            steps_count=len(self.steps),
        )

        if not self.steps:
            yield StepOutput(step_name=self.name or "Steps", content="No steps to execute")
            return

        # Track outputs and pass data between steps - following Condition/Router pattern
        all_results = []
        current_step_input = step_input
        steps_step_outputs = {}

        try:
            for i, step in enumerate(self.steps):
                step_name = getattr(step, "name", f"step_{i + 1}")
                log_debug(f"Steps {self.name}: Executing async step {i + 1}/{len(self.steps)} - {step_name}")

                step_outputs_for_step = []

                if step_index is None or isinstance(step_index, int):
                    # Steps is a main step - child steps get x.1, x.2, x.3 format
                    child_step_index = (step_index if step_index is not None else 1, i)  # Use i, not i+1
                else:
                    # Steps is already a child step - child steps get parent.1, parent.2, parent.3
                    child_step_index = step_index + (i,)  # Extend the tuple

                # Stream step execution
                async for event in step.aexecute_stream(  # type: ignore
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

                # Update step outputs tracking and prepare input for next step
                if step_outputs_for_step:
                    if len(step_outputs_for_step) == 1:
                        steps_step_outputs[step_name] = step_outputs_for_step[0]

                        if step_outputs_for_step[0].stop:
                            logger.info(f"Early termination requested by step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step[0], steps_step_outputs
                        )
                    else:
                        # Use last output
                        steps_step_outputs[step_name] = step_outputs_for_step[-1]

                        if any(output.stop for output in step_outputs_for_step):
                            logger.info(f"Early termination requested by step {step_name}")
                            break

                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step, steps_step_outputs
                        )

            log_debug(f"Steps End: {self.name} ({len(all_results)} results)", center=True, symbol="-")
            # Yield steps execution completed event
            yield StepsExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                steps_count=len(self.steps),
                executed_steps=len(all_results),
                step_results=all_results,
            )

            for result in all_results:
                yield result

        except Exception as e:
            logger.error(f"Async steps streaming failed: {e}")
            error_result = StepOutput(
                step_name=self.name or "Steps",
                content=f"Steps execution failed: {str(e)}",
                success=False,
                error=str(e),
            )
            yield error_result
