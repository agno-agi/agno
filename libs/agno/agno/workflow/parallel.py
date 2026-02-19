import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Union
from uuid import uuid4

from agno.models.metrics import Metrics
from agno.registry import Registry
from agno.run.agent import RunOutputEvent
from agno.run.base import RunContext
from agno.run.team import TeamRunOutputEvent
from agno.run.workflow import (
    ParallelExecutionCompletedEvent,
    ParallelExecutionStartedEvent,
    WorkflowRunOutput,
    WorkflowRunOutputEvent,
)
from agno.session.workflow import WorkflowSession
from agno.utils.log import log_debug, logger
from agno.utils.merge_dict import merge_parallel_session_states
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput, StepType

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
    """A list of steps that execute in parallel.

    Unlike sequential constructs (Steps, Loop), Parallel uses variadic arguments
    to emphasize that the steps are independent and unordered.

    Supports flexible calling conventions:
        Parallel(step1, step2, step3)                      # Steps only (name defaults to "Parallel")
        Parallel(step1, step2, name="my_parallel")         # Name as keyword (at end)
        Parallel("my_parallel", step1, step2)              # Name as first positional arg
    """

    name: Optional[str] = None
    description: Optional[str] = None
    steps: WorkflowSteps = field(default_factory=list)

    def __init__(
        self,
        *args: Union[str, WorkflowSteps],
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        resolved_name = name
        resolved_steps: List[Any] = []

        if args:
            first_arg = args[0]
            # Check if first argument is a plain string (likely a name, not a step)
            if isinstance(first_arg, str):
                # First arg is the name, rest are steps
                resolved_name = first_arg
                resolved_steps = list(args[1:])
            else:
                # All args are steps
                resolved_steps = list(args)

        # If name was provided as keyword, it takes precedence
        if name is not None:
            resolved_name = name

        self.steps = resolved_steps
        self.name = resolved_name
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "Parallel",
            "name": self.name,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps if hasattr(step, "to_dict")],
        }

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        registry: Optional["Registry"] = None,
        db: Optional[Any] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> "Parallel":
        from agno.workflow.condition import Condition
        from agno.workflow.loop import Loop
        from agno.workflow.router import Router
        from agno.workflow.steps import Steps

        def deserialize_step(step_data: Dict[str, Any]) -> Any:
            step_type = step_data.get("type", "Step")
            if step_type == "Loop":
                return Loop.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Parallel":
                return cls.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Steps":
                return Steps.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Condition":
                return Condition.from_dict(step_data, registry=registry, db=db, links=links)
            elif step_type == "Router":
                return Router.from_dict(step_data, registry=registry, db=db, links=links)
            else:
                return Step.from_dict(step_data, registry=registry, db=db, links=links)

        deserialized_steps = [deserialize_step(step) for step in data.get("steps", [])]
        return cls(
            *deserialized_steps,
            name=data.get("name"),
            description=data.get("description"),
        )

    def _prepare_steps(self):
        """Prepare the steps for execution - mirrors workflow logic"""
        from agno.agent.agent import Agent
        from agno.team.team import Team
        from agno.workflow.loop import Loop
        from agno.workflow.router import Router
        from agno.workflow.step import Step
        from agno.workflow.steps import Steps

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
            return StepOutput(
                step_name=self.name or "Parallel",
                step_id=str(uuid4()),
                step_type="Parallel",
                content="No parallel steps executed",
                steps=[],
            )

        if len(step_outputs) == 1:
            # Single result, but still create a Parallel container
            single_result = step_outputs[0]
            aggregated_metrics = self._extract_metrics_from_response(step_outputs)

            return StepOutput(
                step_name=self.name or "Parallel",
                step_id=str(uuid4()),
                step_type=StepType.PARALLEL,
                content=self._build_aggregated_content(step_outputs),
                executor_name=self.name or "Parallel",
                images=single_result.images,
                videos=single_result.videos,
                audio=single_result.audio,
                metrics=aggregated_metrics,
                success=single_result.success,
                error=single_result.error,
                stop=single_result.stop,
                steps=step_outputs,  # This is the key addition
            )

        early_termination_requested = any(output.stop for output in step_outputs if hasattr(output, "stop"))

        # Multiple results - aggregate them with actual content from all steps
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
            step_id=str(uuid4()),
            step_type=StepType.PARALLEL,
            executor_type="parallel",
            executor_name=self.name or "Parallel",
            content=aggregated_content,
            images=all_images if all_images else None,
            videos=all_videos if all_videos else None,
            audio=all_audio if all_audio else None,
            success=not has_any_failure,
            stop=early_termination_requested,
            metrics=aggregated_metrics,
            steps=step_outputs,
        )

    def _extract_metrics_from_response(self, step_outputs: List[StepOutput]) -> Optional[Metrics]:
        """Extract and aggregate metrics from parallel step outputs"""
        if not step_outputs:
            return None

        # Aggregate metrics from all parallel step outputs
        total_metrics = Metrics()

        for result in step_outputs:
            if result.metrics:
                total_metrics = total_metrics + result.metrics

        # If no metrics were found, return None
        if (
            total_metrics.input_tokens == 0
            and total_metrics.output_tokens == 0
            and total_metrics.total_tokens == 0
            and total_metrics.duration is None
        ):
            return None

        return total_metrics

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
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        store_executor_outputs: bool = True,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> StepOutput:
        """Execute all steps in parallel and return aggregated result"""
        # Use workflow logger for parallel orchestration
        log_debug(f"Parallel Start: {self.name} ({len(self.steps)} steps)", center=True, symbol="=")

        self._prepare_steps()

        # Create individual session_state copies for each step to prevent race conditions
        session_state_copies = []
        for _ in range(len(self.steps)):
            # If using run context, no need to deepcopy the state. We want the direct reference.
            if run_context is not None and run_context.session_state is not None:
                session_state_copies.append(run_context.session_state)
            else:
                if session_state is not None:
                    session_state_copies.append(deepcopy(session_state))
                else:
                    session_state_copies.append({})

        def execute_step_with_index(step_with_index):
            """Execute a single step and preserve its original index"""
            idx, step = step_with_index
            # Use the individual session_state copy for this step
            step_session_state = session_state_copies[idx]

            try:
                step_result = step.execute(
                    step_input,
                    session_id=session_id,
                    user_id=user_id,
                    workflow_run_response=workflow_run_response,
                    store_executor_outputs=store_executor_outputs,
                    workflow_session=workflow_session,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    run_context=run_context,
                    session_state=step_session_state,
                    background_tasks=background_tasks,
                )  # type: ignore[union-attr]
                return idx, step_result, step_session_state
            except Exception as exc:
                parallel_step_name = getattr(step, "name", f"step_{idx}")
                logger.error(f"Parallel step {parallel_step_name} failed: {exc}")
                return (
                    idx,
                    StepOutput(
                        step_name=parallel_step_name,
                        content=f"Step {parallel_step_name} failed: {str(exc)}",
                        success=False,
                        error=str(exc),
                    ),
                    step_session_state,
                )

        # Use index to preserve order
        indexed_steps = list(enumerate(self.steps))

        with ThreadPoolExecutor(max_workers=len(self.steps)) as executor:
            # Submit all tasks with their original indices
            # Use copy_context().run to propagate context variables to child threads
            future_to_index = {
                executor.submit(copy_context().run, execute_step_with_index, indexed_step): indexed_step[0]
                for indexed_step in indexed_steps
            }

            # Collect results and modified session_state copies
            results_with_indices = []
            modified_session_states = []
            for future in as_completed(future_to_index):
                try:
                    index, result, modified_session_state = future.result()
                    results_with_indices.append((index, result))
                    modified_session_states.append(modified_session_state)
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

        if run_context is None and session_state is not None:
            merge_parallel_session_states(session_state, modified_session_states)

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
        stream_events: bool = False,
        stream_executor_events: bool = True,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        step_index: Optional[Union[int, tuple]] = None,
        store_executor_outputs: bool = True,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        parent_step_id: Optional[str] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> Iterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Execute all steps in parallel with streaming support"""
        log_debug(f"Parallel Start: {self.name} ({len(self.steps)} steps)", center=True, symbol="=")

        parallel_step_id = str(uuid4())

        self._prepare_steps()

        # Create individual session_state copies for each step to prevent race conditions
        session_state_copies = []
        for _ in range(len(self.steps)):
            # If using run context, no need to deepcopy the state. We want the direct reference.
            if run_context is not None and run_context.session_state is not None:
                session_state_copies.append(run_context.session_state)
            else:
                if session_state is not None:
                    session_state_copies.append(deepcopy(session_state))
                else:
                    session_state_copies.append({})

        if stream_events and workflow_run_response:
            # Yield parallel step started event
            yield ParallelExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                parallel_step_count=len(self.steps),
                step_id=parallel_step_id,
                parent_step_id=parent_step_id,
            )

        import queue

        event_queue = queue.Queue()  # type: ignore
        step_results = []
        modified_session_states = []

        def execute_step_stream_with_index(step_with_index):
            """Execute a single step with streaming and put events in queue immediately"""
            idx, step = step_with_index
            # Use the individual session_state copy for this step
            step_session_state = session_state_copies[idx]

            try:
                step_outputs = []

                # If step_index is None or integer (main step): create (step_index, sub_index)
                # If step_index is tuple (child step): all parallel sub-steps get same index
                if step_index is None or isinstance(step_index, int):
                    # Parallel is a main step - sub-steps get sequential numbers: 1.1, 1.2, 1.3
                    sub_step_index = (step_index if step_index is not None else 0, idx)
                else:
                    # Parallel is a child step - all sub-steps get the same parent number: 1.1, 1.1, 1.1
                    sub_step_index = step_index

                # All workflow step types have execute_stream() method
                for event in step.execute_stream(  # type: ignore[union-attr]
                    step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_events=stream_events,
                    stream_executor_events=stream_executor_events,
                    workflow_run_response=workflow_run_response,
                    step_index=sub_step_index,
                    store_executor_outputs=store_executor_outputs,
                    session_state=step_session_state,
                    run_context=run_context,
                    parent_step_id=parallel_step_id,
                    workflow_session=workflow_session,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    background_tasks=background_tasks,
                ):
                    # Put event immediately in queue
                    event_queue.put(("event", idx, event))
                    if isinstance(event, StepOutput):
                        step_outputs.append(event)

                # Signal completion for this step
                event_queue.put(("complete", idx, step_outputs, step_session_state))
                return idx, step_outputs, step_session_state
            except Exception as exc:
                parallel_step_name = getattr(step, "name", f"step_{idx}")
                logger.error(f"Parallel step {parallel_step_name} streaming failed: {exc}")
                error_event = StepOutput(
                    step_name=parallel_step_name,
                    content=f"Step {parallel_step_name} failed: {str(exc)}",
                    success=False,
                    error=str(exc),
                )
                event_queue.put(("event", idx, error_event))
                event_queue.put(("complete", idx, [error_event], step_session_state))
                return idx, [error_event], step_session_state

        # Submit all parallel tasks
        indexed_steps = list(enumerate(self.steps))

        with ThreadPoolExecutor(max_workers=len(self.steps)) as executor:
            # Submit all tasks
            # Use copy_context().run to propagate context variables to child threads
            futures = [
                executor.submit(copy_context().run, execute_step_stream_with_index, indexed_step)
                for indexed_step in indexed_steps
            ]

            # Process events from queue as they arrive
            completed_steps = 0
            total_steps = len(self.steps)

            while completed_steps < total_steps:
                try:
                    message_type, step_idx, *data = event_queue.get(timeout=1.0)

                    if message_type == "event":
                        event = data[0]
                        # Yield events immediately as they arrive (except StepOutputs)
                        if not isinstance(event, StepOutput):
                            yield event

                    elif message_type == "complete":
                        step_outputs, step_session_state = data
                        step_results.extend(step_outputs)
                        modified_session_states.append(step_session_state)
                        completed_steps += 1

                        step_name = getattr(self.steps[step_idx], "name", f"step_{step_idx}")
                        log_debug(f"Parallel step {step_name} streaming completed")

                except queue.Empty:
                    for i, future in enumerate(futures):
                        if future.done() and future.exception():
                            logger.error(f"Parallel step {i} failed: {future.exception()}")
                            if completed_steps < total_steps:
                                completed_steps += 1
                except Exception as e:
                    logger.error(f"Error processing parallel step events: {e}")
                    completed_steps += 1

            for future in futures:
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Future completion error: {e}")

        # Merge all session_state changes back into the original session_state
        if run_context is None and session_state is not None:
            merge_parallel_session_states(session_state, modified_session_states)

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

        if stream_events and workflow_run_response:
            # Yield parallel step completed event
            yield ParallelExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                parallel_step_count=len(self.steps),
                step_results=flattened_step_results,
                step_id=parallel_step_id,
                parent_step_id=parent_step_id,
            )

    async def aexecute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        store_executor_outputs: bool = True,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> StepOutput:
        """Execute all steps in parallel using asyncio and return aggregated result"""
        # Use workflow logger for async parallel orchestration
        log_debug(f"Parallel Start: {self.name} ({len(self.steps)} steps)", center=True, symbol="=")

        self._prepare_steps()

        # Create individual session_state copies for each step to prevent race conditions
        session_state_copies = []
        for _ in range(len(self.steps)):
            # If using run context, no need to deepcopy the state. We want the direct reference.
            if run_context is not None and run_context.session_state is not None:
                session_state_copies.append(run_context.session_state)
            else:
                if session_state is not None:
                    session_state_copies.append(deepcopy(session_state))
                else:
                    session_state_copies.append({})

        async def execute_step_async_with_index(step_with_index):
            """Execute a single step asynchronously and preserve its original index"""
            idx, step = step_with_index
            # Use the individual session_state copy for this step
            step_session_state = session_state_copies[idx]

            try:
                inner_step_result = await step.aexecute(
                    step_input,
                    session_id=session_id,
                    user_id=user_id,
                    workflow_run_response=workflow_run_response,
                    store_executor_outputs=store_executor_outputs,
                    workflow_session=workflow_session,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    session_state=step_session_state,
                    run_context=run_context,
                    background_tasks=background_tasks,
                )  # type: ignore[union-attr]
                return idx, inner_step_result, step_session_state
            except Exception as exc:
                parallel_step_name = getattr(step, "name", f"step_{idx}")
                logger.error(f"Parallel step {parallel_step_name} failed: {exc}")
                return (
                    idx,
                    StepOutput(
                        step_name=parallel_step_name,
                        content=f"Step {parallel_step_name} failed: {str(exc)}",
                        success=False,
                        error=str(exc),
                    ),
                    step_session_state,
                )

        # Use index to preserve order
        indexed_steps = list(enumerate(self.steps))

        # Create tasks for all steps with their indices
        tasks = [execute_step_async_with_index(indexed_step) for indexed_step in indexed_steps]

        # Execute all tasks concurrently
        results_with_indices = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results and handle exceptions, preserving order
        processed_results_with_indices = []
        modified_session_states = []
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
                # Still collect the session state copy for failed steps
                modified_session_states.append(session_state_copies[i])
            else:
                index, step_result, modified_session_state = result  # type: ignore[misc]
                processed_results_with_indices.append((index, step_result))
                modified_session_states.append(modified_session_state)
                step_name = getattr(self.steps[index], "name", f"step_{index}")
                log_debug(f"Parallel step {step_name} completed")

        # Smart merge all session_state changes back into the original session_state
        if run_context is None and session_state is not None:
            merge_parallel_session_states(session_state, modified_session_states)

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
        stream_events: bool = False,
        stream_executor_events: bool = True,
        workflow_run_response: Optional[WorkflowRunOutput] = None,
        step_index: Optional[Union[int, tuple]] = None,
        store_executor_outputs: bool = True,
        run_context: Optional[RunContext] = None,
        session_state: Optional[Dict[str, Any]] = None,
        parent_step_id: Optional[str] = None,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
        background_tasks: Optional[Any] = None,
    ) -> AsyncIterator[Union[WorkflowRunOutputEvent, TeamRunOutputEvent, RunOutputEvent, StepOutput]]:
        """Execute all steps in parallel with async streaming support"""
        log_debug(f"Parallel Start: {self.name} ({len(self.steps)} steps)", center=True, symbol="=")

        parallel_step_id = str(uuid4())

        self._prepare_steps()

        # Create individual session_state copies for each step to prevent race conditions
        session_state_copies = []
        for _ in range(len(self.steps)):
            # If using run context, no need to deepcopy the state. We want the direct reference.
            if run_context is not None and run_context.session_state is not None:
                session_state_copies.append(run_context.session_state)
            else:
                if session_state is not None:
                    session_state_copies.append(deepcopy(session_state))
                else:
                    session_state_copies.append({})

        if stream_events and workflow_run_response:
            # Yield parallel step started event
            yield ParallelExecutionStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                parallel_step_count=len(self.steps),
                step_id=parallel_step_id,
                parent_step_id=parent_step_id,
            )

        import asyncio

        event_queue = asyncio.Queue()  # type: ignore
        step_results = []
        modified_session_states = []

        async def execute_step_stream_async_with_index(step_with_index):
            """Execute a single step with async streaming and yield events immediately"""
            idx, step = step_with_index
            # Use the individual session_state copy for this step
            step_session_state = session_state_copies[idx]

            try:
                step_outputs = []

                # If step_index is None or integer (main step): create (step_index, sub_index)
                # If step_index is tuple (child step): all parallel sub-steps get same index
                if step_index is None or isinstance(step_index, int):
                    # Parallel is a main step - sub-steps get sequential numbers: 1.1, 1.2, 1.3
                    sub_step_index = (step_index if step_index is not None else 0, idx)
                else:
                    # Parallel is a child step - all sub-steps get the same parent number: 1.1, 1.1, 1.1
                    sub_step_index = step_index

                # All workflow step types have aexecute_stream() method
                async for event in step.aexecute_stream(
                    step_input,
                    session_id=session_id,
                    user_id=user_id,
                    stream_events=stream_events,
                    stream_executor_events=stream_executor_events,
                    workflow_run_response=workflow_run_response,
                    step_index=sub_step_index,
                    store_executor_outputs=store_executor_outputs,
                    session_state=step_session_state,
                    run_context=run_context,
                    parent_step_id=parallel_step_id,
                    workflow_session=workflow_session,
                    add_workflow_history_to_steps=add_workflow_history_to_steps,
                    num_history_runs=num_history_runs,
                    background_tasks=background_tasks,
                ):  # type: ignore[union-attr]
                    # Yield events immediately to the queue
                    await event_queue.put(("event", idx, event))
                    if isinstance(event, StepOutput):
                        step_outputs.append(event)

                # Signal completion for this step
                await event_queue.put(("complete", idx, step_outputs, step_session_state))
                return idx, step_outputs, step_session_state
            except Exception as e:
                parallel_step_name = getattr(step, "name", f"step_{idx}")
                logger.error(f"Parallel step {parallel_step_name} async streaming failed: {e}")
                error_event = StepOutput(
                    step_name=parallel_step_name,
                    content=f"Step {parallel_step_name} failed: {str(e)}",
                    success=False,
                    error=str(e),
                )
                await event_queue.put(("event", idx, error_event))
                await event_queue.put(("complete", idx, [error_event], step_session_state))
                return idx, [error_event], step_session_state

        # Start all parallel tasks
        indexed_steps = list(enumerate(self.steps))
        tasks = [
            asyncio.create_task(execute_step_stream_async_with_index(indexed_step)) for indexed_step in indexed_steps
        ]

        # Process events as they arrive and track completion
        completed_steps = 0
        total_steps = len(self.steps)

        while completed_steps < total_steps:
            try:
                message_type, step_idx, *data = await event_queue.get()

                if message_type == "event":
                    event = data[0]
                    if not isinstance(event, StepOutput):
                        yield event

                elif message_type == "complete":
                    step_outputs, step_session_state = data
                    step_results.extend(step_outputs)
                    modified_session_states.append(step_session_state)
                    completed_steps += 1

                    step_name = getattr(self.steps[step_idx], "name", f"step_{step_idx}")
                    log_debug(f"Parallel step {step_name} async streaming completed")

            except Exception as e:
                logger.error(f"Error processing parallel step events: {e}")
                completed_steps += 1

        await asyncio.gather(*tasks, return_exceptions=True)

        # Merge all session_state changes back into the original session_state
        if run_context is None and session_state is not None:
            merge_parallel_session_states(session_state, modified_session_states)

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

        if stream_events and workflow_run_response:
            # Yield parallel step completed event
            yield ParallelExecutionCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                parallel_step_count=len(self.steps),
                step_results=flattened_step_results,
                step_id=parallel_step_id,
                parent_step_id=parent_step_id,
            )
