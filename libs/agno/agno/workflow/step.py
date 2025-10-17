import inspect
from copy import copy
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Union
from uuid import uuid4

from pydantic import BaseModel

from agno.agent import Agent
from agno.media import Audio, Image, Video
from agno.models.metrics import Metrics
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.workflow import (
    StepCompletedEvent,
    StepStartedEvent,
    WorkflowRunOutput,
    WorkflowRunOutputEvent,
)
from agno.session.workflow import WorkflowSession
from agno.team import Team
from agno.utils.log import log_debug, logger, use_agent_logger, use_team_logger, use_workflow_logger
from agno.utils.merge_dict import merge_dictionaries
from agno.workflow.types import StepInput, StepOutput, StepType

StepExecutor = Callable[
    [StepInput],
    Union[
        StepOutput,
        Iterator[StepOutput],
        Iterator[Any],
        Awaitable[StepOutput],
        Awaitable[Any],
        AsyncIterator[StepOutput],
        AsyncIterator[Any],
    ],
]


@dataclass
class Step:
    """A single unit of work in a workflow pipeline"""

    name: Optional[str] = None

    # Executor options - only one should be provided
    agent: Optional[Agent] = None
    team: Optional[Team] = None
    executor: Optional[StepExecutor] = None

    step_id: Optional[str] = None
    description: Optional[str] = None

    # Step configuration
    max_retries: int = 3
    timeout_seconds: Optional[int] = None

    skip_on_failure: bool = False

    # Input validation mode
    # If False, only warn about missing inputs
    strict_input_validation: bool = False

    add_workflow_history: Optional[bool] = None
    num_history_runs: int = 3

    _retry_count: int = 0

    def __init__(
        self,
        name: Optional[str] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
        executor: Optional[StepExecutor] = None,
        step_id: Optional[str] = None,
        description: Optional[str] = None,
        max_retries: int = 3,
        timeout_seconds: Optional[int] = None,
        skip_on_failure: bool = False,
        strict_input_validation: bool = False,
        add_workflow_history: Optional[bool] = None,
        num_history_runs: int = 3,
    ):
        # Auto-detect name for function executors if not provided
        if name is None and executor is not None:
            name = getattr(executor, "__name__", None)

        self.name = name
        self.agent = agent
        self.team = team
        self.executor = executor

        # Validate executor configuration
        self._validate_executor_config()

        self.step_id = step_id
        self.description = description
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.skip_on_failure = skip_on_failure
        self.strict_input_validation = strict_input_validation
        self.add_workflow_history = add_workflow_history
        self.num_history_runs = num_history_runs
        self.step_id = step_id

        if step_id is None:
            self.step_id = str(uuid4())

        # Set the active executor
        self._set_active_executor()

    @property
    def executor_name(self) -> str:
        """Get the name of the current executor"""
        if hasattr(self.active_executor, "name"):
            return self.active_executor.name or "unnamed_executor"
        elif self._executor_type == "function":
            return getattr(self.active_executor, "__name__", "anonymous_function")
        else:
            return f"{self._executor_type}_executor"

    @property
    def executor_type(self) -> str:
        """Get the type of the current executor"""
        return self._executor_type

    def _validate_executor_config(self):
        """Validate that only one executor type is provided"""
        executor_count = sum(
            [
                self.agent is not None,
                self.team is not None,
                self.executor is not None,
            ]
        )

        if executor_count == 0:
            raise ValueError(f"Step '{self.name}' must have one executor: agent=, team=, or executor=")

        if executor_count > 1:
            provided_executors = []
            if self.agent is not None:
                provided_executors.append("agent")
            if self.team is not None:
                provided_executors.append("team")
            if self.executor is not None:
                provided_executors.append("executor")

            raise ValueError(
                f"Step '{self.name}' can only have one executor type. "
                f"Provided: {', '.join(provided_executors)}. "
                f"Please use only one of: agent=, team=, or executor="
            )

    def _set_active_executor(self) -> None:
        """Set the active executor based on what was provided"""
        if self.agent is not None:
            self.active_executor = self.agent  # type: ignore[assignment]
            self._executor_type = "agent"
        elif self.team is not None:
            self.active_executor = self.team  # type: ignore[assignment]
            self._executor_type = "team"
        elif self.executor is not None:
            self.active_executor = self.executor  # type: ignore[assignment]
            self._executor_type = "function"
        else:
            raise ValueError("No executor configured")

    def _extract_metrics_from_response(self, response: Union[RunOutput, TeamRunOutput]) -> Optional[Metrics]:
        """Extract metrics from agent or team response"""
        if hasattr(response, "metrics") and response.metrics:
            return response.metrics
        return None

    def _call_custom_function(
        self,
        func: Callable,
        step_input: StepInput,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Call custom function with session_state support if the function accepts it"""
        if session_state is not None and self._function_has_session_state_param():
            return func(step_input, session_state)
        else:
            return func(step_input)

    async def _acall_custom_function(
        self,
        func: Callable,
        step_input: StepInput,
        session_state: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Call custom async function with session_state support if the function accepts it"""
        import inspect

        if inspect.isasyncgenfunction(func):
            if session_state is not None and self._function_has_session_state_param():
                return func(step_input, session_state)
            else:
                return func(step_input)
        else:
            if session_state is not None and self._function_has_session_state_param():
                return await func(step_input, session_state)
            else:
                return await func(step_input)

    def execute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        workflow_session: Optional[WorkflowSession] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
    ) -> StepOutput:
        """Execute the step with StepInput, returning final StepOutput (non-streaming)"""
        log_debug(f"Executing step: {self.name}")

        if step_input.previous_step_outputs:
            step_input.previous_step_content = step_input.get_last_step_content()

        if workflow_session:
            step_input.workflow_session = workflow_session
        session_state_copy = copy(session_state) if session_state is not None else {}

        # Execute with retries
        for attempt in range(self.max_retries + 1):
            try:
                response: Union[RunOutput, TeamRunOutput, StepOutput]
                if self._executor_type == "function":
                    if inspect.iscoroutinefunction(self.active_executor) or inspect.isasyncgenfunction(
                        self.active_executor
                    ):
                        raise ValueError("Cannot use async function with synchronous execution")
                    if inspect.isgeneratorfunction(self.active_executor):
                        content = ""
                        final_response = None
                        try:
                            for chunk in self._call_custom_function(
                                self.active_executor, step_input, session_state_copy
                            ):  # type: ignore
                                if (
                                    hasattr(chunk, "content")
                                    and chunk.content is not None
                                    and isinstance(chunk.content, str)
                                ):
                                    content += chunk.content
                                else:
                                    content += str(chunk)
                                if isinstance(chunk, StepOutput):
                                    final_response = chunk

                        except StopIteration as e:
                            if hasattr(e, "value") and isinstance(e.value, StepOutput):
                                final_response = e.value

                        # Merge session_state changes back
                        if session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        if final_response is not None:
                            response = final_response
                        else:
                            response = StepOutput(content=content)
                    else:
                        # Execute function with signature inspection for session_state support
                        result = self._call_custom_function(self.active_executor, step_input, session_state_copy)  # type: ignore

                        # Merge session_state changes back
                        if session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        # If function returns StepOutput, use it directly
                        if isinstance(result, StepOutput):
                            response = result
                        else:
                            response = StepOutput(content=str(result))
                else:
                    # For agents and teams, prepare message with context
                    message = self._prepare_message(
                        step_input.input,
                        step_input.previous_step_outputs,
                    )

                    # Execute agent or team with media
                    if self._executor_type in ["agent", "team"]:
                        # Switch to appropriate logger based on executor type
                        if self._executor_type == "agent":
                            use_agent_logger()
                        elif self._executor_type == "team":
                            use_team_logger()

                        images = (
                            self._convert_image_artifacts_to_images(step_input.images) if step_input.images else None
                        )
                        videos = (
                            self._convert_video_artifacts_to_videos(step_input.videos) if step_input.videos else None
                        )
                        audios = self._convert_audio_artifacts_to_audio(step_input.audio) if step_input.audio else None

                        kwargs: Dict[str, Any] = {}
                        if isinstance(self.active_executor, Team):
                            kwargs["store_member_responses"] = True

                        num_history_runs = self.num_history_runs if self.num_history_runs else num_history_runs

                        use_history = (
                            self.add_workflow_history
                            if self.add_workflow_history is not None
                            else add_workflow_history_to_steps
                        )

                        final_message = message
                        if use_history and workflow_session:
                            history_messages = workflow_session.get_workflow_history_context(num_runs=num_history_runs)
                            if history_messages:
                                final_message = f"{history_messages}{message}"

                        response = self.active_executor.run(  # type: ignore
                            input=final_message,  # type: ignore
                            images=images,
                            videos=videos,
                            audio=audios,
                            files=step_input.files,
                            session_id=session_id,
                            user_id=user_id,
                            session_state=session_state_copy,  # Send a copy to the executor
                            **kwargs,
                        )

                        if session_state is not None:
                            # Update workflow session state
                            merge_dictionaries(session_state, session_state_copy)  # type: ignore

                        if store_executor_outputs and workflow_run_response is not None:
                            self._store_executor_response(workflow_run_response, response)  # type: ignore

                        # Switch back to workflow logger after execution
                        use_workflow_logger()
                    else:
                        raise ValueError(f"Unsupported executor type: {self._executor_type}")

                # Create StepOutput from response
                step_output = self._process_step_output(response)  # type: ignore

                return step_output

            except Exception as e:
                self.retry_count = attempt + 1
                logger.warning(f"Step {self.name} failed (attempt {attempt + 1}): {e}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        log_debug(f"Step {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty StepOutput for skipped step
                        return StepOutput(content=f"Step {self.name} failed but skipped", success=False, error=str(e))
                    else:
                        raise e

        return StepOutput(content=f"Step {self.name} failed but skipped", success=False)

    def _function_has_session_state_param(self) -> bool:
        """Check if the custom function has a session_state parameter"""
        if self._executor_type != "function":
            return False

        try:
            from inspect import signature

            sig = signature(self.active_executor)  # type: ignore
            return "session_state" in sig.parameters
        except Exception:
            return False

    def _enrich_event_with_context(
        self,
        event: Any,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        step_index: Optional[Union[int, tuple]] = None,
    ) -> Any:
        """Enrich event with step and workflow context information"""
        if workflow_run_response is None:
            return event

        if hasattr(event, "workflow_id"):
            event.workflow_id = workflow_run_response.workflow_id
        if hasattr(event, "workflow_run_id"):
            event.workflow_run_id = workflow_run_response.run_id
        if hasattr(event, "step_id"):
            event.step_id = self.step_id
        if hasattr(event, "step_name") and self.name is not None:
            if getattr(event, "step_name", None) is None:
                event.step_name = self.name
        # Only set step_index if it's not already set (preserve parallel.py's tuples)
        if hasattr(event, "step_index") and step_index is not None:
            if event.step_index is None:
                event.step_index = step_index

        return event

    def execute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        stream_executor_events: bool = True,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        session_state: Optional[Dict[str, Any]] = None,
        step_index: Optional[Union[int, tuple]] = None,
        store_executor_outputs: bool = True,
        parent_step_id: Optional[str] = None,
        workflow_session: Optional["WorkflowSession"] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
    ) -> Iterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Execute the step with event-driven streaming support"""

        if step_input.previous_step_outputs:
            step_input.previous_step_content = step_input.get_last_step_content()

        if workflow_session:
            step_input.workflow_session = workflow_session
        # Create session_state copy once to avoid duplication
        session_state_copy = copy(session_state) if session_state is not None else {}

        # Emit StepStartedEvent
        if stream_intermediate_steps and workflow_run_response:
            yield StepStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                step_id=self.step_id,
                parent_step_id=parent_step_id,
            )

        # Execute with retries and streaming
        for attempt in range(self.max_retries + 1):
            try:
                log_debug(f"Step {self.name} streaming attempt {attempt + 1}/{self.max_retries + 1}")
                final_response = None

                if self._executor_type == "function":
                    log_debug(f"Executing function executor for step: {self.name}")

                    if inspect.iscoroutinefunction(self.active_executor) or inspect.isasyncgenfunction(
                        self.active_executor
                    ):
                        raise ValueError("Cannot use async function with synchronous execution")

                    if inspect.isgeneratorfunction(self.active_executor):
                        log_debug("Function returned iterable, streaming events")
                        content = ""
                        try:
                            iterator = self._call_custom_function(self.active_executor, step_input, session_state_copy)  # type: ignore
                            for event in iterator:  # type: ignore
                                if (
                                    hasattr(event, "content")
                                    and event.content is not None
                                    and isinstance(event.content, str)
                                ):
                                    content += event.content
                                else:
                                    content += str(event)
                                if isinstance(event, StepOutput):
                                    final_response = event
                                    break
                                else:
                                    # Enrich event with workflow context before yielding
                                    enriched_event = self._enrich_event_with_context(
                                        event, workflow_run_response, step_index
                                    )
                                    # Only yield executor events if stream_executor_events is True
                                    if stream_executor_events:
                                        yield enriched_event  # type: ignore[misc]

                            # Merge session_state changes back
                            if session_state is not None:
                                merge_dictionaries(session_state, session_state_copy)

                            if not final_response:
                                final_response = StepOutput(content=content)
                        except StopIteration as e:
                            if hasattr(e, "value") and isinstance(e.value, StepOutput):
                                final_response = e.value

                    else:
                        result = self._call_custom_function(self.active_executor, step_input, session_state_copy)  # type: ignore

                        # Merge session_state changes back
                        if session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        if isinstance(result, StepOutput):
                            final_response = result
                        else:
                            final_response = StepOutput(content=str(result))
                        log_debug("Function returned non-iterable, created StepOutput")
                else:
                    # For agents and teams, prepare message with context
                    message = self._prepare_message(
                        step_input.input,
                        step_input.previous_step_outputs,
                    )

                    if self._executor_type in ["agent", "team"]:
                        # Switch to appropriate logger based on executor type
                        if self._executor_type == "agent":
                            use_agent_logger()
                        elif self._executor_type == "team":
                            use_team_logger()

                        images = (
                            self._convert_image_artifacts_to_images(step_input.images) if step_input.images else None
                        )
                        videos = (
                            self._convert_video_artifacts_to_videos(step_input.videos) if step_input.videos else None
                        )
                        audios = self._convert_audio_artifacts_to_audio(step_input.audio) if step_input.audio else None

                        kwargs: Dict[str, Any] = {}
                        if isinstance(self.active_executor, Team):
                            kwargs["store_member_responses"] = True

                        num_history_runs = self.num_history_runs if self.num_history_runs else num_history_runs

                        use_history = (
                            self.add_workflow_history
                            if self.add_workflow_history is not None
                            else add_workflow_history_to_steps
                        )

                        final_message = message
                        if use_history and workflow_session:
                            history_messages = workflow_session.get_workflow_history_context(num_runs=num_history_runs)
                            if history_messages:
                                final_message = f"{history_messages}{message}"

                        response_stream = self.active_executor.run(  # type: ignore[call-overload, misc]
                            input=final_message,
                            images=images,
                            videos=videos,
                            audio=audios,
                            files=step_input.files,
                            session_id=session_id,
                            user_id=user_id,
                            session_state=session_state_copy,  # Send a copy to the executor
                            stream=True,
                            stream_intermediate_steps=stream_intermediate_steps,
                            yield_run_response=True,
                            **kwargs,
                        )

                        active_executor_run_response = None
                        for event in response_stream:
                            if isinstance(event, RunOutput) or isinstance(event, TeamRunOutput):
                                active_executor_run_response = event
                                break
                            enriched_event = self._enrich_event_with_context(event, workflow_run_response, step_index)
                            # Only yield executor events if stream_executor_events is True
                            if stream_executor_events:
                                yield enriched_event  # type: ignore[misc]

                        if session_state is not None:
                            # Update workflow session state
                            merge_dictionaries(session_state, session_state_copy)  # type: ignore

                        if store_executor_outputs and workflow_run_response is not None:
                            self._store_executor_response(workflow_run_response, active_executor_run_response)  # type: ignore

                        final_response = active_executor_run_response  # type: ignore

                    else:
                        raise ValueError(f"Unsupported executor type: {self._executor_type}")

                # If we didn't get a final response, create one
                if final_response is None:
                    final_response = StepOutput(content="")
                    log_debug("Created empty StepOutput as fallback")

                # Switch back to workflow logger after execution
                use_workflow_logger()

                # Yield the step output
                final_response = self._process_step_output(final_response)
                yield final_response

                # Emit StepCompletedEvent
                if stream_intermediate_steps and workflow_run_response:
                    yield StepCompletedEvent(
                        run_id=workflow_run_response.run_id or "",
                        workflow_name=workflow_run_response.workflow_name or "",
                        workflow_id=workflow_run_response.workflow_id or "",
                        session_id=workflow_run_response.session_id or "",
                        step_name=self.name,
                        step_index=step_index,
                        content=final_response.content,
                        step_response=final_response,
                        parent_step_id=parent_step_id,
                    )

                return
            except Exception as e:
                self.retry_count = attempt + 1
                logger.warning(f"Step {self.name} failed (attempt {attempt + 1}): {e}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        log_debug(f"Step {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty StepOutput for skipped step
                        step_output = StepOutput(
                            content=f"Step {self.name} failed but skipped", success=False, error=str(e)
                        )
                        yield step_output
                        return
                    else:
                        raise e

        return

    async def aexecute(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        session_state: Optional[Dict[str, Any]] = None,
        store_executor_outputs: bool = True,
        workflow_session: Optional["WorkflowSession"] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
    ) -> StepOutput:
        """Execute the step with StepInput, returning final StepOutput (non-streaming)"""
        logger.info(f"Executing async step (non-streaming): {self.name}")
        log_debug(f"Executor type: {self._executor_type}")

        if step_input.previous_step_outputs:
            step_input.previous_step_content = step_input.get_last_step_content()

        if workflow_session:
            step_input.workflow_session = workflow_session
        # Create session_state copy once to avoid duplication
        session_state_copy = copy(session_state) if session_state is not None else {}

        # Execute with retries
        for attempt in range(self.max_retries + 1):
            try:
                if self._executor_type == "function":
                    import inspect

                    if inspect.isgeneratorfunction(self.active_executor) or inspect.isasyncgenfunction(
                        self.active_executor
                    ):
                        content = ""
                        final_response = None
                        try:
                            if inspect.isgeneratorfunction(self.active_executor):
                                iterator = self._call_custom_function(
                                    self.active_executor, step_input, session_state_copy
                                )  # type: ignore
                                for chunk in iterator:  # type: ignore
                                    if (
                                        hasattr(chunk, "content")
                                        and chunk.content is not None
                                        and isinstance(chunk.content, str)
                                    ):
                                        content += chunk.content
                                    else:
                                        content += str(chunk)
                                    if isinstance(chunk, StepOutput):
                                        final_response = chunk
                            else:
                                if inspect.isasyncgenfunction(self.active_executor):
                                    iterator = await self._acall_custom_function(
                                        self.active_executor, step_input, session_state_copy
                                    )  # type: ignore
                                    async for chunk in iterator:  # type: ignore
                                        if (
                                            hasattr(chunk, "content")
                                            and chunk.content is not None
                                            and isinstance(chunk.content, str)
                                        ):
                                            content += chunk.content
                                        else:
                                            content += str(chunk)
                                        if isinstance(chunk, StepOutput):
                                            final_response = chunk

                        except StopIteration as e:
                            if hasattr(e, "value") and isinstance(e.value, StepOutput):
                                final_response = e.value

                        # Merge session_state changes back
                        if session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        if final_response is not None:
                            response = final_response
                        else:
                            response = StepOutput(content=content)
                    else:
                        if inspect.iscoroutinefunction(self.active_executor):
                            result = await self._acall_custom_function(
                                self.active_executor, step_input, session_state_copy
                            )  # type: ignore
                        else:
                            result = self._call_custom_function(self.active_executor, step_input, session_state_copy)  # type: ignore

                        # Merge session_state changes back
                        if session_state is not None:
                            merge_dictionaries(session_state, session_state_copy)

                        # If function returns StepOutput, use it directly
                        if isinstance(result, StepOutput):
                            response = result
                        else:
                            response = StepOutput(content=str(result))

                else:
                    # For agents and teams, prepare message with context
                    message = self._prepare_message(
                        step_input.input,
                        step_input.previous_step_outputs,
                    )

                    # Execute agent or team with media
                    if self._executor_type in ["agent", "team"]:
                        # Switch to appropriate logger based on executor type
                        if self._executor_type == "agent":
                            use_agent_logger()
                        elif self._executor_type == "team":
                            use_team_logger()

                        images = (
                            self._convert_image_artifacts_to_images(step_input.images) if step_input.images else None
                        )
                        videos = (
                            self._convert_video_artifacts_to_videos(step_input.videos) if step_input.videos else None
                        )
                        audios = self._convert_audio_artifacts_to_audio(step_input.audio) if step_input.audio else None

                        kwargs: Dict[str, Any] = {}
                        if isinstance(self.active_executor, Team):
                            kwargs["store_member_responses"] = True

                        num_history_runs = self.num_history_runs if self.num_history_runs else num_history_runs

                        use_history = (
                            self.add_workflow_history
                            if self.add_workflow_history is not None
                            else add_workflow_history_to_steps
                        )

                        final_message = message
                        if use_history and workflow_session:
                            history_messages = workflow_session.get_workflow_history_context(num_runs=num_history_runs)
                            if history_messages:
                                final_message = f"{history_messages}{message}"

                        response = await self.active_executor.arun(  # type: ignore
                            input=final_message,  # type: ignore
                            images=images,
                            videos=videos,
                            audio=audios,
                            files=step_input.files,
                            session_id=session_id,
                            user_id=user_id,
                            session_state=session_state_copy,
                            **kwargs,
                        )

                        if session_state is not None:
                            # Update workflow session state
                            merge_dictionaries(session_state, session_state_copy)  # type: ignore

                        if store_executor_outputs and workflow_run_response is not None:
                            self._store_executor_response(workflow_run_response, response)  # type: ignore

                        # Switch back to workflow logger after execution
                        use_workflow_logger()
                    else:
                        raise ValueError(f"Unsupported executor type: {self._executor_type}")

                # Create StepOutput from response
                step_output = self._process_step_output(response)  # type: ignore

                return step_output

            except Exception as e:
                self.retry_count = attempt + 1
                logger.warning(f"Step {self.name} failed (attempt {attempt + 1}): {e}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        log_debug(f"Step {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty StepOutput for skipped step
                        return StepOutput(content=f"Step {self.name} failed but skipped", success=False, error=str(e))
                    else:
                        raise e

        return StepOutput(content=f"Step {self.name} failed but skipped", success=False)

    async def aexecute_stream(
        self,
        step_input: StepInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
        stream_executor_events: bool = True,
        workflow_run_response: Optional["WorkflowRunOutput"] = None,
        session_state: Optional[Dict[str, Any]] = None,
        step_index: Optional[Union[int, tuple]] = None,
        store_executor_outputs: bool = True,
        parent_step_id: Optional[str] = None,
        workflow_session: Optional["WorkflowSession"] = None,
        add_workflow_history_to_steps: Optional[bool] = False,
        num_history_runs: int = 3,
    ) -> AsyncIterator[Union[WorkflowRunOutputEvent, StepOutput]]:
        """Execute the step with event-driven streaming support"""

        if step_input.previous_step_outputs:
            step_input.previous_step_content = step_input.get_last_step_content()

        if workflow_session:
            step_input.workflow_session = workflow_session

        # Create session_state copy once to avoid duplication
        session_state_copy = copy(session_state) if session_state is not None else {}

        if stream_intermediate_steps and workflow_run_response:
            # Emit StepStartedEvent
            yield StepStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name or "",
                workflow_id=workflow_run_response.workflow_id or "",
                session_id=workflow_run_response.session_id or "",
                step_name=self.name,
                step_index=step_index,
                step_id=self.step_id,
                parent_step_id=parent_step_id,
            )

        # Execute with retries and streaming
        for attempt in range(self.max_retries + 1):
            try:
                log_debug(f"Async step {self.name} streaming attempt {attempt + 1}/{self.max_retries + 1}")
                final_response = None

                if self._executor_type == "function":
                    log_debug(f"Executing async function executor for step: {self.name}")
                    import inspect

                    # Check if the function is an async generator
                    if inspect.isasyncgenfunction(self.active_executor):
                        content = ""
                        # It's an async generator - iterate over it
                        iterator = await self._acall_custom_function(
                            self.active_executor, step_input, session_state_copy
                        )  # type: ignore
                        async for event in iterator:  # type: ignore
                            if (
                                hasattr(event, "content")
                                and event.content is not None
                                and isinstance(event.content, str)
                            ):
                                content += event.content
                            else:
                                content += str(event)
                            if isinstance(event, StepOutput):
                                final_response = event
                                break
                            else:
                                # Enrich event with workflow context before yielding
                                enriched_event = self._enrich_event_with_context(
                                    event, workflow_run_response, step_index
                                )
                                # Only yield executor events if stream_executor_events is True
                                if stream_executor_events:
                                    yield enriched_event  # type: ignore[misc]
                        if not final_response:
                            final_response = StepOutput(content=content)
                    elif inspect.iscoroutinefunction(self.active_executor):
                        # It's a regular async function - await it
                        result = await self._acall_custom_function(self.active_executor, step_input, session_state_copy)  # type: ignore
                        if isinstance(result, StepOutput):
                            final_response = result
                        else:
                            final_response = StepOutput(content=str(result))
                    elif inspect.isgeneratorfunction(self.active_executor):
                        content = ""
                        # It's a regular generator function - iterate over it
                        iterator = self._call_custom_function(self.active_executor, step_input, session_state_copy)  # type: ignore
                        for event in iterator:  # type: ignore
                            if (
                                hasattr(event, "content")
                                and event.content is not None
                                and isinstance(event.content, str)
                            ):
                                content += event.content
                            else:
                                content += str(event)
                            if isinstance(event, StepOutput):
                                final_response = event
                                break
                            else:
                                # Enrich event with workflow context before yielding
                                enriched_event = self._enrich_event_with_context(
                                    event, workflow_run_response, step_index
                                )
                                # Only yield executor events if stream_executor_events is True
                                if stream_executor_events:
                                    yield enriched_event  # type: ignore[misc]
                        if not final_response:
                            final_response = StepOutput(content=content)
                    else:
                        # It's a regular function - call it directly
                        result = self._call_custom_function(self.active_executor, step_input, session_state_copy)  # type: ignore
                        if isinstance(result, StepOutput):
                            final_response = result
                        else:
                            final_response = StepOutput(content=str(result))

                    # Merge session_state changes back
                    if session_state is not None:
                        merge_dictionaries(session_state, session_state_copy)
                else:
                    # For agents and teams, prepare message with context
                    message = self._prepare_message(
                        step_input.input,
                        step_input.previous_step_outputs,
                    )

                    if self._executor_type in ["agent", "team"]:
                        # Switch to appropriate logger based on executor type
                        if self._executor_type == "agent":
                            use_agent_logger()
                        elif self._executor_type == "team":
                            use_team_logger()

                        images = (
                            self._convert_image_artifacts_to_images(step_input.images) if step_input.images else None
                        )
                        videos = (
                            self._convert_video_artifacts_to_videos(step_input.videos) if step_input.videos else None
                        )
                        audios = self._convert_audio_artifacts_to_audio(step_input.audio) if step_input.audio else None

                        kwargs: Dict[str, Any] = {}
                        if isinstance(self.active_executor, Team):
                            kwargs["store_member_responses"] = True

                        num_history_runs = self.num_history_runs if self.num_history_runs else num_history_runs

                        use_history = (
                            self.add_workflow_history
                            if self.add_workflow_history is not None
                            else add_workflow_history_to_steps
                        )

                        final_message = message
                        if use_history and workflow_session:
                            history_messages = workflow_session.get_workflow_history_context(num_runs=num_history_runs)
                            if history_messages:
                                final_message = f"{history_messages}{message}"

                        response_stream = self.active_executor.arun(  # type: ignore
                            input=final_message,
                            images=images,
                            videos=videos,
                            audio=audios,
                            files=step_input.files,
                            session_id=session_id,
                            user_id=user_id,
                            session_state=session_state_copy,
                            stream=True,
                            stream_intermediate_steps=stream_intermediate_steps,
                            yield_run_response=True,
                            **kwargs,
                        )

                        active_executor_run_response = None
                        async for event in response_stream:
                            if isinstance(event, RunOutput) or isinstance(event, TeamRunOutput):
                                active_executor_run_response = event
                                break
                            enriched_event = self._enrich_event_with_context(event, workflow_run_response, step_index)
                            # Only yield executor events if stream_executor_events is True
                            if stream_executor_events:
                                yield enriched_event  # type: ignore[misc]

                        if session_state is not None:
                            # Update workflow session state
                            merge_dictionaries(session_state, session_state_copy)  # type: ignore

                        if store_executor_outputs and workflow_run_response is not None:
                            self._store_executor_response(workflow_run_response, active_executor_run_response)  # type: ignore

                        final_response = active_executor_run_response  # type: ignore
                    else:
                        raise ValueError(f"Unsupported executor type: {self._executor_type}")

                # If we didn't get a final response, create one
                if final_response is None:
                    final_response = StepOutput(content="")

                # Switch back to workflow logger after execution
                use_workflow_logger()

                # Yield the final response
                final_response = self._process_step_output(final_response)
                yield final_response

                if stream_intermediate_steps and workflow_run_response:
                    # Emit StepCompletedEvent
                    yield StepCompletedEvent(
                        run_id=workflow_run_response.run_id or "",
                        workflow_name=workflow_run_response.workflow_name or "",
                        workflow_id=workflow_run_response.workflow_id or "",
                        session_id=workflow_run_response.session_id or "",
                        step_name=self.name,
                        step_index=step_index,
                        step_id=self.step_id,
                        content=final_response.content,
                        step_response=final_response,
                        parent_step_id=parent_step_id,
                    )
                return

            except Exception as e:
                self.retry_count = attempt + 1
                logger.warning(f"Step {self.name} failed (attempt {attempt + 1}): {e}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        log_debug(f"Step {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty StepOutput for skipped step
                        step_output = StepOutput(
                            content=f"Step {self.name} failed but skipped", success=False, error=str(e)
                        )
                        yield step_output
                    else:
                        raise e

        return

    def _store_executor_response(
        self, workflow_run_response: "WorkflowRunOutput", executor_run_response: Union[RunOutput, TeamRunOutput]
    ) -> None:
        """Store agent/team responses in step_executor_runs if enabled"""
        if self._executor_type in ["agent", "team"]:
            # propogate the workflow run id as parent run id to the executor response
            executor_run_response.parent_run_id = workflow_run_response.run_id
            executor_run_response.workflow_step_id = self.step_id

            # Scrub the executor response based on the executor's storage flags before storing
            if (
                not self.active_executor.store_media
                or not self.active_executor.store_tool_messages
                or not self.active_executor.store_history_messages
            ):  # type: ignore
                self.active_executor._scrub_run_output_for_storage(executor_run_response)  # type: ignore

            # Get the raw response from the step's active executor
            raw_response = executor_run_response
            if raw_response and isinstance(raw_response, (RunOutput, TeamRunOutput)):
                if workflow_run_response.step_executor_runs is None:
                    workflow_run_response.step_executor_runs = []

                raw_response.workflow_step_id = self.step_id
                # Add the primary executor run
                workflow_run_response.step_executor_runs.append(raw_response)

                # Add direct member agent runs (in case of a team we force store_member_responses=True here)
                if isinstance(raw_response, TeamRunOutput) and getattr(
                    self.active_executor, "store_member_responses", False
                ):
                    for mr in raw_response.member_responses or []:
                        if isinstance(mr, RunOutput):
                            workflow_run_response.step_executor_runs.append(mr)

    def _get_deepest_content_from_step_output(self, step_output: "StepOutput") -> Optional[str]:
        """
        Extract the deepest content from a step output, handling nested structures like Steps, Router, Loop, etc.

        For container steps (Steps, Router, Loop, etc.), this will recursively find the content from the
        last actual step rather than using the generic container message.
        """
        # If this step has nested steps (like Steps, Condition, Router, Loop, etc.)
        if hasattr(step_output, "steps") and step_output.steps and len(step_output.steps) > 0:
            # Recursively get content from the last nested step
            return self._get_deepest_content_from_step_output(step_output.steps[-1])

        # For regular steps, return their content
        return step_output.content  # type: ignore

    def _prepare_message(
        self,
        message: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]],
        previous_step_outputs: Optional[Dict[str, StepOutput]] = None,
    ) -> Optional[Union[str, List[Any], Dict[str, Any], BaseModel]]:
        """Prepare the primary input by combining message and previous step outputs"""

        if previous_step_outputs and self._executor_type in ["agent", "team"]:
            last_output = list(previous_step_outputs.values())[-1] if previous_step_outputs else None
            if last_output:
                deepest_content = self._get_deepest_content_from_step_output(last_output)
                if deepest_content:
                    return deepest_content

        # If no previous step outputs, return the original message unchanged
        return message

    def _process_step_output(self, response: Union[RunOutput, TeamRunOutput, StepOutput]) -> StepOutput:
        """Create StepOutput from execution response"""
        if isinstance(response, StepOutput):
            response.step_name = self.name or "unnamed_step"
            response.step_id = self.step_id
            response.step_type = StepType.STEP
            response.executor_type = self._executor_type
            response.executor_name = self.executor_name
            return response

        # Extract media from response
        images = getattr(response, "images", None)
        videos = getattr(response, "videos", None)
        audio = getattr(response, "audio", None)

        # Extract metrics from response
        metrics = self._extract_metrics_from_response(response)

        return StepOutput(
            step_name=self.name or "unnamed_step",
            step_id=self.step_id,
            step_type=StepType.STEP,
            executor_type=self._executor_type,
            executor_name=self.executor_name,
            content=response.content,
            step_run_id=getattr(response, "run_id", None),
            images=images,
            videos=videos,
            audio=audio,
            metrics=metrics,
        )

    def _convert_function_result_to_response(self, result: Any) -> RunOutput:
        """Convert function execution result to RunOutput"""
        if isinstance(result, RunOutput):
            return result
        elif isinstance(result, str):
            return RunOutput(content=result)
        elif isinstance(result, dict):
            # If it's a dict, try to extract content
            content = result.get("content", str(result))
            return RunOutput(content=content)
        else:
            # Convert any other type to string
            return RunOutput(content=str(result))

    def _convert_audio_artifacts_to_audio(self, audio_artifacts: List[Audio]) -> List[Audio]:
        """Convert AudioArtifact objects to Audio objects"""
        audios = []
        for audio_artifact in audio_artifacts:
            if audio_artifact.url:
                audios.append(Audio(url=audio_artifact.url))
            elif audio_artifact.content:
                audios.append(Audio(content=audio_artifact.content))
            else:
                logger.warning(f"Skipping AudioArtifact with no URL or content: {audio_artifact}")
                continue
        return audios

    def _convert_image_artifacts_to_images(self, image_artifacts: List[Image]) -> List[Image]:
        """
        Convert ImageArtifact objects to Image objects with proper content handling.

        Args:
            image_artifacts: List of ImageArtifact objects to convert

        Returns:
            List of Image objects ready for agent processing
        """
        import base64

        images = []
        for i, img_artifact in enumerate(image_artifacts):
            # Create Image object with proper data from ImageArtifact
            if img_artifact.url:
                images.append(Image(url=img_artifact.url))

            elif img_artifact.content:
                # Handle the case where content is base64-encoded bytes from OpenAI tools
                try:
                    # Try to decode as base64 first (for images from OpenAI tools)
                    if isinstance(img_artifact.content, bytes):
                        # Decode bytes to string, then decode base64 to get actual image bytes
                        base64_str: str = img_artifact.content.decode("utf-8")
                        actual_image_bytes = base64.b64decode(base64_str)
                    else:
                        # If it's already actual image bytes
                        actual_image_bytes = img_artifact.content

                    # Create Image object with proper format
                    image_kwargs = {"content": actual_image_bytes}
                    if img_artifact.mime_type:
                        # Convert mime_type to format (e.g., "image/png" -> "png")
                        if "/" in img_artifact.mime_type:
                            format_from_mime = img_artifact.mime_type.split("/")[-1]
                            image_kwargs["format"] = format_from_mime  # type: ignore[assignment]

                    images.append(Image(**image_kwargs))

                except Exception as e:
                    logger.error(f"Failed to process image content: {e}")
                    # Skip this image if we can't process it
                    continue

            else:
                # Skip images that have neither URL nor content
                logger.warning(f"Skipping ImageArtifact {i} with no URL or content: {img_artifact}")
                continue

        return images

    def _convert_video_artifacts_to_videos(self, video_artifacts: List[Video]) -> List[Video]:
        """
        Convert VideoArtifact objects to Video objects with proper content handling.

        Args:
            video_artifacts: List of VideoArtifact objects to convert

        Returns:
            List of Video objects ready for agent processing
        """
        videos = []
        for i, video_artifact in enumerate(video_artifacts):
            # Create Video object with proper data from VideoArtifact
            if video_artifact.url:
                videos.append(Video(url=video_artifact.url))

            elif video_artifact.content:
                videos.append(Video(content=video_artifact.content))

            else:
                # Skip videos that have neither URL nor content
                logger.warning(f"Skipping VideoArtifact {i} with no URL or content: {video_artifact}")
                continue

        return videos
