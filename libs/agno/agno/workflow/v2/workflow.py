import inspect
from dataclasses import dataclass
from datetime import datetime
from os import getenv
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Literal, Optional, Union, overload
from uuid import uuid4

from pydantic import BaseModel

from agno.agent.agent import Agent
from agno.media import Audio, Image, Video
from agno.run.base import RunStatus
from agno.run.v2.workflow import (
    ConditionExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    LoopExecutionCompletedEvent,
    LoopExecutionStartedEvent,
    LoopIterationCompletedEvent,
    LoopIterationStartedEvent,
    ParallelExecutionCompletedEvent,
    ParallelExecutionStartedEvent,
    RouterExecutionCompletedEvent,
    RouterExecutionStartedEvent,
    StepCompletedEvent,
    StepOutputEvent,
    StepStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunEvent,
    WorkflowRunResponse,
    WorkflowRunResponseEvent,
    WorkflowStartedEvent,
)
from agno.storage.base import Storage
from agno.storage.session.v2.workflow import WorkflowSession as WorkflowSessionV2
from agno.team.team import Team
from agno.utils.log import log_debug, logger, set_log_level_to_debug, set_log_level_to_info
from agno.workflow.v2.condition import Condition
from agno.workflow.v2.loop import Loop
from agno.workflow.v2.parallel import Parallel
from agno.workflow.v2.router import Router
from agno.workflow.v2.step import Step
from agno.workflow.v2.steps import Steps
from agno.workflow.v2.types import StepInput, StepMetrics, StepOutput, WorkflowExecutionInput, WorkflowMetrics

WorkflowSteps = Union[
    Callable[
        ["Workflow", WorkflowExecutionInput],
        Union[StepOutput, Awaitable[StepOutput], Iterator[StepOutput], AsyncIterator[StepOutput], Any],
    ],
    Steps,
    List[
        Union[
            Callable[
                [StepInput], Union[StepOutput, Awaitable[StepOutput], Iterator[StepOutput], AsyncIterator[StepOutput]]
            ],
            Step,
            Steps,
            Loop,
            Parallel,
            Condition,
            Router,
        ]
    ],
]


