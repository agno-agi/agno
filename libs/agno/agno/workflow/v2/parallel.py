import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Iterator, List, Optional, Union

from agno.run.response import RunResponseEvent
from agno.run.team import TeamRunResponseEvent
from agno.run.v2.workflow import WorkflowRunResponse, WorkflowRunResponseEvent
from agno.utils.log import log_debug, logger
from agno.workflow.v2.condition import Condition
from agno.workflow.v2.loop import Loop
from agno.workflow.v2.step import Step
from agno.workflow.v2.steps import Steps
from agno.workflow.v2.types import StepInput, StepOutput

WorkflowSteps = List[
    Union[
        Callable[
            [StepInput], Union[StepOutput, Awaitable[StepOutput], Iterator[StepOutput], AsyncIterator[StepOutput]]
        ],
        Step,
        "Steps",
        "Loop",
        "Parallel",
        "Condition",
    ]
]


@dataclass
class Parallel:
    """A list of steps that execute in parallel"""

    steps: WorkflowSteps

    name: Optional[str] = None
    description: Optional[str] = None

    def __init__(
        self,
        *steps: Union[Step, "Steps", "Loop", "Parallel", "Condition"],
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        self.steps = list(steps)
        self.name = name
        self.description = description

    def execute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[StepOutput]:
        """Execute all steps in parallel using ThreadPoolExecutor"""
        logger.info(f"Executing {len(self.steps)} steps in parallel: {self.name}")

        def execute_step(step: Step) -> StepOutput:
            """Execute a single step"""
            try:
                return step.execute(step_input, session_id=session_id, user_id=user_id)
            except Exception as e:
                logger.error(f"Parallel step {step.name} failed: {e}")
                # Return error StepOutput instead of raising
                return StepOutput(
                    step_name=step.name, content=f"Step {step.name} failed: {str(e)}", success=False, error=str(e)
                )

        results = []
        with ThreadPoolExecutor(max_workers=len(self.steps)) as executor:
            # Submit all tasks
            future_to_step = {
                executor.submit(execute_step, step): step for step in self.steps if isinstance(step, Step)
            }

            # Collect results as they complete
            for future in as_completed(future_to_step):
                step = future_to_step[future]
                try:
                    result = future.result()
                    results.append(result)
                    log_debug(f"Parallel step {step.name} completed")
                except Exception as e:
                    logger.error(f"Parallel step {step.name} failed: {e}")
                    # Add error result
                    results.append(
                        StepOutput(
                            step_name=step.name,
                            content=f"Step {step.name} failed: {str(e)}",
                            success=False,
                            error=str(e),
                        )
                    )

        # Sort results by original step order
        step_name_to_index = {step.name: i for i, step in enumerate(self.steps) if isinstance(step, Step)}
        results.sort(key=lambda x: step_name_to_index.get(x.step_name, 999))

        log_debug(f"Parallel execution completed with {len(results)} results")
        return results

    def execute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[int] = None,
    ) -> Iterator[Union[WorkflowRunResponseEvent, TeamRunResponseEvent, RunResponseEvent, StepOutput]]:
        """Execute all steps in parallel with streaming support"""
        log_debug(f"Streaming {len(self.steps)} steps in parallel: {self.name}")

        def execute_step_stream(step: Step):
            """Execute a single step with streaming"""
            try:
                events = []
                for event in step.execute_stream(
                    step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=step_index,
                ):
                    events.append(event)
                return events
            except Exception as e:
                logger.error(f"Parallel step {step.name} streaming failed: {e}")
                return [
                    StepOutput(
                        step_name=step.name, content=f"Step {step.name} failed: {str(e)}", success=False, error=str(e)
                    )
                ]

        all_events = []
        with ThreadPoolExecutor(max_workers=len(self.steps)) as executor:
            # Submit all tasks
            future_to_step = {
                executor.submit(execute_step_stream, step): step for step in self.steps if isinstance(step, Step)
            }

            # Collect results as they complete
            for future in as_completed(future_to_step):
                step = future_to_step[future]
                try:
                    events = future.result()
                    all_events.extend(events)
                    log_debug(f"Parallel step {step.name} streaming completed")
                except Exception as e:
                    logger.error(f"Parallel step {step.name} streaming failed: {e}")
                    all_events.append(
                        StepOutput(
                            step_name=step.name,
                            content=f"Step {step.name} failed: {str(e)}",
                            success=False,
                            error=str(e),
                        )
                    )

        # Yield all collected events
        for event in all_events:
            yield event

    async def aexecute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[StepOutput]:
        """Execute all steps in parallel using asyncio"""
        logger.info(f"Async executing {len(self.steps)} steps in parallel: {self.name}")

        async def execute_step_async(step: Step) -> StepOutput:
            """Execute a single step asynchronously"""
            try:
                return await step.aexecute(step_input, session_id=session_id, user_id=user_id)
            except Exception as e:
                logger.error(f"Parallel step {step.name} failed: {e}")
                return StepOutput(
                    step_name=step.name, content=f"Step {step.name} failed: {str(e)}", success=False, error=str(e)
                )

        # Create tasks for all steps
        tasks = [execute_step_async(step) for step in self.steps if isinstance(step, Step)]

        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                step_name = self.steps[i].name if i < len(self.steps) else f"step_{i}"
                logger.error(f"Parallel step {step_name} failed: {result}")
                processed_results.append(
                    StepOutput(
                        step_name=step_name,
                        content=f"Step {step_name} failed: {str(result)}",
                        success=False,
                        error=str(result),
                    )
                )
            else:
                processed_results.append(result)

        log_debug(f"Parallel async execution completed with {len(processed_results)} results")
        return processed_results

    async def aexecute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[int] = None,
    ) -> AsyncIterator[Union[WorkflowRunResponseEvent, TeamRunResponseEvent, RunResponseEvent, StepOutput]]:
        """Execute all steps in parallel with async streaming support"""
        log_debug(f"Async streaming {len(self.steps)} steps in parallel: {self.name}")

        async def execute_step_stream_async(step: Step):
            """Execute a single step with async streaming"""
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
                return events
            except Exception as e:
                logger.error(f"Parallel step {step.name} async streaming failed: {e}")
                return [
                    StepOutput(
                        step_name=step.name, content=f"Step {step.name} failed: {str(e)}", success=False, error=str(e)
                    )
                ]

        # Create tasks for all steps
        tasks = [execute_step_stream_async(step) for step in self.steps if isinstance(step, Step)]

        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process and yield all events
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Parallel step streaming failed: {result}")
                yield StepOutput(content=f"Parallel step failed: {str(result)}", success=False, error=str(result))
            else:
                for event in result:
                    yield event
