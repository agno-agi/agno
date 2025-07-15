import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Union

from agno.run.response import RunResponseEvent
from agno.run.team import TeamRunResponseEvent
from agno.run.v2.workflow import (
    ParallelExecutionCompletedEvent,
    ParallelExecutionStartedEvent,
    WorkflowRunResponse,
    WorkflowRunResponseEvent,
)
from agno.utils.log import log_debug, logger
from agno.workflow.v2.condition import Condition
from agno.workflow.v2.step import Step
from agno.workflow.v2.steps import Steps
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
class Parallel:
    """A list of steps that execute in parallel"""

    steps: WorkflowSteps

    name: Optional[str] = None
    description: Optional[str] = None

    def __init__(
        self,
        *steps: WorkflowSteps,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        self.steps = list(steps)
        self.name = name
        self.description = description

    def _prepare_steps(self):
        """Prepare the steps for execution - mirrors workflow logic"""
        from agno.agent.agent import Agent
        from agno.team.team import Team
        from agno.workflow.v2.loop import Loop
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

    def _aggregate_results(self, step_outputs: List[StepOutput]) -> StepOutput:
        """Aggregate multiple step outputs into a single StepOutput"""
        if not step_outputs:
            return StepOutput(step_name=self.name or "Parallel", content="No parallel steps executed")

        # To store the individual step outputs for each parallel step
        parallel_step_outputs = {output.step_name or f"step_{i}": output for i, output in enumerate(step_outputs)}

        if len(step_outputs) == 1:
            # Single result, update the step name but preserve parallel structure
            single_result = step_outputs[0]

            # Extract metrics using the dedicated method
            aggregated_metrics = self._extract_metrics_from_response(step_outputs)

            return StepOutput(
                step_name=self.name or "Parallel",
                content=single_result.content,
                parallel_step_outputs=parallel_step_outputs,
                response=single_result.response,
                images=single_result.images,
                videos=single_result.videos,
                audio=single_result.audio,
                metrics=aggregated_metrics,
                success=single_result.success,
                error=single_result.error,
                stop=single_result.stop,
            )

        early_termination_requested = any(output.stop for output in step_outputs if hasattr(output, "stop"))

        # Multiple results - aggregate them
        aggregated_content = self._build_aggregated_content(step_outputs)

        # Combine all media from parallel steps
        all_images = []
        all_videos = []
        all_audio = []
        has_any_failure = False

        for result in step_outputs:
            all_images.extend(result.images or [])
            all_videos.extend(result.videos or [])
            all_audio.extend(result.audio or [])
            if result.success is False:
                has_any_failure = True

        # Extract metrics using the dedicated method
        aggregated_metrics = self._extract_metrics_from_response(step_outputs)

        return StepOutput(
            step_name=self.name or "Parallel",
            content=aggregated_content,
            parallel_step_outputs=parallel_step_outputs,
            images=all_images if all_images else None,
            videos=all_videos if all_videos else None,
            audio=all_audio if all_audio else None,
            success=not has_any_failure,
            stop=early_termination_requested,
            metrics=aggregated_metrics,
        )

    def _extract_metrics_from_response(self, step_outputs: List[StepOutput]) -> Optional[Dict[str, Any]]:
        """Extract and aggregate metrics from parallel step outputs"""
        if not step_outputs:
            return None

        parallel_step_metrics = {}

        for result in step_outputs:
            step_name = result.step_name or "unknown"

            # Create clean step metrics for parallel steps
            if result.metrics:
                # If the step already has structured metrics, extract the actual metrics
                if isinstance(result.metrics, dict) and "metrics" in result.metrics:
                    actual_metrics = result.metrics.get("metrics")
                    executor_type = result.metrics.get("executor_type", "unknown")
                    executor_name = result.metrics.get("executor_name", "unknown")
                else:
                    actual_metrics = result.metrics
                    executor_type = getattr(result, "executor_type", "unknown")
                    executor_name = getattr(result, "executor_name", "unknown")

                parallel_step_metrics[step_name] = {
                    "step_name": step_name,
                    "executor_type": executor_type,
                    "executor_name": executor_name,
                    "metrics": actual_metrics,
                }
            else:
                # Even if no metrics, record the step execution
                parallel_step_metrics[step_name] = {
                    "step_name": step_name,
                    "executor_type": getattr(result, "executor_type", "unknown"),
                    "executor_name": getattr(result, "executor_name", "unknown"),
                    "metrics": None,
                }

        # Create aggregated metrics structure for parallel execution
        if parallel_step_metrics:
            return {
                "step_name": self.name or "Parallel",
                "executor_type": "parallel",
                "executor_name": self.name or "Parallel",
                "parallel_steps": parallel_step_metrics,
            }

        return None

    def _build_aggregated_content(self, step_outputs: List[StepOutput]) -> str:
        """Build aggregated content from multiple step outputs"""
        aggregated = "## Parallel Execution Results\n\n"

        for i, output in enumerate(step_outputs):
            step_name = output.step_name or f"Step {i + 1}"
            content = output.content or ""

            # Add status indicator
            if output.success is False:
                status_icon = "❌ FAILURE:"
            else:
                status_icon = "✅ SUCCESS:"

            aggregated += f"### {status_icon} {step_name}\n"
            if content and str(content).strip():
                aggregated += f"{content}\n\n"
            else:
                aggregated += "*(No content)*\n\n"

        return aggregated.strip()

    def execute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> StepOutput:
        """Execute all steps in parallel and return aggregated result"""
        # Use workflow logger for parallel orchestration
        log_debug(f"Parallel Start: {self.name} ({len(self.steps)} steps)", center=True, symbol="=")

        self._prepare_steps()

        def execute_step_with_index(step_with_index):
            """Execute a single step and preserve its original index"""
            index, step = step_with_index
            try:
                result = step.execute(step_input, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
                return (index, result)
            except Exception as e:
                step_name = getattr(step, "name", f"step_{index}")
                logger.error(f"Parallel step {step_name} failed: {e}")
                return (
                    index,
                    StepOutput(
                        step_name=step_name, content=f"Step {step_name} failed: {str(e)}", success=False, error=str(e)
                    ),
                )

        # Use index to preserve order
        indexed_steps = list(enumerate(self.steps))

        with ThreadPoolExecutor(max_workers=len(self.steps)) as executor:
            # Submit all tasks with their original indices
            future_to_index = {
                executor.submit(execute_step_with_index, indexed_step): indexed_step[0]
                for indexed_step in indexed_steps
            }

            # Collect results
            results_with_indices = []
            for future in as_completed(future_to_index):
                try:
                    index, result = future.result()
                    results_with_indices.append((index, result))
                    step_name = getattr(self.steps[index], "name", f"step_{index}")
                    log_debug(f"Parallel step {step_name} completed")
                except Exception as e:
                    index = future_to_index[future]
                    step_name = getattr(self.steps[index], "name", f"step_{index}")
                    logger.error(f"Parallel step {step_name} failed: {e}")
                    results_with_indices.append(
                        (
                            index,
                            StepOutput(
                                step_name=step_name,
                                content=f"Step {step_name} failed: {str(e)}",
                                success=False,
                                error=str(e),
                            ),
                        )
                    )

        # Sort by original index to preserve order
        results_with_indices.sort(key=lambda x: x[0])
        results = [result for _, result in results_with_indices]

        # Flatten results - handle steps that return List[StepOutput] (like Condition/Loop)
        flattened_results: List[StepOutput] = []
        for result in results:
            if isinstance(result, list):
                flattened_results.extend(result)
            else:
                flattened_results.append(result)

        # Aggregate all results into a single StepOutput
        aggregated_result = self._aggregate_results(flattened_results)

        # Use workflow logger for parallel completion
        log_debug(f"Parallel End: {self.name} ({len(self.steps)} steps)", center=True, symbol="=")

        return aggregated_result

    def execute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[Union[int, tuple]] = None,
    ) -> Iterator[Union[WorkflowRunResponseEvent, StepOutput]]:
        """Execute all steps in parallel with streaming support"""
        log_debug(f"Parallel Start: {self.name} ({len(self.steps)} steps)", center=True, symbol="=")

        self._prepare_steps()

        if stream_intermediate_steps and workflow_run_response:
            # Yield parallel step started event
            yield ParallelExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                parallel_step_count=len(self.steps),
            )

        def execute_step_stream_with_index(step_with_index):
            """Execute a single step with streaming and preserve its original index"""
            index, step = step_with_index
            try:
                events = []

                # If step_index is None or integer (main step): create (step_index, sub_index)
                # If step_index is tuple (child step): all parallel sub-steps get same index
                if step_index is None or isinstance(step_index, int):
                    # Parallel is a main step - sub-steps get sequential numbers: 1.1, 1.2, 1.3
                    sub_step_index = (step_index if step_index is not None else 0, index)
                else:
                    # Parallel is a child step - all sub-steps get the same parent number: 1.1, 1.1, 1.1
                    sub_step_index = step_index

                # All workflow step types have execute_stream() method
                for event in step.execute_stream(  # type: ignore[union-attr]
                    step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=sub_step_index,
                ):
                    events.append(event)
                return (index, events)
            except Exception as e:
                step_name = getattr(step, "name", f"step_{index}")
                logger.error(f"Parallel step {step_name} streaming failed: {e}")
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

        # Use index to preserve order
        indexed_steps = list(enumerate(self.steps))
        all_events_with_indices = []
        step_results = []

        with ThreadPoolExecutor(max_workers=len(self.steps)) as executor:
            # Submit all tasks with their original indices
            future_to_index = {
                executor.submit(execute_step_stream_with_index, indexed_step): indexed_step[0]
                for indexed_step in indexed_steps
            }

            # Collect results as they complete
            for future in as_completed(future_to_index):
                try:
                    index, events = future.result()
                    all_events_with_indices.append((index, events))

                    # Extract StepOutput from events for the final result
                    step_outputs = [event for event in events if isinstance(event, StepOutput)]
                    if step_outputs:
                        step_results.extend(step_outputs)

                    step_name = getattr(self.steps[index], "name", f"step_{index}")
                    log_debug(f"Parallel step {step_name} streaming completed")
                except Exception as e:
                    index = future_to_index[future]
                    step_name = getattr(self.steps[index], "name", f"step_{index}")
                    logger.error(f"Parallel step {step_name} streaming failed: {e}")
                    error_event = StepOutput(
                        step_name=step_name,
                        content=f"Step {step_name} failed: {str(e)}",
                        success=False,
                        error=str(e),
                    )
                    all_events_with_indices.append((index, [error_event]))
                    step_results.append(error_event)

        # Sort events by original index to preserve order
        all_events_with_indices.sort(key=lambda x: x[0])

        # Yield all collected streaming events in order (but not final StepOutputs)
        for _, events in all_events_with_indices:
            for event in events:
                # Only yield non-StepOutput events during streaming to avoid duplication
                if not isinstance(event, StepOutput):
                    yield event

        # Flatten step_results - handle steps that return List[StepOutput] (like Condition/Loop)
        flattened_step_results: List[StepOutput] = []
        for result in step_results:
            if isinstance(result, list):
                flattened_step_results.extend(result)
            else:
                flattened_step_results.append(result)

        # Create aggregated result from all step outputs
        aggregated_result = self._aggregate_results(flattened_step_results)

        # Yield the final aggregated StepOutput
        yield aggregated_result

        log_debug(f"Parallel End: {self.name} ({len(self.steps)} steps)", center=True, symbol="=")

        if stream_intermediate_steps and workflow_run_response:
            # Yield parallel step completed event
            yield ParallelExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                parallel_step_count=len(self.steps),
                step_results=[aggregated_result],  # Now single aggregated result
            )

    async def aexecute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> StepOutput:
        """Execute all steps in parallel using asyncio and return aggregated result"""
        # Use workflow logger for async parallel orchestration
        log_debug(f"Parallel Start: {self.name} ({len(self.steps)} steps)", center=True, symbol="=")

        self._prepare_steps()

        async def execute_step_async_with_index(step_with_index):
            """Execute a single step asynchronously and preserve its original index"""
            index, step = step_with_index
            try:
                result = await step.aexecute(step_input, session_id=session_id, user_id=user_id)  # type: ignore[union-attr]
                return (index, result)
            except Exception as e:
                step_name = getattr(step, "name", f"step_{index}")
                logger.error(f"Parallel step {step_name} failed: {e}")
                return (
                    index,
                    StepOutput(
                        step_name=step_name,
                        content=f"Step {step_name} failed: {str(e)}",
                        success=False,
                        error=str(e),
                    ),
                )

        # Use index to preserve order
        indexed_steps = list(enumerate(self.steps))

        # Create tasks for all steps with their indices
        tasks = [execute_step_async_with_index(indexed_step) for indexed_step in indexed_steps]

        # Execute all tasks concurrently
        results_with_indices = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and handle exceptions, preserving order
        processed_results_with_indices = []
        for i, result in enumerate(results_with_indices):
            if isinstance(result, Exception):
                step_name = getattr(self.steps[i], "name", f"step_{i}")
                logger.error(f"Parallel step {step_name} failed: {result}")
                processed_results_with_indices.append(
                    (
                        i,
                        StepOutput(
                            step_name=step_name,
                            content=f"Step {step_name} failed: {str(result)}",
                            success=False,
                            error=str(result),
                        ),
                    )
                )
            else:
                index, step_result = result  # type: ignore[misc]
                processed_results_with_indices.append((index, step_result))
                step_name = getattr(self.steps[index], "name", f"step_{index}")
                log_debug(f"Parallel step {step_name} completed")

        # Sort by original index to preserve order
        processed_results_with_indices.sort(key=lambda x: x[0])
        results = [result for _, result in processed_results_with_indices]

        # Flatten results - handle steps that return List[StepOutput] (like Condition/Loop)
        flattened_results: List[StepOutput] = []
        for result in results:
            if isinstance(result, list):
                flattened_results.extend(result)
            else:
                flattened_results.append(result)

        # Aggregate all results into a single StepOutput
        aggregated_result = self._aggregate_results(flattened_results)

        # Use workflow logger for async parallel completion
        log_debug(f"Parallel End: {self.name} ({len(self.steps)} steps)", center=True, symbol="=")

        return aggregated_result

    async def aexecute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        workflow_run_response: Optional[WorkflowRunResponse] = None,
        step_index: Optional[Union[int, tuple]] = None,
    ) -> AsyncIterator[Union[WorkflowRunResponseEvent, TeamRunResponseEvent, RunResponseEvent, StepOutput]]:
        """Execute all steps in parallel with async streaming support"""
        log_debug(f"Parallel Start: {self.name} ({len(self.steps)} steps)", center=True, symbol="=")

        self._prepare_steps()

        if stream_intermediate_steps and workflow_run_response:
            # Yield parallel step started event
            yield ParallelExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                parallel_step_count=len(self.steps),
            )

        async def execute_step_stream_async_with_index(step_with_index):
            """Execute a single step with async streaming and preserve its original index"""
            index, step = step_with_index
            try:
                events = []

                # If step_index is None or integer (main step): create (step_index, sub_index)
                # If step_index is tuple (child step): all parallel sub-steps get same index
                if step_index is None or isinstance(step_index, int):
                    # Parallel is a main step - sub-steps get sequential numbers: 1.1, 1.2, 1.3
                    sub_step_index = (step_index if step_index is not None else 0, index)
                else:
                    # Parallel is a child step - all sub-steps get the same parent number: 1.1, 1.1, 1.1
                    sub_step_index = step_index

                # All workflow step types have aexecute_stream() method
                async for event in step.aexecute_stream(
                    step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                    workflow_run_response=workflow_run_response,
                    step_index=sub_step_index,
                ):  # type: ignore[union-attr]
                    events.append(event)
                return (index, events)
            except Exception as e:
                step_name = getattr(step, "name", f"step_{index}")
                logger.error(f"Parallel step {step_name} async streaming failed: {e}")
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

        # Use index to preserve order
        indexed_steps = list(enumerate(self.steps))
        all_events_with_indices = []
        step_results = []

        # Create tasks for all steps with their indices
        tasks = [execute_step_stream_async_with_index(indexed_step) for indexed_step in indexed_steps]

        # Execute all tasks concurrently
        results_with_indices = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and handle exceptions, preserving order
        for i, result in enumerate(results_with_indices):
            if isinstance(result, Exception):
                step_name = getattr(self.steps[i], "name", f"step_{i}")
                logger.error(f"Parallel step {step_name} async streaming failed: {result}")
                error_event = StepOutput(
                    step_name=step_name,
                    content=f"Step {step_name} failed: {str(result)}",
                    success=False,
                    error=str(result),
                )
                all_events_with_indices.append((i, [error_event]))
                step_results.append(error_event)
            else:
                index, events = result  # type: ignore[misc]
                all_events_with_indices.append((index, events))

                # Extract StepOutput from events for the final result
                step_outputs = [event for event in events if isinstance(event, StepOutput)]
                if step_outputs:
                    step_results.extend(step_outputs)

                step_name = getattr(self.steps[index], "name", f"step_{index}")
                log_debug(f"Parallel step {step_name} async streaming completed")

        # Sort events by original index to preserve order
        all_events_with_indices.sort(key=lambda x: x[0])

        # Yield all collected streaming events in order (but not final StepOutputs)
        for _, events in all_events_with_indices:
            for event in events:
                # Only yield non-StepOutput events during streaming to avoid duplication
                if not isinstance(event, StepOutput):
                    yield event

        # Flatten step_results - handle steps that return List[StepOutput] (like Condition/Loop)
        flattened_step_results: List[StepOutput] = []
        for result in step_results:
            if isinstance(result, list):
                flattened_step_results.extend(result)
            else:
                flattened_step_results.append(result)

        # Create aggregated result from all step outputs
        aggregated_result = self._aggregate_results(flattened_step_results)

        # Yield the final aggregated StepOutput
        yield aggregated_result

        log_debug(f"Parallel End: {self.name} ({len(self.steps)} steps)", center=True, symbol="=")

        if stream_intermediate_steps and workflow_run_response:
            # Yield parallel step completed event
            yield ParallelExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                parallel_step_count=len(self.steps),
                step_results=[aggregated_result],  # Now single aggregated result
            )
