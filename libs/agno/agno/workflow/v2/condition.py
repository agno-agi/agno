import asyncio
import inspect
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    def _build_aggregated_content(self, step_outputs: List[StepOutput]) -> str:
        """Build aggregated content from multiple step outputs"""
        if not step_outputs:
            return "Condition was not met - no steps executed."

        aggregated = "## Condition Execution Results\n\n"

        for i, output in enumerate(step_outputs):
            step_name = output.step_name or f"Step {i + 1}"
            content = output.content or ""

            # Add status indicator
            if output.success is False:
                status_icon = "❌ FAILURE:"
            else:
                status_icon = "✅ SUCCESS:"

            aggregated += f"### {status_icon} {step_name}\n"
            if content.strip():
                aggregated += f"{content}\n\n"
            else:
                aggregated += "*(No content)*\n\n"

        return aggregated.strip()

    def _aggregate_results(self, step_outputs: List[StepOutput]) -> StepOutput:
        """Aggregate multiple step outputs into a single result"""
        if not step_outputs:
            return StepOutput(
                step_name=self.name or "Condition",
                content="Condition was not met - no steps executed.",
                success=True,
                images=[],
                videos=[],
                audio=[],
            )

        # Aggregate content
        aggregated_content = self._build_aggregated_content(step_outputs)

        # Aggregate media
        all_images = []
        all_videos = []
        all_audio = []

        for output in step_outputs:
            if output.images:
                all_images.extend(output.images)
            if output.videos:
                all_videos.extend(output.videos)
            if output.audio:
                all_audio.extend(output.audio)

        # Check if any step failed
        has_failures = any(output.success is False for output in step_outputs)

        return StepOutput(
            step_name=self.name or "Condition",
            content=aggregated_content,
            success=not has_failures,
            images=all_images,
            videos=all_videos,
            audio=all_audio,
        )

    def execute(
        self, step_input: StepInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> StepOutput:
        """Execute the condition and its steps"""
        logger.info(f"Executing condition: {self.name}")

        # Evaluate the condition
        condition_result = self._evaluate_condition(step_input)
        steps_to_execute = self._get_steps_to_execute(condition_result)

        logger.info(f"Condition {self.name} evaluated to: {len(steps_to_execute)} steps to execute")

        if not steps_to_execute:
            return StepOutput(
                step_name=self.name or "Condition",
                content="Condition was not met - no steps executed.",
                success=True,
                images=[],
                videos=[],
                audio=[],
            )

        # Execute the steps
        step_outputs = []
        for i, step in enumerate(steps_to_execute):
            try:
                result = step.execute(step_input, session_id=session_id, user_id=user_id)
                step_outputs.append(result)
                step_name = getattr(step, "name", f"step_{i}")
                logger.info(f"Condition step {step_name} completed")
            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Condition step {step_name} failed: {e}")
                step_outputs.append(
                    StepOutput(
                        step_name=step_name,
                        content=f"Step {step_name} failed: {str(e)}",
                        success=False,
                        error=str(e),
                    )
                )

        return self._aggregate_results(step_outputs)

    def execute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[int] = None,
    ) -> Iterator[Union[WorkflowRunResponseEvent, StepOutput]]:
        """Execute the condition with streaming support"""
        logger.info(f"Streaming condition: {self.name}")

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
            result = StepOutput(
                step_name=self.name or "Condition",
                content="Condition was not met - no steps executed.",
                success=True,
                images=[],
                videos=[],
                audio=[],
            )
            yield result

            # Yield condition completed event
            yield ConditionExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                condition_result=False,
                executed_steps=0,
                step_results=[result],
            )
            return

        # Execute the steps with streaming
        step_outputs = []
        for i, step in enumerate(steps_to_execute):
            try:
                # Stream each step
                for event in step.execute_stream(
                    step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=step_index,
                ):
                    if isinstance(event, StepOutput):
                        step_outputs.append(event)
                    else:
                        # Only yield events with content attribute to avoid errors
                        if hasattr(event, "content"):
                            yield event

                step_name = getattr(step, "name", f"step_{i}")
                logger.info(f"Condition step {step_name} streaming completed")
            except Exception as e:
                step_name = getattr(step, "name", f"step_{i}")
                logger.error(f"Condition step {step_name} streaming failed: {e}")
                error_output = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                step_outputs.append(error_output)

        # Create aggregated result
        aggregated_result = self._aggregate_results(step_outputs)
        yield aggregated_result

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
            step_results=[aggregated_result],
        )

    async def aexecute(
        self, step_input: StepInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> StepOutput:
        """Async execute the condition and its steps"""
        logger.info(f"Async executing condition: {self.name}")

        # Evaluate the condition
        condition_result = await self._aevaluate_condition(step_input)
        steps_to_execute = self._get_steps_to_execute(condition_result)

        logger.info(f"Condition {self.name} evaluated to: {len(steps_to_execute)} steps to execute")

        if not steps_to_execute:
            return StepOutput(
                step_name=self.name or "Condition",
                content="Condition was not met - no steps executed.",
                success=True,
                images=[],
                videos=[],
                audio=[],
            )

        # Execute the steps concurrently
        async def execute_step_async(step, index):
            try:
                result = await step.aexecute(step_input, session_id=session_id, user_id=user_id)
                step_name = getattr(step, "name", f"step_{index}")
                logger.info(f"Condition step {step_name} async completed")
                return result
            except Exception as e:
                step_name = getattr(step, "name", f"step_{index}")
                logger.error(f"Condition step {step_name} async failed: {e}")
                return StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )

        # Execute all steps concurrently
        tasks = [execute_step_async(step, i) for i, step in enumerate(steps_to_execute)]
        step_outputs = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any exceptions that were returned
        processed_outputs = []
        for i, output in enumerate(step_outputs):
            if isinstance(output, Exception):
                step_name = getattr(steps_to_execute[i], "name", f"step_{i}")
                logger.error(f"Condition step {step_name} async failed: {output}")
                processed_outputs.append(
                    StepOutput(
                        step_name=step_name,
                        content=f"Step {step_name} failed: {str(output)}",
                        success=False,
                        error=str(output),
                    )
                )
            else:
                processed_outputs.append(output)

        return self._aggregate_results(processed_outputs)

    async def aexecute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[int] = None,
    ) -> AsyncIterator[Union[WorkflowRunResponseEvent, TeamRunResponseEvent, RunResponseEvent, StepOutput]]:
        """Async execute the condition with streaming support"""
        logger.info(f"Async streaming condition: {self.name}")

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
            result = StepOutput(
                step_name=self.name or "Condition",
                content="Condition was not met - no steps executed.",
                success=True,
                images=[],
                videos=[],
                audio=[],
            )
            yield result

            # Yield condition completed event
            yield ConditionExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                condition_result=False,
                executed_steps=0,
                step_results=[result],
            )
            return

        # Execute the steps with async streaming
        async def execute_step_stream_async(step, index):
            try:
                events = []
                async for event in step.aexecute_stream(
                    step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=step_index,
                ):
                    events.append(event)
                return (index, events)
            except Exception as e:
                step_name = getattr(step, "name", f"step_{index}")
                logger.error(f"Condition step {step_name} async streaming failed: {e}")
                return (
                    index,
                    [
                        StepOutput(
                            step_name=step_name,
                            content=f"Step {step_name} failed: {str(e)}",
                            success=False,
                            error=str(e),
                        )
                    ],
                )

        # Execute all steps concurrently
        tasks = [execute_step_stream_async(step, i) for i, step in enumerate(steps_to_execute)]
        results_with_indices = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and handle exceptions, preserving order
        all_events_with_indices = []
        step_results = []
        for i, result in enumerate(results_with_indices):
            if isinstance(result, Exception):
                step_name = getattr(steps_to_execute[i], "name", f"step_{i}")
                logger.error(f"Condition step {step_name} async streaming failed: {result}")
                error_event = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(result)}",
                    success=False,
                    error=str(result),
                )
                all_events_with_indices.append((i, [error_event]))
                step_results.append(error_event)
            else:
                index, events = result
                all_events_with_indices.append((index, events))

                # Extract StepOutput from events for the final result
                step_outputs = [event for event in events if isinstance(event, StepOutput)]
                if step_outputs:
                    step_results.extend(step_outputs)

                step_name = getattr(steps_to_execute[index], "name", f"step_{index}")
                logger.info(f"Condition step {step_name} async streaming completed")

        # Sort events by original index to preserve order
        all_events_with_indices.sort(key=lambda x: x[0])

        # Yield all collected streaming events in order (but not final StepOutputs)
        for _, events in all_events_with_indices:
            for event in events:
                # Only yield non-StepOutput events during streaming to avoid duplication
                # and only yield events with content attribute to avoid errors
                if not isinstance(event, StepOutput) and hasattr(event, "content"):
                    yield event

        # Create aggregated result from all step outputs
        aggregated_result = self._aggregate_results(step_results)

        # Yield the final aggregated StepOutput
        yield aggregated_result

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
            step_results=[aggregated_result],
        )
