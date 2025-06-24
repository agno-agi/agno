import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Iterator, List, Optional, Union

from agno.run.response import RunResponseEvent
from agno.run.team import TeamRunResponseEvent
from agno.run.v2.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    WorkflowRunResponse,
    WorkflowRunResponseEvent,
)
from agno.utils.log import log_debug, logger
from agno.workflow.v2.loop import Loop
from agno.workflow.v2.step import Step
from agno.workflow.v2.types import StepInput, StepOutput

WorkflowSteps = List[
    Union[
        Callable[
            [StepInput], Union[StepOutput, Awaitable[StepOutput], Iterator[StepOutput], AsyncIterator[StepOutput]]
        ],
        Step,
        "Steps",  # noqa: F821
        "Loop",  # noqa: F821
        "Parallel",  # noqa: F821
        "Condition",  # noqa: F821
    ]
]


@dataclass
class Condition:
    """A condition that executes a step (or list of steps) if the condition is met"""

    # Evaluator can be a async or sync function, or a boolean
    # If it is a function, it has to return the step/steps to execute
    # If it is a boolean, it will be used to determine if all the provided steps should be executed
    evaluator: Union[
        Callable[[StepInput], Union[bool, Step, List[Step]]],
        Callable[[StepInput], Awaitable[Union[bool, Step, List[Step]]]],
        bool,
    ]
    steps: WorkflowSteps

    name: Optional[str] = None
    description: Optional[str] = None

    def _prepare_steps(self):
        """Prepare the steps for execution - mirrors workflow logic"""
        from agno.agent.agent import Agent
        from agno.team.team import Team
        from agno.workflow.v2.parallel import Parallel
        from agno.workflow.v2.step import Step

        prepared_steps = []
        for step in self.steps:
            if isinstance(step, Callable):
                prepared_steps.append(Step(name=step.__name__, description="User-defined callable step", executor=step))
            elif isinstance(step, Agent):
                prepared_steps.append(Step(name=step.name, description=step.description, agent=step))
            elif isinstance(step, Team):
                prepared_steps.append(Step(name=step.name, description=step.description, team=step))
            elif isinstance(step, (Step, Loop, Parallel, Condition)):
                prepared_steps.append(step)
            else:
                raise ValueError(f"Invalid step type: {type(step).__name__}")

        self.steps = prepared_steps

    def _update_step_input_from_outputs(
        self, step_input: StepInput, step_outputs: Union[StepOutput, List[StepOutput]]
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

        return StepInput(
            message=step_input.message,
            message_data=step_input.message_data,
            previous_step_content=previous_step_content,
            images=current_images + all_images,
            videos=current_videos + all_videos,
            audio=current_audio + all_audio,
        )

    def _evaluate_condition(self, step_input: StepInput) -> Union[bool, List[Step]]:
        """Evaluate the condition and return either a boolean or list of steps to execute"""
        if isinstance(self.evaluator, bool):
            return self.evaluator

        if callable(self.evaluator):
            result = self.evaluator(step_input)

            # Handle the result based on its type
            if isinstance(result, bool):
                return result
            elif isinstance(result, Step):
                return [result]
            elif isinstance(result, list):
                return result
            else:
                logger.warning(f"Condition evaluator returned unexpected type: {type(result)}")
                return False

        return False

    async def _aevaluate_condition(self, step_input: StepInput) -> Union[bool, List[Step]]:
        """Async version of condition evaluation"""
        if isinstance(self.evaluator, bool):
            return self.evaluator

        if callable(self.evaluator):
            if inspect.iscoroutinefunction(self.evaluator):
                result = await self.evaluator(step_input)
            else:
                result = self.evaluator(step_input)

            # Handle the result based on its type
            if isinstance(result, bool):
                return result
            elif isinstance(result, Step):
                return [result]
            elif isinstance(result, list):
                return result
            else:
                logger.warning(f"Condition evaluator returned unexpected type: {type(result)}")
                return False

        return False

    def _get_steps_to_execute(self, condition_result: Union[bool, List[Step]]) -> List[Step]:
        """Get the list of steps to execute based on condition result"""
        if isinstance(condition_result, bool):
            if condition_result:
                return self.steps
            else:
                return []
        elif isinstance(condition_result, list):
            return condition_result
        else:
            return []

    def execute(
        self, step_input: StepInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> List[StepOutput]:
        """Execute the condition and its steps with sequential chaining like Loop"""
        logger.info(f"Executing condition: {self.name}")

        self._prepare_steps()

        # Evaluate the condition
        condition_result = self._evaluate_condition(step_input)
        steps_to_execute = self._get_steps_to_execute(condition_result)

        logger.info(f"Condition {self.name} evaluated to: {len(steps_to_execute)} steps to execute")

        if not steps_to_execute:
            return []

        all_results = []
        current_step_input = step_input

        for i, step in enumerate(steps_to_execute):
            try:
                step_output = step.execute(current_step_input, session_id=session_id, user_id=user_id)

                # Handle both single StepOutput and List[StepOutput] (from Loop/Condition steps)
                if isinstance(step_output, list):
                    all_results.extend(step_output)
                else:
                    all_results.append(step_output)

                step_name = getattr(step, "name", f"step_{i}")
                logger.info(f"Condition step {step_name} completed")

                # Update step input for next step - mirrors Loop logic
                current_step_input = self._update_step_input_from_outputs(current_step_input, step_output)

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

        return all_results

    def execute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[int] = None,
    ) -> Iterator[Union[WorkflowRunResponseEvent, StepOutput]]:
        """Execute the condition with streaming support - mirrors Loop logic"""
        logger.info(f"Streaming condition: {self.name}")

        self._prepare_steps()

        # Evaluate the condition
        condition_result = self._evaluate_condition(step_input)
        steps_to_execute = self._get_steps_to_execute(condition_result)

        # Yield condition started event
        yield ConditionExecutionStartedEvent(
            run_id=workflow_run_response.run_id or "",
            workflow_name=workflow_run_response.workflow_name or "",
            workflow_id=workflow_run_response.workflow_id or "",
            session_id=workflow_run_response.session_id or "",
            step_name=self.name,
            step_index=step_index,
            condition_result=bool(steps_to_execute),
        )

        if not steps_to_execute:
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

        all_results = []
        current_step_input = step_input

        for i, step in enumerate(steps_to_execute):
            try:
                step_outputs_for_step = []
                # Stream step execution
                for event in step.execute_stream(
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=step_index,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs_for_step.append(event)
                        all_results.append(event)
                    else:
                        # Yield other events (streaming content, step events, etc.)
                        yield event

                step_name = getattr(step, "name", f"step_{i}")
                logger.info(f"Condition step {step_name} streaming completed")

                # Update step input for next step using all outputs from this step
                if step_outputs_for_step:
                    if len(step_outputs_for_step) == 1:
                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step[0]
                        )
                    else:
                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step
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

        # Yield condition completed event
        yield ConditionExecutionCompletedEvent(
            run_id=workflow_run_response.run_id or "",
            workflow_name=workflow_run_response.workflow_name or "",
            workflow_id=workflow_run_response.workflow_id or "",
            session_id=workflow_run_response.session_id or "",
            step_name=self.name,
            step_index=step_index,
            condition_result=True,
            executed_steps=len(steps_to_execute),
            step_results=all_results,  # Now returns all individual step results
        )

    async def aexecute(
        self, step_input: StepInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> List[StepOutput]:  # Changed to List[StepOutput]
        """Async execute the condition and its steps with sequential chaining"""
        logger.info(f"Async executing condition: {self.name}")

        self._prepare_steps()

        # Evaluate the condition
        condition_result = await self._aevaluate_condition(step_input)
        steps_to_execute = self._get_steps_to_execute(condition_result)

        logger.info(f"Condition {self.name} evaluated to: {len(steps_to_execute)} steps to execute")

        if not steps_to_execute:
            return []  # Return empty list

        # Chain steps sequentially like Loop does
        all_results = []
        current_step_input = step_input

        for i, step in enumerate(steps_to_execute):
            try:
                step_output = await step.aexecute(current_step_input, session_id=session_id, user_id=user_id)

                # Handle both single StepOutput and List[StepOutput]
                if isinstance(step_output, list):
                    all_results.extend(step_output)
                else:
                    all_results.append(step_output)

                step_name = getattr(step, "name", f"step_{i}")
                logger.info(f"Condition step {step_name} async completed")

                # Update step input for next step
                current_step_input = self._update_step_input_from_outputs(current_step_input, step_output)

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
                break  # Stop on first error

        return all_results

    async def aexecute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[int] = None,
    ) -> AsyncIterator[Union[WorkflowRunResponseEvent, TeamRunResponseEvent, RunResponseEvent, StepOutput]]:
        """Async execute the condition with streaming support - mirrors Loop logic"""
        logger.info(f"Async streaming condition: {self.name}")

        self._prepare_steps()

        # Evaluate the condition
        condition_result = await self._aevaluate_condition(step_input)
        steps_to_execute = self._get_steps_to_execute(condition_result)

        # Yield condition started event
        yield ConditionExecutionStartedEvent(
            run_id=workflow_run_response.run_id or "",
            workflow_name=workflow_run_response.workflow_name or "",
            workflow_id=workflow_run_response.workflow_id or "",
            session_id=workflow_run_response.session_id or "",
            step_name=self.name,
            step_index=step_index,
            condition_result=bool(steps_to_execute),
        )

        if not steps_to_execute:
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

        # Chain steps sequentially like Loop does
        all_results = []
        current_step_input = step_input

        for i, step in enumerate(steps_to_execute):
            try:
                step_outputs_for_step = []

                # Stream step execution - mirroring Loop logic
                async for event in step.aexecute_stream(
                    current_step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=step_index,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs_for_step.append(event)
                        all_results.append(event)
                    else:
                        # Yield other events (streaming content, step events, etc.)
                        yield event

                step_name = getattr(step, "name", f"step_{i}")
                logger.info(f"Condition step {step_name} async streaming completed")

                # Update step input for next step using all outputs from this step
                if step_outputs_for_step:
                    if len(step_outputs_for_step) == 1:
                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step[0]
                        )
                    else:
                        current_step_input = self._update_step_input_from_outputs(
                            current_step_input, step_outputs_for_step
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
                break  # Stop on first error

        # Yield condition completed event
        yield ConditionExecutionCompletedEvent(
            run_id=workflow_run_response.run_id or "",
            workflow_name=workflow_run_response.workflow_name or "",
            workflow_id=workflow_run_response.workflow_id or "",
            session_id=workflow_run_response.session_id or "",
            step_name=self.name,
            step_index=step_index,
            condition_result=True,
            executed_steps=len(steps_to_execute),
            step_results=all_results,  # Now returns all individual step results
        )