@dataclass
class Workflow:
    """Pipeline-based workflow execution"""

    # Workflow identification - make name optional with default
    name: Optional[str] = None
    workflow_id: Optional[str] = None
    description: Optional[str] = None

    # Workflow configuration
    steps: Optional[WorkflowSteps] = None

    storage: Optional[Storage] = None

    # Session management
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    user_id: Optional[str] = None
    workflow_session_id: Optional[str] = None
    workflow_session_state: Optional[Dict[str, Any]] = None

    # Runtime state
    run_id: Optional[str] = None
    run_response: Optional[WorkflowRunResponse] = None

    # Workflow session for storage
    workflow_session: Optional[WorkflowSessionV2] = None
    debug_mode: Optional[bool] = False

    # --- Workflow Streaming ---
    # Stream the response from the Workflow
    stream: Optional[bool] = None
    # Stream the intermediate steps from the Workflow
    stream_intermediate_steps: bool = False

    store_events: bool = False
    events_to_skip: Optional[List[WorkflowRunEvent]] = None

    def __init__(
        self,
        workflow_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        storage: Optional[Storage] = None,
        steps: Optional[WorkflowSteps] = None,
        session_id: Optional[str] = None,
        session_name: Optional[str] = None,
        workflow_session_state: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        debug_mode: Optional[bool] = False,
        stream: Optional[bool] = None,
        stream_intermediate_steps: bool = False,
        store_events: bool = False,
        events_to_skip: Optional[List[WorkflowRunEvent]] = None,
    ):
        self.workflow_id = workflow_id
        self.name = name
        self.description = description
        self.storage = storage
        self.steps = steps
        self.session_id = session_id
        self.session_name = session_name
        self.workflow_session_state = workflow_session_state
        self.user_id = user_id
        self.debug_mode = debug_mode
        self.store_events = store_events
        self.events_to_skip = events_to_skip or []
        self.stream = stream
        self.stream_intermediate_steps = stream_intermediate_steps

    def initialize_workflow(self):
        if self.workflow_id is None:
            self.workflow_id = str(uuid4())
            log_debug(f"Generated new workflow_id: {self.workflow_id}")

        if self.session_id is None:
            self.session_id = str(uuid4())
            log_debug(f"Generated new session_id: {self.session_id}")

        # Set storage mode to workflow_v2
        if self.storage is not None:
            self.storage.mode = "workflow_v2"

        self._update_workflow_session_state()

    def _handle_event(
        self, event: "WorkflowRunResponseEvent", workflow_run_response: WorkflowRunResponse
    ) -> "WorkflowRunResponseEvent":
        """Handle workflow events for storage - similar to Team._handle_event"""
        if self.store_events:
            # Check if this event type should be skipped
            if self.events_to_skip:
                event_type = event.event
                for skip_event in self.events_to_skip:
                    if isinstance(skip_event, str):
                        if event_type == skip_event:
                            return event
                    else:
                        # It's a WorkflowRunEvent enum
                        if event_type == skip_event.value:
                            return event

            # Store the event
            if workflow_run_response.events is None:
                workflow_run_response.events = []

            workflow_run_response.events.append(event)

        return event

    def _transform_step_output_to_event(
        self, step_output: StepOutput, workflow_run_response: WorkflowRunResponse, step_index: Optional[int] = None
    ) -> StepOutputEvent:
        """Transform a StepOutput object into a StepOutputEvent for consistent streaming interface"""
        return StepOutputEvent(
            step_output=step_output,
            run_id=workflow_run_response.run_id or "",
            workflow_name=workflow_run_response.workflow_name,
            workflow_id=workflow_run_response.workflow_id,
            session_id=workflow_run_response.session_id,
            step_name=step_output.step_name,
            step_index=step_index,
        )

    def _set_debug(self) -> None:
        """Set debug mode and configure logging"""
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()

            # Propagate to steps - only if steps is iterable (not callable)
            if self.steps and not isinstance(self.steps, Callable):
                for step in self.steps:
                    # TODO: Handle properly steps inside other primitives

                    # Propagate to step executors (agents/teams)
                    if hasattr(step, "active_executor") and step.active_executor:
                        executor = step.active_executor
                        if hasattr(executor, "debug_mode"):
                            executor.debug_mode = True

                        # If it's a team, propagate to all members
                        if hasattr(executor, "members"):
                            for member in executor.members:
                                if hasattr(member, "debug_mode"):
                                    member.debug_mode = True
        else:
            set_log_level_to_info()

    def _create_step_input(
        self,
        execution_input: WorkflowExecutionInput,
        previous_step_outputs: Optional[Dict[str, StepOutput]] = None,
        shared_images: Optional[List[Image]] = None,
        shared_videos: Optional[List[Video]] = None,
        shared_audio: Optional[List[Audio]] = None,
    ) -> StepInput:
        """Helper method to create StepInput with enhanced data flow support"""

        previous_step_content = None
        if previous_step_outputs:
            last_output = list(previous_step_outputs.values())[-1]
            previous_step_content = last_output.content if last_output else None

        return StepInput(
            message=execution_input.message,
            previous_step_content=previous_step_content,
            previous_step_outputs=previous_step_outputs,
            workflow_message=execution_input.message,
            images=shared_images or [],
            videos=shared_videos or [],
            audio=shared_audio or [],
        )

    def _get_step_count(self) -> int:
        """Get the number of steps in the workflow"""
        if self.steps is None:
            return 0
        elif isinstance(self.steps, Callable):
            return 1  # Callable function counts as 1 step
        else:
            return len(self.steps)

    def _convert_dict_to_step_metrics(self, step_name: str, metrics_dict: Dict[str, Any]) -> StepMetrics:
        """Convert dictionary metrics to StepMetrics object"""
        return StepMetrics.from_dict(
            {
                "step_name": step_name,
                "executor_type": metrics_dict.get("executor_type", "unknown"),
                "executor_name": metrics_dict.get("executor_name", "unknown"),
                "metrics": metrics_dict.get("metrics"),
                "parallel_steps": metrics_dict.get("parallel_steps"),
            }
        )

    def _aggregate_workflow_metrics(self, step_responses: List[Union[StepOutput, List[StepOutput]]]) -> WorkflowMetrics:
        """Aggregate metrics from all step responses into structured workflow metrics"""
        steps_dict = {}
        total_steps = 0

        def process_step_output(step_output: StepOutput):
            """Process a single step output for metrics"""
            nonlocal total_steps
            total_steps += 1

            # Add step-specific metrics
            if step_output.step_name and step_output.metrics:
                step_metrics = self._convert_dict_to_step_metrics(step_output.step_name, step_output.metrics)
                steps_dict[step_output.step_name] = step_metrics

        # Process all step responses
        for step_response in step_responses:
            if isinstance(step_response, list):
                # Handle List[StepOutput] from workflow components
                for sub_step_output in step_response:
                    process_step_output(sub_step_output)
            else:
                # Handle single StepOutput
                process_step_output(step_response)

        return WorkflowMetrics(
            total_steps=total_steps,
            steps=steps_dict,
        )

    def _call_custom_function(
        self, func: Callable, workflow: "Workflow", execution_input: WorkflowExecutionInput, **kwargs: Any
    ) -> Any:
        """Call custom function with only the parameters it expects"""
        sig = inspect.signature(func)

        # Build arguments based on what the function actually accepts
        call_kwargs = {}

        # Only add workflow and execution_input if the function expects them
        if "workflow" in sig.parameters:
            call_kwargs["workflow"] = self
        if "execution_input" in sig.parameters:
            call_kwargs["execution_input"] = execution_input

        # Add any other kwargs that the function expects
        for param_name in kwargs:
            if param_name in sig.parameters:
                call_kwargs[param_name] = kwargs[param_name]

        # If function has **kwargs parameter, pass all remaining kwargs
        for param in sig.parameters.values():
            if param.kind == param.VAR_KEYWORD:
                call_kwargs.update(kwargs)
                break

        try:
            return func(**call_kwargs)
        except TypeError as e:
            # If signature inspection fails, fall back to original method
            logger.warning(
                f"Async function signature inspection failed: {e}. Falling back to original calling convention."
            )
            return func(workflow, execution_input, **kwargs)

    def _execute(
        self, execution_input: WorkflowExecutionInput, workflow_run_response: WorkflowRunResponse, **kwargs: Any
    ) -> WorkflowRunResponse:
        """Execute a specific pipeline by name synchronously"""

        workflow_run_response.status = RunStatus.running

        if isinstance(self.steps, Callable):
            if inspect.iscoroutinefunction(self.steps) or inspect.isasyncgenfunction(self.steps):
                raise ValueError("Cannot use async function with synchronous execution")
            elif inspect.isgeneratorfunction(self.steps):
                content = ""
                for chunk in self.steps(self, execution_input, **kwargs):
                    if hasattr(chunk, "content") and chunk.content is not None and isinstance(chunk.content, str):
                        content += chunk.content
                    else:
                        content += str(chunk)
                workflow_run_response.content = content
            else:
                # Execute the workflow with the custom executor
                workflow_run_response.content = self._call_custom_function(self.steps, self, execution_input, **kwargs)

            workflow_run_response.status = RunStatus.completed
        else:
            try:
                # Track outputs from each step for enhanced data flow
                collected_step_outputs: List[Union[StepOutput, List[StepOutput]]] = []
                previous_step_outputs: Dict[str, StepOutput] = {}

                shared_images = execution_input.images or []
                output_images = []
                shared_videos = execution_input.videos or []
                output_videos = []
                shared_audio = execution_input.audio or []
                output_audio = []

                for i, step in enumerate(self.steps):
                    step_name = getattr(step, "name", f"step_{i + 1}")
                    log_debug(f"Executing step {i + 1}/{self._get_step_count()}: {step_name}")

                    # Create enhanced StepInput
                    step_input = self._create_step_input(
                        execution_input=execution_input,
                        previous_step_outputs=previous_step_outputs,
                        shared_images=shared_images,
                        shared_videos=shared_videos,
                        shared_audio=shared_audio,
                    )

                    step_output = step.execute(step_input, session_id=self.session_id, user_id=self.user_id)

                    # Update the workflow-level previous_step_outputs dictionary
                    if isinstance(step_output, list):
                        # For multiple outputs (from Loop, Condition, etc.), store the last one
                        if step_output:
                            previous_step_outputs[step_name] = step_output[-1]
                            if any(output.stop for output in step_output):
                                logger.info(f"Early termination requested by step {step_name}")
                                break
                    else:
                        # Single output
                        previous_step_outputs[step_name] = step_output
                        if step_output.stop:
                            logger.info(f"Early termination requested by step {step_name}")
                            break

                    # Update shared media for next step
                    if isinstance(step_output, list):
                        for output in step_output:
                            shared_images.extend(output.images or [])
                            shared_videos.extend(output.videos or [])
                            shared_audio.extend(output.audio or [])
                            output_images.extend(output.images or [])
                            output_videos.extend(output.videos or [])
                            output_audio.extend(output.audio or [])
                    else:
                        shared_images.extend(step_output.images or [])
                        shared_videos.extend(step_output.videos or [])
                        shared_audio.extend(step_output.audio or [])
                        output_images.extend(step_output.images or [])
                        output_videos.extend(step_output.videos or [])
                        output_audio.extend(step_output.audio or [])

                    collected_step_outputs.append(step_output)

                    self._collect_workflow_session_state_from_agents_and_teams()

                # Update the workflow_run_response with completion data
                if collected_step_outputs:
                    workflow_run_response.workflow_metrics = self._aggregate_workflow_metrics(collected_step_outputs)
                    last_output = collected_step_outputs[-1]
                    if isinstance(last_output, list) and last_output:
                        # If it's a list (from Condition/Loop/etc.), use the last one
                        workflow_run_response.content = last_output[-1].content
                    else:
                        # Single StepOutput
                        workflow_run_response.content = last_output.content
                else:
                    workflow_run_response.content = "No steps executed"

                workflow_run_response.step_responses = collected_step_outputs
                workflow_run_response.images = output_images
                workflow_run_response.videos = output_videos
                workflow_run_response.audio = output_audio
                workflow_run_response.status = RunStatus.completed

            except Exception as e:
                import traceback

                traceback.print_exc()
                logger.error(f"Workflow execution failed: {e}")
                # Store error response
                workflow_run_response.status = RunStatus.error
                workflow_run_response.content = f"Workflow execution failed: {e}"

            finally:
                if self.workflow_session:
                    self.workflow_session.add_run(workflow_run_response)
                self.write_to_storage()

        return workflow_run_response

    def _execute_stream(
        self,
        execution_input: WorkflowExecutionInput,
        workflow_run_response: WorkflowRunResponse,
        stream_intermediate_steps: bool = False,
        **kwargs: Any,
    ) -> Iterator[WorkflowRunResponseEvent]:
        """Execute a specific pipeline by name with event streaming"""

        workflow_run_response.status = RunStatus.running

        workflow_started_event = WorkflowStartedEvent(
            run_id=workflow_run_response.run_id or "",
            workflow_name=workflow_run_response.workflow_name,
            workflow_id=workflow_run_response.workflow_id,
            session_id=workflow_run_response.session_id,
        )
        yield self._handle_event(workflow_started_event, workflow_run_response)

        if isinstance(self.steps, Callable):
            if inspect.iscoroutinefunction(self.steps) or inspect.isasyncgenfunction(self.steps):
                raise ValueError("Cannot use async function with synchronous execution")
            elif inspect.isgeneratorfunction(self.steps):
                content = ""
                for chunk in self._call_custom_function(self.steps, self, execution_input, **kwargs):
                    # Update the run_response with the content from the result
                    if hasattr(chunk, "content") and chunk.content is not None and isinstance(chunk.content, str):
                        content += chunk.content
                        yield chunk
                    else:
                        content += str(chunk)
                workflow_run_response.content = content
            else:
                workflow_run_response.content = self._call_custom_function(self.steps, self, execution_input, **kwargs)
            workflow_run_response.status = RunStatus.completed

        else:
            try:
                # Track outputs from each step for enhanced data flow
                collected_step_outputs: List[Union[StepOutput, List[StepOutput]]] = []
                previous_step_outputs: Dict[str, StepOutput] = {}

                shared_images = execution_input.images or []
                output_images = []
                shared_videos = execution_input.videos or []
                output_videos = []
                shared_audio = execution_input.audio or []
                output_audio = []

                early_termination = False

                for i, step in enumerate(self.steps):
                    step_name = getattr(step, "name", f"step_{i + 1}")
                    log_debug(f"Streaming step {i + 1}/{self._get_step_count()}: {step_name}")

                    # Create enhanced StepInput
                    step_input = self._create_step_input(
                        execution_input=execution_input,
                        previous_step_outputs=previous_step_outputs,
                        shared_images=shared_images,
                        shared_videos=shared_videos,
                        shared_audio=shared_audio,
                    )

                    # Execute step with streaming and yield all events
                    for event in step.execute_stream(
                        step_input,
                        session_id=self.session_id,
                        user_id=self.user_id,
                        stream_intermediate_steps=stream_intermediate_steps,
                        workflow_run_response=workflow_run_response,
                        step_index=i,
                    ):
                        # Handle events
                        if isinstance(event, StepOutput):
                            step_output = event
                            collected_step_outputs.append(step_output)

                            # Update the workflow-level previous_step_outputs dictionary
                            previous_step_outputs[step_name] = step_output

                            # Transform StepOutput to StepOutputEvent for consistent streaming interface
                            step_output_event = self._transform_step_output_to_event(
                                step_output, workflow_run_response, step_index=i
                            )

                            if step_output.stop:
                                logger.info(f"Early termination requested by step {step_name}")
                                # Update shared media for next step
                                shared_images.extend(step_output.images or [])
                                shared_videos.extend(step_output.videos or [])
                                shared_audio.extend(step_output.audio or [])
                                output_images.extend(step_output.images or [])
                                output_videos.extend(step_output.videos or [])
                                output_audio.extend(step_output.audio or [])

                                # Only yield StepOutputEvent for function executors, not for agents/teams
                                if getattr(step, "executor_type", None) == "function":
                                    yield step_output_event

                                # Break out of the step loop
                                early_termination = True
                                break

                            # Update shared media for next step
                            shared_images.extend(step_output.images or [])
                            shared_videos.extend(step_output.videos or [])
                            shared_audio.extend(step_output.audio or [])
                            output_images.extend(step_output.images or [])
                            output_videos.extend(step_output.videos or [])
                            output_audio.extend(step_output.audio or [])

                            # Only yield StepOutputEvent for generator functions, not for agents/teams
                            if getattr(step, "executor_type", None) == "function":
                                yield step_output_event
                        
                        elif isinstance(event, WorkflowRunResponseEvent):
                            yield self._handle_event(event, workflow_run_response)

                        else:
                            # Yield other internal events
                            yield event
                    # Break out of main step loop if early termination was requested
                    if "early_termination" in locals() and early_termination:
                        break

                    self._collect_workflow_session_state_from_agents_and_teams()

                # Update the workflow_run_response with completion data
                if collected_step_outputs:
                    workflow_run_response.workflow_metrics = self._aggregate_workflow_metrics(collected_step_outputs)
                    last_output = collected_step_outputs[-1]
                    if isinstance(last_output, list) and last_output:
                        # If it's a list (from Condition/Loop/etc.), use the last one
                        workflow_run_response.content = last_output[-1].content
                    else:
                        # Single StepOutput
                        workflow_run_response.content = last_output.content
                else:
                    workflow_run_response.content = "No steps executed"

                workflow_run_response.step_responses = collected_step_outputs
                workflow_run_response.images = output_images
                workflow_run_response.videos = output_videos
                workflow_run_response.audio = output_audio
                workflow_run_response.status = RunStatus.completed

            except Exception as e:
                logger.error(f"Workflow execution failed: {e}")

                from agno.run.v2.workflow import WorkflowErrorEvent

                error_event = WorkflowErrorEvent(
                    run_id=self.run_id or "",
                    workflow_id=self.workflow_id,
                    workflow_name=self.name,
                    session_id=self.session_id,
                    error=str(e),
                )

                yield error_event

                # Update workflow_run_response with error
                workflow_run_response.content = error_event.error
                workflow_run_response.status = RunStatus.error

        # Yield workflow completed event
        workflow_completed_event = WorkflowCompletedEvent(
            run_id=workflow_run_response.run_id or "",
            content=workflow_run_response.content,
            workflow_name=workflow_run_response.workflow_name,
            workflow_id=workflow_run_response.workflow_id,
            session_id=workflow_run_response.session_id,
            step_responses=workflow_run_response.step_responses,
            extra_data=workflow_run_response.extra_data,
        )
        yield self._handle_event(workflow_completed_event, workflow_run_response)

        # Store the completed workflow response
        if self.workflow_session:
            self.workflow_session.add_run(workflow_run_response)

        # Save to storage after complete execution
        self.write_to_storage()

    async def _acall_custom_function(
        self, func: Callable, workflow: "Workflow", execution_input: WorkflowExecutionInput, **kwargs: Any
    ) -> Any:
        """Call custom function with only the parameters it expects - handles both async functions and async generators"""
        sig = inspect.signature(func)

        # Build arguments based on what the function actually accepts
        call_kwargs = {}

        # Only add workflow and execution_input if the function expects them
        if "workflow" in sig.parameters:
            call_kwargs["workflow"] = self
        if "execution_input" in sig.parameters:
            call_kwargs["execution_input"] = execution_input

        # Add any other kwargs that the function expects
        for param_name in kwargs:
            if param_name in sig.parameters:
                call_kwargs[param_name] = kwargs[param_name]

        # If function has **kwargs parameter, pass all remaining kwargs
        for param in sig.parameters.values():
            if param.kind == param.VAR_KEYWORD:
                call_kwargs.update(kwargs)
                break

        try:
            # Check if it's an async generator function
            if inspect.isasyncgenfunction(func):
                # For async generators, call the function and return the async generator directly
                return func(**call_kwargs)
            else:
                # For regular async functions, await the result
                return await func(**call_kwargs)
        except TypeError as e:
            # If signature inspection fails, fall back to original method
            logger.warning(
                f"Async function signature inspection failed: {e}. Falling back to original calling convention."
            )
            if inspect.isasyncgenfunction(func):
                # For async generators, use the same signature inspection logic in fallback
                return func(**call_kwargs)
            else:
                # For regular async functions, use the same signature inspection logic in fallback
                return await func(**call_kwargs)

    async def _aexecute(
        self, execution_input: WorkflowExecutionInput, workflow_run_response: WorkflowRunResponse, **kwargs: Any
    ) -> WorkflowRunResponse:
        """Execute a specific pipeline by name asynchronously"""

        workflow_run_response.status = RunStatus.running

        if isinstance(self.steps, Callable):
            # Execute the workflow with the custom executor
            content = ""

            if inspect.iscoroutinefunction(self.steps):
                workflow_run_response.content = await self._acall_custom_function(
                    self.steps, self, execution_input, **kwargs
                )
            elif inspect.isgeneratorfunction(self.steps):
                for chunk in self.steps(self, execution_input, **kwargs):
                    if hasattr(chunk, "content") and chunk.content is not None and isinstance(chunk.content, str):
                        content += chunk.content
                    else:
                        content += str(chunk)
                workflow_run_response.content = content
            elif inspect.isasyncgenfunction(self.steps):
                async for chunk in self.steps(self, execution_input):
                    if hasattr(chunk, "content") and chunk.content is not None and isinstance(chunk.content, str):
                        content += chunk.content
                    else:
                        content += str(chunk)
                workflow_run_response.content = content
            else:
                workflow_run_response.content = self.steps(self, execution_input, **kwargs)
            workflow_run_response.status = RunStatus.completed

        else:
            try:
                # Track outputs from each step for enhanced data flow
                collected_step_outputs: List[Union[StepOutput, List[StepOutput]]] = []
                previous_step_outputs: Dict[str, StepOutput] = {}

                shared_images = execution_input.images or []
                output_images = []
                shared_videos = execution_input.videos or []
                output_videos = []
                shared_audio = execution_input.audio or []
                output_audio = []

                for i, step in enumerate(self.steps):
                    step_name = getattr(step, "name", f"step_{i + 1}")
                    log_debug(f"Async Executing step {i + 1}/{self._get_step_count()}: {step_name}")

                    # Create enhanced StepInput
                    step_input = self._create_step_input(
                        execution_input=execution_input,
                        previous_step_outputs=previous_step_outputs,
                        shared_images=shared_images,
                        shared_videos=shared_videos,
                        shared_audio=shared_audio,
                    )

                    step_output = await step.aexecute(step_input, session_id=self.session_id, user_id=self.user_id)

                    # Update the workflow-level previous_step_outputs dictionary
                    if isinstance(step_output, list):
                        # For multiple outputs (from Loop, Condition, etc.), store the last one
                        if step_output:
                            previous_step_outputs[step_name] = step_output[-1]
                            if any(output.stop for output in step_output):
                                logger.info(f"Early termination requested by step {step_name}")
                                break
                    else:
                        # Single output
                        previous_step_outputs[step_name] = step_output
                        if step_output.stop:
                            logger.info(f"Early termination requested by step {step_name}")
                            break

                    # Update shared media for next step
                    if isinstance(step_output, list):
                        for output in step_output:
                            shared_images.extend(output.images or [])
                            shared_videos.extend(output.videos or [])
                            shared_audio.extend(output.audio or [])
                            output_images.extend(output.images or [])
                            output_videos.extend(output.videos or [])
                            output_audio.extend(output.audio or [])
                    else:
                        shared_images.extend(step_output.images or [])
                        shared_videos.extend(step_output.videos or [])
                        shared_audio.extend(step_output.audio or [])
                        output_images.extend(step_output.images or [])
                        output_videos.extend(step_output.videos or [])
                        output_audio.extend(step_output.audio or [])

                    collected_step_outputs.append(step_output)

                    self._collect_workflow_session_state_from_agents_and_teams()

                # Update the workflow_run_response with completion data
                if collected_step_outputs:
                    workflow_run_response.workflow_metrics = self._aggregate_workflow_metrics(collected_step_outputs)
                    last_output = collected_step_outputs[-1]
                    if isinstance(last_output, list) and last_output:
                        # If it's a list (from Condition/Loop/etc.), use the last one
                        workflow_run_response.content = last_output[-1].content
                    else:
                        # Single StepOutput
                        workflow_run_response.content = last_output.content
                else:
                    workflow_run_response.content = "No steps executed"

                workflow_run_response.step_responses = collected_step_outputs
                workflow_run_response.images = output_images
                workflow_run_response.videos = output_videos
                workflow_run_response.audio = output_audio
                workflow_run_response.status = RunStatus.completed

            except Exception as e:
                logger.error(f"Workflow execution failed: {e}")
                workflow_run_response.status = RunStatus.error
                workflow_run_response.content = f"Workflow execution failed: {e}"

        # Store error response
        if self.workflow_session:
            self.workflow_session.add_run(workflow_run_response)
        self.write_to_storage()

        return workflow_run_response

    async def _aexecute_stream(
        self,
        execution_input: WorkflowExecutionInput,
        workflow_run_response: WorkflowRunResponse,
        stream_intermediate_steps: bool = False,
        **kwargs: Any,
    ) -> AsyncIterator[WorkflowRunResponseEvent]:
        """Execute a specific pipeline by name with event streaming"""

        workflow_run_response.status = RunStatus.running
        workflow_started_event = WorkflowStartedEvent(
            run_id=workflow_run_response.run_id or "",
            workflow_name=workflow_run_response.workflow_name,
            workflow_id=workflow_run_response.workflow_id,
            session_id=workflow_run_response.session_id,
        )
        yield self._handle_event(workflow_started_event, workflow_run_response)

        if isinstance(self.steps, Callable):
            if inspect.iscoroutinefunction(self.steps):
                workflow_run_response.content = await self.steps(self, execution_input, **kwargs)
            elif inspect.isgeneratorfunction(self.steps):
                content = ""
                for chunk in self.steps(self, execution_input, **kwargs):
                    if hasattr(chunk, "content") and chunk.content is not None and isinstance(chunk.content, str):
                        content += chunk.content
                        yield chunk
                    else:
                        content += str(chunk)
                workflow_run_response.content = content
            elif inspect.isasyncgenfunction(self.steps):
                content = ""
                async_gen = await self._acall_custom_function(self.steps, self, execution_input, **kwargs)
                async for chunk in async_gen:
                    if hasattr(chunk, "content") and chunk.content is not None and isinstance(chunk.content, str):
                        content += chunk.content
                        yield chunk
                    else:
                        content += str(chunk)
                workflow_run_response.content = content
            else:
                workflow_run_response.content = self.steps(self, execution_input, **kwargs)
            workflow_run_response.status = RunStatus.completed

        else:
            try:
                # Track outputs from each step for enhanced data flow
                collected_step_outputs: List[Union[StepOutput, List[StepOutput]]] = []
                previous_step_outputs: Dict[str, StepOutput] = {}

                shared_images = execution_input.images or []
                output_images = []
                shared_videos = execution_input.videos or []
                output_videos = []
                shared_audio = execution_input.audio or []
                output_audio = []

                early_termination = False

                for i, step in enumerate(self.steps):
                    step_name = getattr(step, "name", f"step_{i + 1}")
                    log_debug(f"Async streaming step {i + 1}/{self._get_step_count()}: {step_name}")

                    # Create enhanced StepInput
                    step_input = self._create_step_input(
                        execution_input=execution_input,
                        previous_step_outputs=previous_step_outputs,
                        shared_images=shared_images,
                        shared_videos=shared_videos,
                        shared_audio=shared_audio,
                    )

                    # Execute step with streaming and yield all events
                    async for event in step.aexecute_stream(
                        step_input,
                        session_id=self.session_id,
                        user_id=self.user_id,
                        stream_intermediate_steps=stream_intermediate_steps,
                        workflow_run_response=workflow_run_response,
                        step_index=i,
                    ):
                        if isinstance(event, StepOutput):
                            step_output = event
                            collected_step_outputs.append(step_output)

                            # Update the workflow-level previous_step_outputs dictionary
                            previous_step_outputs[step_name] = step_output

                            # Transform StepOutput to StepOutputEvent for consistent streaming interface
                            step_output_event = self._transform_step_output_to_event(
                                step_output, workflow_run_response, step_index=i
                            )

                            if step_output.stop:
                                logger.info(f"Early termination requested by step {step_name}")
                                # Update shared media for next step
                                shared_images.extend(step_output.images or [])
                                shared_videos.extend(step_output.videos or [])
                                shared_audio.extend(step_output.audio or [])
                                output_images.extend(step_output.images or [])
                                output_videos.extend(step_output.videos or [])
                                output_audio.extend(step_output.audio or [])

                                if getattr(step, "executor_type", None) == "function":
                                    yield step_output_event

                                # Break out of the step loop
                                early_termination = True
                                break

                            # Update shared media for next step
                            shared_images.extend(step_output.images or [])
                            shared_videos.extend(step_output.videos or [])
                            shared_audio.extend(step_output.audio or [])
                            output_images.extend(step_output.images or [])
                            output_videos.extend(step_output.videos or [])
                            output_audio.extend(step_output.audio or [])

                            # Only yield StepOutputEvent for generator functions, not for agents/teams
                            if getattr(step, "executor_type", None) == "function":
                                yield step_output_event

                        elif isinstance(event, WorkflowRunResponseEvent):
                            yield self._handle_event(event, workflow_run_response)

                        else:
                            # Yield other internal events
                            yield event

                    # Break out of main step loop if early termination was requested
                    if "early_termination" in locals() and early_termination:
                        break

                    self._collect_workflow_session_state_from_agents_and_teams()

                # Update the workflow_run_response with completion data
                if collected_step_outputs:
                    workflow_run_response.workflow_metrics = self._aggregate_workflow_metrics(collected_step_outputs)
                    last_output = collected_step_outputs[-1]
                    if isinstance(last_output, list) and last_output:
                        # If it's a list (from Condition/Loop/etc.), use the last one
                        workflow_run_response.content = last_output[-1].content
                    else:
                        # Single StepOutput
                        workflow_run_response.content = last_output.content
                else:
                    workflow_run_response.content = "No steps executed"

                workflow_run_response.step_responses = collected_step_outputs
                workflow_run_response.images = output_images
                workflow_run_response.videos = output_videos
                workflow_run_response.audio = output_audio
                workflow_run_response.status = RunStatus.completed

            except Exception as e:
                logger.error(f"Workflow execution failed: {e}")

                from agno.run.v2.workflow import WorkflowErrorEvent

                error_event = WorkflowErrorEvent(
                    run_id=self.run_id or "",
                    workflow_id=self.workflow_id,
                    workflow_name=self.name,
                    session_id=self.session_id,
                    error=str(e),
                )

                yield error_event

                # Update workflow_run_response with error
                workflow_run_response.content = error_event.error
                workflow_run_response.status = RunStatus.error

        # Yield workflow completed event
        workflow_completed_event = WorkflowCompletedEvent(
            run_id=workflow_run_response.run_id or "",
            content=workflow_run_response.content,
            workflow_name=workflow_run_response.workflow_name,
            workflow_id=workflow_run_response.workflow_id,
            session_id=workflow_run_response.session_id,
            step_responses=workflow_run_response.step_responses,
            extra_data=workflow_run_response.extra_data,
        )
        yield self._handle_event(workflow_completed_event, workflow_run_response)

        # Store the completed workflow response
        if self.workflow_session:
            self.workflow_session.add_run(workflow_run_response)

        # Save to storage after complete execution
        self.write_to_storage()

    def _update_workflow_session_state(self):
        if not self.workflow_session_state:
            self.workflow_session_state = {}

        self.workflow_session_state.update(
            {
                "workflow_id": self.workflow_id,
                "run_id": self.run_id,
                "session_id": self.session_id,
                "session_name": self.session_name,
            }
        )
        if self.name:
            self.workflow_session_state["workflow_name"] = self.name

        return self.workflow_session_state

    @overload
    def run(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: Literal[False] = False,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> WorkflowRunResponse: ...

    @overload
    def run(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: Literal[True] = True,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> Iterator[WorkflowRunResponseEvent]: ...

    def run(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: bool = False,
        stream_intermediate_steps: Optional[bool] = None,
        **kwargs: Any,
    ) -> Union[WorkflowRunResponse, Iterator[WorkflowRunResponseEvent]]:
        """Execute the workflow synchronously with optional streaming"""
        self._set_debug()

        log_debug(f"Workflow Run Start: {self.name}", center=True)

        # Use simple defaults
        stream = stream or self.stream or False
        stream_intermediate_steps = stream_intermediate_steps or self.stream_intermediate_steps or False

        # Can't have stream_intermediate_steps if stream is False
        if not stream:
            stream_intermediate_steps = False

        log_debug(f"Stream: {stream}")
        log_debug(f"Total steps: {self._get_step_count()}")

        if user_id is not None:
            self.user_id = user_id
            log_debug(f"User ID: {user_id}")
        if session_id is not None:
            self.session_id = session_id
            log_debug(f"Session ID: {session_id}")

        self.run_id = str(uuid4())

        self.initialize_workflow()

        # Load or create session
        self.load_session()

        # Prepare steps
        self._prepare_steps()

        # Create workflow run response that will be updated by reference
        workflow_run_response = WorkflowRunResponse(
            run_id=self.run_id,
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            created_at=int(datetime.now().timestamp()),
        )
        self.run_response = workflow_run_response

        inputs = WorkflowExecutionInput(
            message=message,
            audio=audio,
            images=images,
            videos=videos,
        )
        log_debug(
            f"Created pipeline input with session state keys: {list(self.workflow_session_state.keys()) if self.workflow_session_state else 'None'}"
        )

        self.update_agents_and_teams_session_info()

        if stream:
            return self._execute_stream(
                execution_input=inputs,
                workflow_run_response=workflow_run_response,
                stream_intermediate_steps=stream_intermediate_steps,
                **kwargs,
            )
        else:
            return self._execute(execution_input=inputs, workflow_run_response=workflow_run_response, **kwargs)

    @overload
    async def arun(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: Literal[False] = False,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> WorkflowRunResponse: ...

    @overload
    async def arun(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: Literal[True] = True,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> AsyncIterator[WorkflowRunResponseEvent]: ...

    async def arun(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: bool = False,
        stream_intermediate_steps: bool = False,
        **kwargs: Any,
    ) -> Union[WorkflowRunResponse, AsyncIterator[WorkflowRunResponseEvent]]:
        """Execute the workflow synchronously with optional streaming"""
        log_debug(f"Async Workflow Run Start: {self.name}", center=True)

        # Use simple defaults
        stream = stream or self.stream or False
        stream_intermediate_steps = stream_intermediate_steps or self.stream_intermediate_steps or False

        # Can't have stream_intermediate_steps if stream is False
        if not stream:
            stream_intermediate_steps = False

        log_debug(f"Stream: {stream}")

        # Set user_id and session_id if provided
        if user_id is not None:
            self.user_id = user_id
            log_debug(f"User ID: {user_id}")
        if session_id is not None:
            self.session_id = session_id
            log_debug(f"Session ID: {session_id}")

        self.run_id = str(uuid4())

        self.initialize_workflow()

        # Load or create session
        self.load_session()

        # Prepare steps
        self._prepare_steps()

        # Create workflow run response that will be updated by reference
        workflow_run_response = WorkflowRunResponse(
            run_id=self.run_id,
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            created_at=int(datetime.now().timestamp()),
        )
        self.run_response = workflow_run_response

        inputs = WorkflowExecutionInput(
            message=message,
            audio=audio,
            images=images,
            videos=videos,
        )
        log_debug(
            f"Created async pipeline input with session state keys: {list(self.workflow_session_state.keys()) if self.workflow_session_state else 'None'}"
        )

        self.update_agents_and_teams_session_info()

        if stream:
            return self._aexecute_stream(
                execution_input=inputs,
                workflow_run_response=workflow_run_response,
                stream_intermediate_steps=stream_intermediate_steps,
                **kwargs,
            )
        else:
            return await self._aexecute(execution_input=inputs, workflow_run_response=workflow_run_response, **kwargs)

    def _prepare_steps(self):
        """Prepare the steps for execution"""
        prepared_steps = []
        if not isinstance(self.steps, Callable):
            for step in self.steps:
                if isinstance(step, Callable):
                    prepared_steps.append(
                        Step(name=step.__name__, description="User-defined callable step", executor=step)
                    )
                elif isinstance(step, Agent):
                    prepared_steps.append(Step(name=step.name, description=step.description, agent=step))
                elif isinstance(step, Team):
                    prepared_steps.append(Step(name=step.name, description=step.description, team=step))
                elif isinstance(step, (Step, Steps, Loop, Parallel, Condition, Router)):
                    prepared_steps.append(step)
                else:
                    raise ValueError(f"Invalid step type: {type(step).__name__}")

            self.steps = prepared_steps

    def get_workflow_session(self) -> WorkflowSessionV2:
        """Get a WorkflowSessionV2 object for storage"""
        workflow_data = {}
        # TODO: Handle recursive
        if self.steps and not isinstance(self.steps, Callable):
            workflow_data["steps"] = [
                {
                    "name": step.name if hasattr(step, "name") else step.__name__,
                    "description": step.description if hasattr(step, "description") else "User-defined callable step",
                }
                for step in self.steps
            ]
        elif isinstance(self.steps, Callable):
            workflow_data["steps"] = [
                {
                    "name": "Custom Function",
                    "description": "User-defined callable workflow",
                }
            ]

        return WorkflowSessionV2(
            session_id=self.session_id,
            user_id=self.user_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            runs=self.workflow_session.runs if self.workflow_session else [],
            workflow_data=workflow_data,
            session_data={},
        )

    def load_workflow_session(self, session: WorkflowSessionV2):
        """Load workflow session from storage"""
        if self.workflow_id is None and session.workflow_id is not None:
            self.workflow_id = session.workflow_id
        if self.user_id is None and session.user_id is not None:
            self.user_id = session.user_id
        if self.session_id is None and session.session_id is not None:
            self.session_id = session.session_id
        if self.name is None and session.workflow_name is not None:
            self.name = session.workflow_name

        self.workflow_session = session
        log_debug(f"Loaded WorkflowSessionV2: {session.session_id}")

    def read_from_storage(self) -> Optional[WorkflowSessionV2]:
        """Load the WorkflowSessionV2 from storage"""
        if self.storage is not None and self.session_id is not None:
            session = self.storage.read(session_id=self.session_id)
            if session and isinstance(session, WorkflowSessionV2):
                self.load_workflow_session(session)
                return session
        return None

    def write_to_storage(self) -> Optional[WorkflowSessionV2]:
        """Save the WorkflowSessionV2 to storage"""
        if self.storage is not None:
            session_to_save = self.get_workflow_session()
            saved_session = self.storage.upsert(session=session_to_save)
            if saved_session and isinstance(saved_session, WorkflowSessionV2):
                self.workflow_session = saved_session
                return saved_session
        return None

    def load_session(self, force: bool = False) -> Optional[str]:
        """Load an existing session from storage or create a new one"""
        log_debug(f"Current session_id: {self.session_id}")

        if self.workflow_session is not None and not force:
            if self.session_id is not None and self.workflow_session.session_id == self.session_id:
                log_debug("Using existing workflow session")
                return self.workflow_session.session_id

        if self.storage is not None:
            # Try to load existing session
            log_debug(f"Reading WorkflowSessionV2: {self.session_id}")
            existing_session = self.read_from_storage()

            # Create new session if it doesn't exist
            if existing_session is None:
                log_debug("Creating new WorkflowSessionV2")
                self.workflow_session = WorkflowSessionV2(
                    session_id=self.session_id,  # type: ignore
                    user_id=self.user_id,
                    workflow_id=self.workflow_id,
                    workflow_name=self.name,
                )
                saved_session = self.write_to_storage()
                if saved_session is None:
                    raise Exception("Failed to create new WorkflowSessionV2 in storage")
                log_debug(f"Created WorkflowSessionV2: {saved_session.session_id}")

        return self.session_id

    def new_session(self) -> None:
        """Create a new workflow session"""
        log_debug("Creating new workflow session")

        self.workflow_session = None
        self.session_id = str(uuid4())

        log_debug(f"New session ID: {self.session_id}")
        self.load_session(force=True)

    def _format_step_content_for_display(self, step_output: StepOutput) -> str:
        """Format content for display, handling structured outputs. Works for both raw content and StepOutput objects."""
        # If it's a StepOutput, extract the content
        if hasattr(step_output, "content"):
            actual_content = step_output.content
        else:
            actual_content = step_output

        if not actual_content:
            return ""

        # If it's already a string, return as-is
        if isinstance(actual_content, str):
            return actual_content

        # If it's a structured output (BaseModel or dict), format it nicely
        if isinstance(actual_content, BaseModel):
            return (
                f"**Structured Output:**\n\n```json\n{actual_content.model_dump_json(indent=2, exclude_none=True)}\n```"
            )
        elif isinstance(actual_content, (dict, list)):
            import json

            return f"**Structured Output:**\n\n```json\n{json.dumps(actual_content, indent=2, default=str)}\n```"
        else:
            # Fallback to string conversion
            return str(actual_content)

    def print_response(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: bool = False,
        stream_intermediate_steps: bool = False,
        markdown: bool = True,
        show_time: bool = True,
        show_step_details: bool = True,
        console: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Print workflow execution with rich formatting and optional streaming

        Args:
            message: The main query/input for the workflow
            message_data: Attached message data to the input
            user_id: User ID
            session_id: Session ID
            audio: Audio input
            images: Image input
            videos: Video input
            stream: Whether to stream the response content
            stream_intermediate_steps: Whether to stream intermediate steps
            markdown: Whether to render content as markdown
            show_time: Whether to show execution time
            show_step_details: Whether to show individual step outputs
            console: Rich console instance (optional)
        """

        stream_intermediate_steps = stream_intermediate_steps or self.stream_intermediate_steps or False
        stream = stream or self.stream or False

        if stream:
            self._print_response_stream(
                message=message,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
                stream_intermediate_steps=stream_intermediate_steps,
                markdown=markdown,
                show_time=show_time,
                show_step_details=show_step_details,
                console=console,
                **kwargs,
            )
        else:
            self._print_response(
                message=message,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
                markdown=markdown,
                show_time=show_time,
                show_step_details=show_step_details,
                console=console,
                **kwargs,
            )

    def _print_response(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        markdown: bool = True,
        show_time: bool = True,
        show_step_details: bool = True,
        console: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Print workflow execution with rich formatting (non-streaming)"""
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        from agno.utils.response import create_panel
        from agno.utils.timer import Timer

        if console is None:
            from agno.cli.console import console

        # Show workflow info
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        workflow_info = f"""**Workflow:** {self.name}"""
        if self.description:
            workflow_info += f"""\n\n**Description:** {self.description}"""
        workflow_info += f"""\n\n**Steps:** {self._get_step_count()} steps"""
        if message:
            if isinstance(message, str):
                workflow_info += f"""\n\n**Message:** {message}"""
            else:
                # Handle structured input message
                if isinstance(message, BaseModel):
                    data_display = message.model_dump_json(indent=2, exclude_none=True)
                elif isinstance(message, (dict, list)):
                    import json

                    data_display = json.dumps(message, indent=2, default=str)
                else:
                    data_display = str(message)
                workflow_info += f"""\n\n**Structured Input:**\n```json\n{data_display}\n```"""
        if user_id:
            workflow_info += f"""\n\n**User ID:** {user_id}"""
        if session_id:
            workflow_info += f"""\n\n**Session ID:** {session_id}"""
        workflow_info = workflow_info.strip()

        workflow_panel = create_panel(
            content=Markdown(workflow_info) if markdown else workflow_info,
            title="Workflow Information",
            border_style="cyan",
        )
        console.print(workflow_panel)

        # Start timer
        response_timer = Timer()
        response_timer.start()

        with Live(console=console) as live_log:
            status = Status("Starting workflow...", spinner="dots")
            live_log.update(status)

            try:
                # Execute workflow and get the response directly
                workflow_response: WorkflowRunResponse = self.run(
                    message=message,
                    user_id=user_id,
                    session_id=session_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    **kwargs,
                )

                response_timer.stop()

                if show_step_details and workflow_response.step_responses:
                    for i, step_output in enumerate(workflow_response.step_responses):
                        # Handle both single StepOutput and List[StepOutput] (from loop/parallel steps)
                        if isinstance(step_output, list):
                            # This is a loop or parallel step with multiple outputs
                            for j, sub_step_output in enumerate(step_output):
                                if sub_step_output.content:
                                    formatted_content = self._format_step_content_for_display(sub_step_output)
                                    step_panel = create_panel(
                                        content=Markdown(formatted_content) if markdown else formatted_content,
                                        title=f"Step {i + 1}.{j + 1}: {sub_step_output.step_name} (Completed)",
                                        border_style="green",
                                    )
                                    console.print(step_panel)
                        else:
                            # This is a regular single step
                            if step_output.content:
                                formatted_content = self._format_step_content_for_display(step_output)
                                step_panel = create_panel(
                                    content=Markdown(formatted_content) if markdown else formatted_content,
                                    title=f"Step {i + 1}: {step_output.step_name} (Completed)",
                                    border_style="green",
                                )
                                console.print(step_panel)

                # For callable functions, show the content directly since there are no step_responses
                elif show_step_details and isinstance(self.steps, Callable) and workflow_response.content:
                    step_panel = create_panel(
                        content=Markdown(workflow_response.content) if markdown else workflow_response.content,
                        title="Custom Function (Completed)",
                        border_style="green",
                    )
                    console.print(step_panel)

                # Show final summary
                if workflow_response.extra_data:
                    status = workflow_response.status.value
                    summary_content = ""
                    summary_content += f"""\n\n**Status:** {status}"""
                    summary_content += f"""\n\n**Steps Completed:** {len(workflow_response.step_responses) if workflow_response.step_responses else 0}"""
                    summary_content = summary_content.strip()

                    summary_panel = create_panel(
                        content=Markdown(summary_content) if markdown else summary_content,
                        title="Execution Summary",
                        border_style="blue",
                    )
                    console.print(summary_panel)

                live_log.update("")

                # Final completion message
                if show_time:
                    completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                    console.print(completion_text)

            except Exception as e:
                import traceback

                traceback.print_exc()
                response_timer.stop()
                error_panel = create_panel(
                    content=f"Workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
                )
                console.print(error_panel)

    def _print_response_stream(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream_intermediate_steps: bool = False,
        markdown: bool = True,
        show_time: bool = True,
        show_step_details: bool = True,
        console: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Print workflow execution with clean streaming - green step blocks displayed once"""
        from rich.console import Group
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        from agno.utils.response import create_panel
        from agno.utils.timer import Timer

        if console is None:
            from agno.cli.console import console

        stream_intermediate_steps = True  # With streaming print response, we need to stream intermediate steps

        # Show workflow info (same as before)
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        workflow_info = f"""**Workflow:** {self.name}"""
        if self.description:
            workflow_info += f"""\n\n**Description:** {self.description}"""
        workflow_info += f"""\n\n**Steps:** {self._get_step_count()} steps"""
        if message:
            if isinstance(message, str):
                workflow_info += f"""\n\n**Message:** {message}"""
            else:
                # Handle structured input message
                if isinstance(message, BaseModel):
                    data_display = message.model_dump_json(indent=2, exclude_none=True)
                elif isinstance(message, (dict, list)):
                    import json

                    data_display = json.dumps(message, indent=2, default=str)
                else:
                    data_display = str(message)
                workflow_info += f"""\n\n**Structured Input:**\n```json\n{data_display}\n```"""
        if user_id:
            workflow_info += f"""\n\n**User ID:** {user_id}"""
        if session_id:
            workflow_info += f"""\n\n**Session ID:** {session_id}"""
        workflow_info = workflow_info.strip()

        workflow_panel = create_panel(
            content=Markdown(workflow_info) if markdown else workflow_info,
            title="Workflow Information",
            border_style="cyan",
        )
        console.print(workflow_panel)

        # Start timer
        response_timer = Timer()
        response_timer.start()

        # Streaming execution variables
        current_step_content = ""
        current_step_name = ""
        current_step_index = 0
        step_responses = []
        step_started_printed = False
        is_callable_function = isinstance(self.steps, Callable)

        with Live(console=console, refresh_per_second=10) as live_log:
            status = Status("Starting workflow...", spinner="dots")
            live_log.update(status)

            try:
                for response in self.run(
                    message=message,
                    user_id=user_id,
                    session_id=session_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    stream=True,
                    stream_intermediate_steps=stream_intermediate_steps,
                    **kwargs,
                ):
                    # Handle the new event types
                    if isinstance(response, WorkflowStartedEvent):
                        status.update("Workflow started...")
                        if is_callable_function:
                            current_step_name = "Custom Function"
                            current_step_index = 0
                        live_log.update(status)

                    elif isinstance(response, StepStartedEvent):
                        current_step_name = response.step_name or "Unknown"
                        current_step_index = response.step_index or 0
                        current_step_content = ""
                        step_started_printed = False
                        status.update(f"Starting step {current_step_index + 1}: {current_step_name}...")
                        live_log.update(status)

                    elif isinstance(response, StepCompletedEvent):
                        step_name = response.step_name or "Unknown"
                        step_index = response.step_index or 0

                        status.update(f"Completed step {step_index + 1}: {step_name}")

                        if response.content:
                            step_responses.append(
                                {
                                    "step_name": step_name,
                                    "step_index": step_index,
                                    "content": response.content,
                                    "event": response.event,
                                }
                            )

                        # Print the final step result in green (only once)
                        if show_step_details and current_step_content and not step_started_printed:
                            live_log.update(status, refresh=True)

                            final_step_panel = create_panel(
                                content=Markdown(current_step_content) if markdown else current_step_content,
                                title=f"Step {step_index + 1}: {step_name} (Completed)",
                                border_style="green",
                            )
                            console.print(final_step_panel)
                            step_started_printed = True

                    elif isinstance(response, LoopExecutionStartedEvent):
                        current_step_name = response.step_name or "Loop"
                        current_step_index = response.step_index or 0
                        current_step_content = ""
                        step_started_printed = False
                        status.update(
                            f"Starting loop: {current_step_name} (max {response.max_iterations} iterations)..."
                        )
                        live_log.update(status)

                    elif isinstance(response, LoopIterationStartedEvent):
                        status.update(
                            f"Loop iteration {response.iteration}/{response.max_iterations}: {response.step_name}..."
                        )
                        live_log.update(status)

                    elif isinstance(response, LoopIterationCompletedEvent):
                        status.update(
                            f"Completed iteration {response.iteration}/{response.max_iterations}: {response.step_name}"
                        )

                        # Add iteration results to step_responses
                        if response.iteration_results:
                            for i, result in enumerate(response.iteration_results):
                                step_responses.append(
                                    {
                                        "step_name": f"{response.step_name}.{response.iteration}.{i + 1}: {result.step_name}",
                                        "step_index": response.step_index,
                                        "content": result.content,
                                        "event": "LoopIterationResult",
                                    }
                                )

                    elif isinstance(response, LoopExecutionCompletedEvent):
                        step_name = response.step_name or "Loop"
                        step_index = response.step_index or 0

                        status.update(f"Completed loop: {step_name} ({response.total_iterations} iterations)")
                        live_log.update(status, refresh=True)

                        # Print loop summary
                        if show_step_details:
                            summary_content = "**Loop Summary:**\n\n"
                            summary_content += (
                                f"- Total iterations: {response.total_iterations}/{response.max_iterations}\n"
                            )
                            summary_content += (
                                f"- Total steps executed: {sum(len(iteration) for iteration in response.all_results)}\n"
                            )

                            loop_summary_panel = create_panel(
                                content=Markdown(summary_content) if markdown else summary_content,
                                title=f"Loop {step_name} (Completed)",
                                border_style="yellow",
                            )
                            console.print(loop_summary_panel)

                        step_started_printed = True

                    elif isinstance(response, ParallelExecutionStartedEvent):
                        current_step_name = response.step_name or "Parallel Steps"
                        current_step_index = response.step_index or 0
                        current_step_content = ""
                        step_started_printed = False
                        status.update(
                            f"Starting parallel execution: {current_step_name} ({response.parallel_step_count} steps)..."
                        )
                        live_log.update(status)

                    elif isinstance(response, ParallelExecutionCompletedEvent):
                        step_name = response.step_name or "Parallel Steps"
                        step_index = response.step_index or 0

                        status.update(f"Completed parallel execution: {step_name}")

                        # Add results from all parallel steps to step_responses
                        if response.step_results:
                            for i, step_result in enumerate(response.step_results):
                                step_responses.append(
                                    {
                                        "step_name": f"{step_name}.{i + 1}: {step_result.step_name}",
                                        "step_index": step_index,
                                        "content": step_result.content,
                                        "event": "ParallelStepResult",
                                    }
                                )

                    elif isinstance(response, ConditionExecutionStartedEvent):
                        current_step_name = response.step_name or "Condition"
                        current_step_index = response.step_index or 0
                        current_step_content = ""
                        step_started_printed = False
                        condition_text = "met" if response.condition_result else "not met"
                        status.update(f"Starting condition: {current_step_name} (condition {condition_text})...")
                        live_log.update(status)

                    elif isinstance(response, ConditionExecutionCompletedEvent):
                        step_name = response.step_name or "Condition"
                        step_index = response.step_index or 0

                        status.update(f"Completed condition: {step_name}")

                        # Add results from executed steps to step_responses
                        if response.step_results:
                            for i, step_result in enumerate(response.step_results):
                                step_responses.append(
                                    {
                                        "step_name": f"{step_name}: {step_result.step_name}",
                                        "step_index": step_index,
                                        "content": step_result.content,
                                        "event": "ConditionStepResult",
                                    }
                                )

                    elif isinstance(response, RouterExecutionStartedEvent):
                        current_step_name = response.step_name or "Router"
                        current_step_index = response.step_index or 0
                        current_step_content = ""
                        step_started_printed = False
                        selected_steps_text = ", ".join(response.selected_steps) if response.selected_steps else "none"
                        status.update(f"Starting router: {current_step_name} (selected: {selected_steps_text})...")
                        live_log.update(status)

                    elif isinstance(response, RouterExecutionCompletedEvent):
                        step_name = response.step_name or "Router"
                        step_index = response.step_index or 0

                        status.update(f"Completed router: {step_name}")

                        # Add results from executed steps to step_responses
                        if response.step_results:
                            for i, step_result in enumerate(response.step_results):
                                step_responses.append(
                                    {
                                        "step_name": f"{step_name}: {step_result.step_name}",
                                        "step_index": step_index,
                                        "content": step_result.content,
                                        "event": "RouterStepResult",
                                    }
                                )

                        # Print router summary
                        if show_step_details:
                            selected_steps_text = (
                                ", ".join(response.selected_steps) if response.selected_steps else "none"
                            )
                            summary_content = "**Router Summary:**\n\n"
                            summary_content += f"- Selected steps: {selected_steps_text}\n"
                            summary_content += f"- Executed steps: {response.executed_steps or 0}\n"

                            router_summary_panel = create_panel(
                                content=Markdown(summary_content) if markdown else summary_content,
                                title=f"Router {step_name} (Completed)",
                                border_style="purple",
                            )
                            console.print(router_summary_panel)

                        step_started_printed = True

                    elif isinstance(response, WorkflowCompletedEvent):
                        status.update("Workflow completed!")

                        # For callable functions, print the final content block here since there are no step events
                        if (
                            is_callable_function
                            and show_step_details
                            and current_step_content
                            and not step_started_printed
                        ):
                            final_step_panel = create_panel(
                                content=Markdown(current_step_content) if markdown else current_step_content,
                                title="Custom Function (Completed)",
                                border_style="green",
                            )
                            console.print(final_step_panel)
                            step_started_printed = True

                        live_log.update(status, refresh=True)

                        # Show final summary
                        if response.extra_data:
                            status = response.status
                            summary_content = ""
                            summary_content += f"""\n\n**Status:** {status}"""
                            summary_content += f"""\n\n**Steps Completed:** {len(response.step_responses) if response.step_responses else 0}"""
                            summary_content = summary_content.strip()

                            summary_panel = create_panel(
                                content=Markdown(summary_content) if markdown else summary_content,
                                title="Execution Summary",
                                border_style="blue",
                            )
                            console.print(summary_panel)

                    else:
                        if isinstance(response, str):
                            response_str = response
                        elif isinstance(response, StepOutputEvent):
                            # Handle StepOutputEvent objects yielded from workflow
                            response_str = response.content or ""
                        else:
                            from agno.run.response import RunResponseContentEvent
                            from agno.run.team import RunResponseContentEvent as TeamRunResponseContentEvent

                            current_step_executor_type = None
                            if not is_callable_function and self.steps and current_step_index < len(self.steps):
                                step = self.steps[current_step_index]
                                if hasattr(step, "executor_type"):
                                    current_step_executor_type = step.executor_type

                            # Check if this is a streaming content event from agent or team
                            if isinstance(
                                response,
                                (TeamRunResponseContentEvent, WorkflowRunResponseEvent),
                            ):
                                # Check if this is a team's final structured output
                                is_structured_output = (
                                    isinstance(response, TeamRunResponseContentEvent)
                                    and hasattr(response, "content_type")
                                    and response.content_type != "str"
                                    and response.content_type != ""
                                )

                                # Extract the content from the streaming event
                                response_str = response.content
                            elif isinstance(response, RunResponseContentEvent) and current_step_executor_type != "team":
                                response_str = response.content
                            else:
                                continue

                        # Use the unified formatting function for consistency
                        response_str = self._format_step_content_for_display(response_str)

                        # Filter out empty responses and add to current step content
                        if response_str and response_str.strip():
                            # If it's a structured output from a team, replace the content instead of appending
                            if "is_structured_output" in locals() and is_structured_output:
                                current_step_content = response_str
                            else:
                                current_step_content += response_str

                            # Live update the step panel with streaming content
                            if show_step_details and not step_started_printed:
                                # For callable functions, show different title during streaming
                                title = f"Step {current_step_index + 1}: {current_step_name} (Streaming...)"
                                if is_callable_function:
                                    title = "Custom Function (Streaming...)"

                                # Show the streaming content live in green panel
                                live_step_panel = create_panel(
                                    content=Markdown(current_step_content) if markdown else current_step_content,
                                    title=title,
                                    border_style="green",
                                )

                                # Create group with status and current step content
                                group = Group(status, live_step_panel)
                                live_log.update(group)

                response_timer.stop()

                live_log.update("")

                # Final completion message
                if show_time:
                    completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                    console.print(completion_text)

            except Exception as e:
                import traceback

                traceback.print_exc()
                response_timer.stop()
                error_panel = create_panel(
                    content=f"Workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
                )
                console.print(error_panel)

    async def aprint_response(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: bool = False,
        stream_intermediate_steps: bool = False,
        markdown: bool = True,
        show_time: bool = True,
        show_step_details: bool = True,
        console: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Print workflow execution with rich formatting and optional streaming

        Args:
            message: The main message/input for the workflow
            message_data: Attached message data to the input
            user_id: User ID
            session_id: Session ID
            audio: Audio input
            images: Image input
            videos: Video input
            stream_intermediate_steps: Whether to stream intermediate steps
            stream: Whether to stream the response content
            markdown: Whether to render content as markdown
            show_time: Whether to show execution time
            show_step_details: Whether to show individual step outputs
            console: Rich console instance (optional)
        """
        if stream:
            await self._aprint_response_stream(
                message=message,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
                stream_intermediate_steps=stream_intermediate_steps,
                markdown=markdown,
                show_time=show_time,
                show_step_details=show_step_details,
                console=console,
                **kwargs,
            )
        else:
            await self._aprint_response(
                message=message,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
                markdown=markdown,
                show_time=show_time,
                show_step_details=show_step_details,
                console=console,
                **kwargs,
            )

    async def _aprint_response(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        markdown: bool = True,
        show_time: bool = True,
        show_step_details: bool = True,
        console: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Print workflow execution with rich formatting (non-streaming)"""
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        from agno.utils.response import create_panel
        from agno.utils.timer import Timer

        if console is None:
            from agno.cli.console import console

        # Show workflow info
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        workflow_info = f"""**Workflow:** {self.name}"""
        if self.description:
            workflow_info += f"""\n\n**Description:** {self.description}"""
        workflow_info += f"""\n\n**Steps:** {self._get_step_count()} steps"""
        if message:
            if isinstance(message, str):
                workflow_info += f"""\n\n**Message:** {message}"""
            else:
                # Handle structured input message
                if isinstance(message, BaseModel):
                    data_display = message.model_dump_json(indent=2, exclude_none=True)
                elif isinstance(message, (dict, list)):
                    import json

                    data_display = json.dumps(message, indent=2, default=str)
                else:
                    data_display = str(message)
                workflow_info += f"""\n\n**Structured Input:**\n```json\n{data_display}\n```"""
        if user_id:
            workflow_info += f"""\n\n**User ID:** {user_id}"""
        if session_id:
            workflow_info += f"""\n\n**Session ID:** {session_id}"""
        workflow_info = workflow_info.strip()

        workflow_panel = create_panel(
            content=Markdown(workflow_info) if markdown else workflow_info,
            title="Workflow Information",
            border_style="cyan",
        )
        console.print(workflow_panel)

        # Start timer
        response_timer = Timer()
        response_timer.start()

        with Live(console=console) as live_log:
            status = Status("Starting async workflow...\n", spinner="dots")
            live_log.update(status)

            try:
                # Execute workflow and get the response directly
                workflow_response: WorkflowRunResponse = await self.arun(
                    message=message,
                    user_id=user_id,
                    session_id=session_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    **kwargs,
                )

                response_timer.stop()

                # Show individual step responses if available
                if show_step_details and workflow_response.step_responses:
                    for i, step_output in enumerate(workflow_response.step_responses):
                        # Handle both single StepOutput and List[StepOutput] (from loop/parallel steps)
                        if isinstance(step_output, list):
                            # This is a loop or parallel step with multiple outputs
                            for j, sub_step_output in enumerate(step_output):
                                if sub_step_output.content:
                                    formatted_content = self._format_step_content_for_display(sub_step_output)
                                    step_panel = create_panel(
                                        content=Markdown(formatted_content) if markdown else formatted_content,
                                        title=f"Step {i + 1}.{j + 1}: {sub_step_output.step_name} (Completed)",
                                        border_style="green",
                                    )
                                    console.print(step_panel)
                        else:
                            # This is a regular single step
                            if step_output.content:
                                formatted_content = self._format_step_content_for_display(step_output)
                                step_panel = create_panel(
                                    content=Markdown(formatted_content) if markdown else formatted_content,
                                    title=f"Step {i + 1}: {step_output.step_name} (Completed)",
                                    border_style="green",
                                )
                                console.print(step_panel)

                # For callable functions, show the content directly since there are no step_responses
                elif show_step_details and isinstance(self.steps, Callable) and workflow_response.content:
                    step_panel = create_panel(
                        content=Markdown(workflow_response.content) if markdown else workflow_response.content,
                        title="Custom Function (Completed)",
                        border_style="green",
                    )
                    console.print(step_panel)

                # Show final summary
                if workflow_response.extra_data:
                    status = workflow_response.status.value
                    summary_content = ""
                    summary_content += f"""\n\n**Status:** {status}"""
                    summary_content += f"""\n\n**Steps Completed:** {len(workflow_response.step_responses) if workflow_response.step_responses else 0}"""
                    summary_content = summary_content.strip()

                    summary_panel = create_panel(
                        content=Markdown(summary_content) if markdown else summary_content,
                        title="Execution Summary",
                        border_style="blue",
                    )
                    console.print(summary_panel)

                live_log.update("")

                # Final completion message
                if show_time:
                    completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                    console.print(completion_text)

            except Exception as e:
                import traceback

                traceback.print_exc()
                response_timer.stop()
                error_panel = create_panel(
                    content=f"Workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
                )
                console.print(error_panel)

    async def _aprint_response_stream(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream_intermediate_steps: bool = False,
        markdown: bool = True,
        show_time: bool = True,
        show_step_details: bool = True,
        console: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Print workflow execution with clean streaming - green step blocks displayed once"""
        from rich.console import Group
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        from agno.utils.response import create_panel
        from agno.utils.timer import Timer

        if console is None:
            from agno.cli.console import console

        stream_intermediate_steps = True  # With streaming print response, we need to stream intermediate steps

        # Show workflow info (same as before)
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        workflow_info = f"""**Workflow:** {self.name}"""
        if self.description:
            workflow_info += f"""\n\n**Description:** {self.description}"""
        workflow_info += f"""\n\n**Steps:** {self._get_step_count()} steps"""
        if message:
            if isinstance(message, str):
                workflow_info += f"""\n\n**Message:** {message}"""
            else:
                # Handle structured input message
                if isinstance(message, BaseModel):
                    data_display = message.model_dump_json(indent=2, exclude_none=True)
                elif isinstance(message, (dict, list)):
                    import json

                    data_display = json.dumps(message, indent=2, default=str)
                else:
                    data_display = str(message)
                workflow_info += f"""\n\n**Structured Input:**\n```json\n{data_display}\n```"""
        if user_id:
            workflow_info += f"""\n\n**User ID:** {user_id}"""
        if session_id:
            workflow_info += f"""\n\n**Session ID:** {session_id}"""
        workflow_info = workflow_info.strip()

        workflow_panel = create_panel(
            content=Markdown(workflow_info) if markdown else workflow_info,
            title="Workflow Information",
            border_style="cyan",
        )
        console.print(workflow_panel)

        # Start timer
        response_timer = Timer()
        response_timer.start()

        # Streaming execution variables
        current_step_content = ""
        current_step_name = ""
        current_step_index = 0
        step_responses = []
        step_started_printed = False
        is_callable_function = isinstance(self.steps, Callable)

        with Live(console=console, refresh_per_second=10) as live_log:
            status = Status("Starting async workflow...", spinner="dots")
            live_log.update(status)

            try:
                async for response in await self.arun(
                    message=message,
                    user_id=user_id,
                    session_id=session_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    stream=True,
                    stream_intermediate_steps=stream_intermediate_steps,
                    **kwargs,
                ):
                    # Handle the new event types
                    if isinstance(response, WorkflowStartedEvent):
                        status.update("Workflow started...")
                        if is_callable_function:
                            current_step_name = "Custom Function"
                            current_step_index = 0
                        live_log.update(status)

                    elif isinstance(response, StepStartedEvent):
                        current_step_name = response.step_name or "Unknown"
                        current_step_index = response.step_index or 0
                        current_step_content = ""
                        step_started_printed = False
                        status.update(f"Starting step {current_step_index + 1}: {current_step_name}...")
                        live_log.update(status)

                    elif isinstance(response, StepCompletedEvent):
                        step_name = response.step_name or "Unknown"
                        step_index = response.step_index or 0

                        status.update(f"Completed step {step_index + 1}: {step_name}")

                        if response.content:
                            step_responses.append(
                                {
                                    "step_name": step_name,
                                    "step_index": step_index,
                                    "content": response.content,
                                    "event": response.event,
                                }
                            )

                        # Print the final step result in green (only once)
                        if show_step_details and current_step_content and not step_started_printed:
                            live_log.update(status, refresh=True)

                            final_step_panel = create_panel(
                                content=Markdown(current_step_content) if markdown else current_step_content,
                                title=f"Step {step_index + 1}: {step_name} (Completed)",
                                border_style="green",
                            )
                            console.print(final_step_panel)
                            step_started_printed = True

                    elif isinstance(response, LoopExecutionStartedEvent):
                        current_step_name = response.step_name or "Loop"
                        current_step_index = response.step_index or 0
                        current_step_content = ""
                        step_started_printed = False
                        status.update(
                            f"Starting loop: {current_step_name} (max {response.max_iterations} iterations)..."
                        )
                        live_log.update(status)

                    elif isinstance(response, LoopIterationStartedEvent):
                        status.update(
                            f"Loop iteration {response.iteration}/{response.max_iterations}: {response.step_name}..."
                        )
                        live_log.update(status)

                    elif isinstance(response, LoopIterationCompletedEvent):
                        status.update(
                            f"Completed iteration {response.iteration}/{response.max_iterations}: {response.step_name}"
                        )

                        # Add iteration results to step_responses
                        if response.iteration_results:
                            for i, result in enumerate(response.iteration_results):
                                step_responses.append(
                                    {
                                        "step_name": f"{response.step_name}.{response.iteration}.{i + 1}: {result.step_name}",
                                        "step_index": response.step_index,
                                        "content": result.content,
                                        "event": "LoopIterationResult",
                                    }
                                )

                    elif isinstance(response, LoopExecutionCompletedEvent):
                        step_name = response.step_name or "Loop"
                        step_index = response.step_index or 0

                        status.update(f"Completed loop: {step_name} ({response.total_iterations} iterations)")
                        live_log.update(status, refresh=True)

                        # Print loop summary
                        if show_step_details:
                            summary_content = "**Loop Summary:**\n\n"
                            summary_content += (
                                f"- Total iterations: {response.total_iterations}/{response.max_iterations}\n"
                            )
                            summary_content += (
                                f"- Total steps executed: {sum(len(iteration) for iteration in response.all_results)}\n"
                            )

                            loop_summary_panel = create_panel(
                                content=Markdown(summary_content) if markdown else summary_content,
                                title=f"Loop {step_name} (Completed)",
                                border_style="yellow",
                            )
                            console.print(loop_summary_panel)

                        step_started_printed = True

                    elif isinstance(response, ConditionExecutionStartedEvent):
                        current_step_name = response.step_name or "Condition"
                        current_step_index = response.step_index or 0
                        current_step_content = ""
                        step_started_printed = False
                        condition_text = "met" if response.condition_result else "not met"
                        status.update(f"Starting condition: {current_step_name} (condition {condition_text})...")
                        live_log.update(status)

                    elif isinstance(response, ConditionExecutionCompletedEvent):
                        step_name = response.step_name or "Condition"
                        step_index = response.step_index or 0

                        status.update(f"Completed condition: {step_name}")

                        # Add results from executed steps to step_responses
                        if response.step_results:
                            for i, step_result in enumerate(response.step_results):
                                step_responses.append(
                                    {
                                        "step_name": f"{step_name}: {step_result.step_name}",
                                        "step_index": step_index,
                                        "content": step_result.content,
                                        "event": "ConditionStepResult",
                                    }
                                )

                    elif isinstance(response, ParallelExecutionStartedEvent):
                        current_step_name = response.step_name or "Parallel Steps"
                        current_step_index = response.step_index or 0
                        current_step_content = ""
                        step_started_printed = False
                        status.update(
                            f"Starting parallel execution: {current_step_name} ({response.parallel_step_count} steps)..."
                        )
                        live_log.update(status)

                    elif isinstance(response, ParallelExecutionCompletedEvent):
                        step_name = response.step_name or "Parallel Steps"
                        step_index = response.step_index or 0

                        status.update(f"Completed parallel execution: {step_name}")

                        # Add results from all parallel steps to step_responses
                        if response.step_results:
                            for i, step_result in enumerate(response.step_results):
                                step_responses.append(
                                    {
                                        "step_name": f"{step_name}.{i + 1}: {step_result.step_name}",
                                        "step_index": step_index,
                                        "content": step_result.content,
                                        "event": "ParallelStepResult",
                                    }
                                )

                    elif isinstance(response, RouterExecutionStartedEvent):
                        current_step_name = response.step_name or "Router"
                        current_step_index = response.step_index or 0
                        current_step_content = ""
                        step_started_printed = False
                        selected_steps_text = ", ".join(response.selected_steps) if response.selected_steps else "none"
                        status.update(f"Starting router: {current_step_name} (selected: {selected_steps_text})...")
                        live_log.update(status)

                    elif isinstance(response, RouterExecutionCompletedEvent):
                        step_name = response.step_name or "Router"
                        step_index = response.step_index or 0

                        status.update(f"Completed router: {step_name}")

                        # Add results from executed steps to step_responses
                        if response.step_results:
                            for i, step_result in enumerate(response.step_results):
                                step_responses.append(
                                    {
                                        "step_name": f"{step_name}: {step_result.step_name}",
                                        "step_index": step_index,
                                        "content": step_result.content,
                                        "event": "RouterStepResult",
                                    }
                                )

                        # Print router summary
                        if show_step_details:
                            selected_steps_text = (
                                ", ".join(response.selected_steps) if response.selected_steps else "none"
                            )
                            summary_content = "**Router Summary:**\n\n"
                            summary_content += f"- Selected steps: {selected_steps_text}\n"
                            summary_content += f"- Executed steps: {response.executed_steps or 0}\n"

                            router_summary_panel = create_panel(
                                content=Markdown(summary_content) if markdown else summary_content,
                                title=f"Router {step_name} (Completed)",
                                border_style="purple",
                            )
                            console.print(router_summary_panel)

                        step_started_printed = True

                    elif isinstance(response, WorkflowCompletedEvent):
                        status.update("Workflow completed!")

                        # For callable functions, print the final content block here since there are no step events
                        if (
                            is_callable_function
                            and show_step_details
                            and current_step_content
                            and not step_started_printed
                        ):
                            final_step_panel = create_panel(
                                content=Markdown(current_step_content) if markdown else current_step_content,
                                title="Custom Function (Completed)",
                                border_style="green",
                            )
                            console.print(final_step_panel)
                            step_started_printed = True

                        live_log.update(status, refresh=True)

                        # Show final summary
                        if response.extra_data:
                            status = response.status
                            summary_content = ""
                            summary_content += f"""\n\n**Status:** {status}"""
                            summary_content += f"""\n\n**Steps Completed:** {len(response.step_responses) if response.step_responses else 0}"""
                            summary_content = summary_content.strip()

                            summary_panel = create_panel(
                                content=Markdown(summary_content) if markdown else summary_content,
                                title="Execution Summary",
                                border_style="blue",
                            )
                            console.print(summary_panel)

                    else:
                        if isinstance(response, str):
                            response_str = response
                        elif isinstance(response, StepOutputEvent):
                            # Handle StepOutputEvent objects yielded from workflow
                            response_str = response.content or ""
                        else:
                            from agno.run.response import RunResponseContentEvent
                            from agno.run.team import RunResponseContentEvent as TeamRunResponseContentEvent

                            current_step_executor_type = None
                            if not is_callable_function and self.steps and current_step_index < len(self.steps):
                                step = self.steps[current_step_index]
                                if hasattr(step, "executor_type"):
                                    current_step_executor_type = step.executor_type

                            # Check if this is a streaming content event from agent or team
                            if isinstance(
                                response,
                                (RunResponseContentEvent, TeamRunResponseContentEvent, WorkflowRunResponseEvent),
                            ):
                                # Extract the content from the streaming event
                                response_str = response.content

                                # Check if this is a team's final structured output
                                is_structured_output = (
                                    isinstance(response, TeamRunResponseContentEvent)
                                    and hasattr(response, "content_type")
                                    and response.content_type != "str"
                                    and response.content_type != ""
                                )
                            elif isinstance(response, RunResponseContentEvent) and current_step_executor_type != "team":
                                response_str = response.content
                            else:
                                continue

                        # Use the unified formatting function for consistency
                        response_str = self._format_step_content_for_display(response_str)

                        # Filter out empty responses and add to current step content
                        if response_str and response_str.strip():
                            # If it's a structured output from a team, replace the content instead of appending
                            if "is_structured_output" in locals() and is_structured_output:
                                current_step_content = response_str
                            else:
                                current_step_content += response_str

                            # Live update the step panel with streaming content
                            if show_step_details and not step_started_printed:
                                # For callable functions, show different title during streaming
                                title = f"Step {current_step_index + 1}: {current_step_name} (Streaming...)"
                                if is_callable_function:
                                    title = "Custom Function (Streaming...)"

                                # Show the streaming content live in green panel
                                live_step_panel = create_panel(
                                    content=Markdown(current_step_content) if markdown else current_step_content,
                                    title=title,
                                    border_style="green",
                                )

                                # Create group with status and current step content
                                group = Group(status, live_step_panel)
                                live_log.update(group)

                response_timer.stop()

                live_log.update("")

                # Final completion message
                if show_time:
                    completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                    console.print(completion_text)

            except Exception as e:
                import traceback

                traceback.print_exc()
                response_timer.stop()
                error_panel = create_panel(
                    content=f"Workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
                )
                console.print(error_panel)

    def to_dict(self) -> Dict[str, Any]:
        """Convert workflow to dictionary representation"""
        # TODO: Handle nested
        return {
            "name": self.name,
            "workflow_id": self.workflow_id,
            "description": self.description,
            "steps": [
                {
                    "name": s.name if hasattr(s, "name") else s.__name__,
                    "description": s.description if hasattr(s, "description") else "User-defined callable step",
                }
                for s in self.steps
            ],
            "session_id": self.session_id,
        }

    def _collect_workflow_session_state_from_agents_and_teams(self):
        """Collect updated workflow_session_state from agents after step execution"""
        if self.workflow_session_state is None:
            self.workflow_session_state = {}

        # Collect state from all agents in all steps
        if self.steps and not isinstance(self.steps, Callable):
            for step in self.steps:
                if isinstance(step, Step):
                    executor = step.active_executor
                    if hasattr(executor, "workflow_session_state") and executor.workflow_session_state:
                        # Merge the agent's session state back into workflow session state
                        from agno.utils.merge_dict import merge_dictionaries

                        merge_dictionaries(self.workflow_session_state, executor.workflow_session_state)

                    # If it's a team, collect from all members
                    if hasattr(executor, "members"):
                        for member in executor.members:
                            if hasattr(member, "workflow_session_state") and member.workflow_session_state:
                                merge_dictionaries(self.workflow_session_state, member.workflow_session_state)

    def _update_executor_workflow_session_state(self, executor) -> None:
        """Update executor with workflow_session_state"""
        if self.workflow_session_state is not None:
            # Update session_state with workflow_session_state
            executor.workflow_session_state = self.workflow_session_state

    def update_agents_and_teams_session_info(self):
        """Update agents and teams with workflow session information"""
        # Initialize steps - only if steps is iterable (not callable)    
        if self.steps and not isinstance(self.steps, Callable):
            for step in self.steps:
                # TODO: Handle properly steps inside other primitives
                if isinstance(step, Step):
                    active_executor = step.active_executor

                    if hasattr(active_executor, "workflow_session_id"):
                        active_executor.workflow_session_id = self.session_id
                    if hasattr(active_executor, "workflow_id"):
                        active_executor.workflow_id = self.workflow_id

                    # Set workflow_session_state on agents and teams
                    self._update_executor_workflow_session_state(active_executor)

                    # If it's a team, update all members
                    if hasattr(active_executor, "members"):
                        for member in active_executor.members:
                            if hasattr(member, "workflow_session_id"):
                                member.workflow_session_id = self.session_id
                            if hasattr(member, "workflow_id"):
                                member.workflow_id = self.workflow_id

                            # Set workflow_session_state on team members
                            self._update_executor_workflow_session_state(member)
