from __future__ import annotations

import asyncio
import time
import warnings
from collections import deque
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
    cast,
    overload,
)
from uuid import uuid4

from agno.agent.trait.base import AgentTraitBase
from agno.exceptions import InputCheckError, OutputCheckError, RunCancelledException
from agno.models.base import Model
from agno.models.metrics import Metrics
from agno.run import RunContext, RunStatus
from agno.run.agent import (
    RunInput,
    RunOutput,
    RunOutputEvent,
)
from agno.run.cancel import (
    acleanup_run,
    araise_if_cancelled,
    aregister_run,
    cleanup_run,
    raise_if_cancelled,
    register_run,
)
from agno.utils.agent import (
    await_for_open_threads,
    await_for_thread_tasks_stream,
    store_media_util,
    validate_input,
    validate_media_object_id,
    wait_for_open_threads,
    wait_for_thread_tasks_stream,
)
from agno.utils.events import (
    add_error_event,
    create_run_cancelled_event,
    create_run_completed_event,
    create_run_content_completed_event,
    create_run_continued_event,
    create_run_error_event,
    create_run_started_event,
    create_session_summary_completed_event,
    create_session_summary_started_event,
    handle_event,
)
from agno.utils.hooks import normalize_post_hooks, normalize_pre_hooks
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.merge_dict import merge_dictionaries

if TYPE_CHECKING:
    from pydantic import BaseModel

    from agno.filters import FilterExpr
    from agno.media import Audio, File, Image, Video
    from agno.models.message import Message
    from agno.models.response import ModelResponse, ToolExecution
    from agno.run.messages import RunMessages
    from agno.run.requirement import RunRequirement
    from agno.session import AgentSession
    from agno.tools.function import Function


class AgentRunTrait(AgentTraitBase):
    def _initialize_session(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[str, Optional[str]]:
        """Initialize the session for the agent."""

        if session_id is None:
            if self.session_id:
                session_id = self.session_id
            else:
                session_id = str(uuid4())
                # We make the session_id sticky to the agent instance if no session_id is provided
                self.session_id = session_id

        log_debug(f"Session ID: {session_id}", center=True)

        # Use the default user_id when necessary
        if user_id is None or user_id == "":
            user_id = self.user_id

        return session_id, user_id

    def _run(
        self,
        run_response: RunOutput,
        run_context: RunContext,
        session: AgentSession,
        user_id: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> RunOutput:
        """Run the Agent and return the RunOutput.

        Steps:
        1. Execute pre-hooks
        2. Determine tools for model
        3. Prepare run messages
        4. Start memory creation in background thread
        5. Reason about the task if reasoning is enabled
        6. Generate a response from the Model (includes running function calls)
        7. Update the RunOutput with the model response
        8. Store media if enabled
        9. Convert the response to the structured format if needed
        10. Execute post-hooks
        11. Wait for background memory creation and cultural knowledge creation
        12. Create session summary
        13. Cleanup and store the run response and session
        """
        memory_future = None
        learning_future = None
        cultural_knowledge_future = None

        try:
            # Register run for cancellation tracking
            register_run(run_response.run_id)  # type: ignore

            # Set up retry logic
            num_attempts = self.retries + 1
            for attempt in range(num_attempts):
                if num_attempts > 1:
                    log_debug(f"Retrying Agent run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")
                try:
                    # 1. Execute pre-hooks
                    run_input = cast(RunInput, run_response.input)
                    self.model = cast(Model, self.model)
                    if self.pre_hooks is not None:
                        # Can modify the run input
                        pre_hook_iterator = self._execute_pre_hooks(
                            hooks=self.pre_hooks,  # type: ignore
                            run_response=run_response,
                            run_input=run_input,
                            run_context=run_context,
                            session=session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            background_tasks=background_tasks,
                            **kwargs,
                        )
                        # Consume the generator without yielding
                        deque(pre_hook_iterator, maxlen=0)

                    # 2. Determine tools for model
                    processed_tools = self.get_tools(
                        run_response=run_response,
                        run_context=run_context,
                        session=session,
                        user_id=user_id,
                    )
                    _tools = self._determine_tools_for_model(
                        model=self.model,
                        processed_tools=processed_tools,
                        run_response=run_response,
                        session=session,
                        run_context=run_context,
                    )

                    # 3. Prepare run messages
                    run_messages: RunMessages = self._get_run_messages(
                        run_response=run_response,
                        run_context=run_context,
                        input=run_input.input_content,
                        session=session,
                        user_id=user_id,
                        audio=run_input.audios,
                        images=run_input.images,
                        videos=run_input.videos,
                        files=run_input.files,
                        add_history_to_context=add_history_to_context,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                        tools=_tools,
                        **kwargs,
                    )
                    if len(run_messages.messages) == 0:
                        log_error("No messages to be sent to the model.")

                    log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

                    # 4. Start memory creation in background thread
                    memory_future = self._start_memory_future(
                        run_messages=run_messages,
                        user_id=user_id,
                        existing_future=memory_future,
                    )

                    # Start learning extraction as a background task (runs concurrently with the main execution)
                    learning_future = self._start_learning_future(
                        run_messages=run_messages,
                        session=session,
                        user_id=user_id,
                        existing_future=learning_future,
                    )

                    # Start cultural knowledge creation in background thread
                    cultural_knowledge_future = self._start_cultural_knowledge_future(
                        run_messages=run_messages,
                        existing_future=cultural_knowledge_future,
                    )

                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 5. Reason about the task
                    self._handle_reasoning(
                        run_response=run_response, run_messages=run_messages, run_context=run_context
                    )

                    # Check for cancellation before model call
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 6. Generate a response from the Model (includes running function calls)
                    self.model = cast(Model, self.model)

                    model_response: ModelResponse = self.model.response(
                        messages=run_messages.messages,
                        tools=_tools,
                        tool_choice=self.tool_choice,
                        tool_call_limit=self.tool_call_limit,
                        response_format=response_format,
                        run_response=run_response,
                        send_media_to_model=self.send_media_to_model,
                        compression_manager=self.compression_manager if self.compress_tool_results else None,
                    )

                    # Check for cancellation after model call
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # If an output model is provided, generate output using the output model
                    self._generate_response_with_output_model(model_response, run_messages)

                    # If a parser model is provided, structure the response separately
                    self._parse_response_with_parser_model(model_response, run_messages, run_context=run_context)

                    # 7. Update the RunOutput with the model response
                    self._update_run_response(
                        model_response=model_response, run_response=run_response, run_messages=run_messages
                    )

                    # We should break out of the run function
                    if any(tool_call.is_paused for tool_call in run_response.tools or []):
                        wait_for_open_threads(
                            memory_future=memory_future,  # type: ignore
                            cultural_knowledge_future=cultural_knowledge_future,  # type: ignore
                            learning_future=learning_future,  # type: ignore
                        )

                        return self._handle_agent_run_paused(
                            run_response=run_response, session=session, user_id=user_id
                        )

                    # 8. Store media if enabled
                    if self.store_media:
                        store_media_util(run_response, model_response)

                    # 9. Convert the response to the structured format if needed
                    self._convert_response_to_structured_format(run_response, run_context=run_context)

                    # 10. Execute post-hooks after output is generated but before response is returned
                    if self.post_hooks is not None:
                        post_hook_iterator = self._execute_post_hooks(
                            hooks=self.post_hooks,  # type: ignore
                            run_output=run_response,
                            run_context=run_context,
                            session=session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            background_tasks=background_tasks,
                            **kwargs,
                        )
                        deque(post_hook_iterator, maxlen=0)

                    # Check for cancellation
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 11. Wait for background memory creation and cultural knowledge creation
                    wait_for_open_threads(
                        memory_future=memory_future,  # type: ignore
                        cultural_knowledge_future=cultural_knowledge_future,  # type: ignore
                        learning_future=learning_future,  # type: ignore
                    )

                    # 12. Create session summary
                    if self.session_summary_manager is not None and self.enable_session_summaries:
                        # Upsert the RunOutput to Agent Session before creating the session summary
                        session.upsert_run(run=run_response)
                        try:
                            self.session_summary_manager.create_session_summary(session=session)
                        except Exception as e:
                            log_warning(f"Error in session summary creation: {str(e)}")

                    run_response.status = RunStatus.completed

                    # 13. Cleanup and store the run response and session
                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                    # Log Agent Telemetry
                    self._log_agent_telemetry(session_id=session.session_id, run_id=run_response.run_id)

                    log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                    return run_response
                except RunCancelledException as e:
                    log_info(f"Run {run_response.run_id} was cancelled")
                    run_response.content = str(e)
                    run_response.status = RunStatus.cancelled

                    # Cleanup and store the run response and session
                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                    return run_response
                except (InputCheckError, OutputCheckError) as e:
                    # Handle exceptions during streaming
                    run_response.status = RunStatus.error
                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                    return run_response
                except KeyboardInterrupt:
                    run_response = cast(RunOutput, run_response)
                    run_response.status = RunStatus.cancelled
                    run_response.content = "Operation cancelled by user"
                    return run_response

                except Exception as e:
                    if attempt < num_attempts - 1:
                        # Calculate delay with exponential backoff if enabled
                        if self.exponential_backoff:
                            delay = self.delay_between_retries * (2**attempt)
                        else:
                            delay = self.delay_between_retries

                        log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                        time.sleep(delay)
                        continue

                    run_response.status = RunStatus.error

                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Error in Agent run: {str(e)}")

                    # Cleanup and store the run response and session
                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                    return run_response
        finally:
            # Cancel background futures on error (wait_for_open_threads handles waiting on success)
            if memory_future is not None and not memory_future.done():
                memory_future.cancel()
            if cultural_knowledge_future is not None and not cultural_knowledge_future.done():
                cultural_knowledge_future.cancel()
            if learning_future is not None and not learning_future.done():
                learning_future.cancel()

            # Always disconnect connectable tools
            self._disconnect_connectable_tools()
            # Always clean up the run tracking
            cleanup_run(run_response.run_id)  # type: ignore

        return run_response

    def _run_stream(
        self,
        run_response: RunOutput,
        run_context: RunContext,
        session: AgentSession,
        user_id: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        stream_events: bool = False,
        yield_run_output: Optional[bool] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> Iterator[Union[RunOutputEvent, RunOutput]]:
        """Run the Agent and yield the RunOutput.

        Steps:
        1. Execute pre-hooks
        2. Determine tools for model
        3. Prepare run messages
        4. Start memory creation in background thread
        5. Reason about the task if reasoning is enabled
        6. Process model response
        7. Parse response with parser model if provided
        8. Wait for background memory creation and cultural knowledge creation
        9. Create session summary
        10. Cleanup and store the run response and session
        """
        memory_future = None
        learning_future = None
        cultural_knowledge_future = None

        try:
            # Register run for cancellation tracking
            register_run(run_response.run_id)  # type: ignore

            # Set up retry logic
            num_attempts = self.retries + 1
            for attempt in range(num_attempts):
                if num_attempts > 1:
                    log_debug(f"Retrying Agent run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")
                try:
                    # 1. Execute pre-hooks
                    run_input = cast(RunInput, run_response.input)
                    self.model = cast(Model, self.model)
                    if self.pre_hooks is not None:
                        # Can modify the run input
                        pre_hook_iterator = self._execute_pre_hooks(
                            hooks=self.pre_hooks,  # type: ignore
                            run_response=run_response,
                            run_input=run_input,
                            run_context=run_context,
                            session=session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            stream_events=stream_events,
                            background_tasks=background_tasks,
                            **kwargs,
                        )
                        for event in pre_hook_iterator:
                            yield event

                    # 2. Determine tools for model
                    processed_tools = self.get_tools(
                        run_response=run_response,
                        run_context=run_context,
                        session=session,
                        user_id=user_id,
                    )
                    _tools = self._determine_tools_for_model(
                        model=self.model,
                        processed_tools=processed_tools,
                        run_response=run_response,
                        session=session,
                        run_context=run_context,
                    )

                    # 3. Prepare run messages
                    run_messages: RunMessages = self._get_run_messages(
                        run_response=run_response,
                        input=run_input.input_content,
                        session=session,
                        run_context=run_context,
                        user_id=user_id,
                        audio=run_input.audios,
                        images=run_input.images,
                        videos=run_input.videos,
                        files=run_input.files,
                        add_history_to_context=add_history_to_context,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                        tools=_tools,
                        **kwargs,
                    )
                    if len(run_messages.messages) == 0:
                        log_error("No messages to be sent to the model.")

                    log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

                    # 4. Start memory creation in background thread
                    memory_future = self._start_memory_future(
                        run_messages=run_messages,
                        user_id=user_id,
                        existing_future=memory_future,
                    )

                    # Start learning extraction as a background task (runs concurrently with the main execution)
                    learning_future = self._start_learning_future(
                        run_messages=run_messages,
                        session=session,
                        user_id=user_id,
                        existing_future=learning_future,
                    )

                    # Start cultural knowledge creation in background thread
                    cultural_knowledge_future = self._start_cultural_knowledge_future(
                        run_messages=run_messages,
                        existing_future=cultural_knowledge_future,
                    )

                    # Start the Run by yielding a RunStarted event
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_run_started_event(run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )

                    # 5. Reason about the task if reasoning is enabled
                    yield from self._handle_reasoning_stream(
                        run_response=run_response,
                        run_messages=run_messages,
                        run_context=run_context,
                        stream_events=stream_events,
                    )

                    # Check for cancellation before model processing
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 6. Process model response
                    if self.output_model is None:
                        for event in self._handle_model_response_stream(
                            session=session,
                            run_response=run_response,
                            run_messages=run_messages,
                            tools=_tools,
                            response_format=response_format,
                            stream_events=stream_events,
                            session_state=run_context.session_state,
                            run_context=run_context,
                        ):
                            raise_if_cancelled(run_response.run_id)  # type: ignore
                            yield event
                    else:
                        from agno.run.agent import (
                            IntermediateRunContentEvent,
                            RunContentEvent,
                        )  # type: ignore

                        for event in self._handle_model_response_stream(
                            session=session,
                            run_response=run_response,
                            run_messages=run_messages,
                            tools=_tools,
                            response_format=response_format,
                            stream_events=stream_events,
                            session_state=run_context.session_state,
                            run_context=run_context,
                        ):
                            raise_if_cancelled(run_response.run_id)  # type: ignore
                            if isinstance(event, RunContentEvent):
                                if stream_events:
                                    yield IntermediateRunContentEvent(
                                        content=event.content,
                                        content_type=event.content_type,
                                    )
                            else:
                                yield event

                        # If an output model is provided, generate output using the output model
                        for event in self._generate_response_with_output_model_stream(
                            session=session,
                            run_response=run_response,
                            run_messages=run_messages,
                            stream_events=stream_events,
                        ):
                            raise_if_cancelled(run_response.run_id)  # type: ignore
                            yield event  # type: ignore

                    # Check for cancellation after model processing
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 7. Parse response with parser model if provided
                    yield from self._parse_response_with_parser_model_stream(  # type: ignore
                        session=session, run_response=run_response, stream_events=stream_events, run_context=run_context
                    )

                    # We should break out of the run function
                    if any(tool_call.is_paused for tool_call in run_response.tools or []):
                        yield from wait_for_thread_tasks_stream(
                            memory_future=memory_future,  # type: ignore
                            cultural_knowledge_future=cultural_knowledge_future,  # type: ignore
                            learning_future=learning_future,  # type: ignore
                            stream_events=stream_events,
                            run_response=run_response,
                            events_to_skip=self.events_to_skip,
                            store_events=self.store_events,
                            get_memories_callback=lambda: self.get_user_memories(user_id=user_id),
                        )

                        # Handle the paused run
                        yield from self._handle_agent_run_paused_stream(
                            run_response=run_response, session=session, user_id=user_id
                        )
                        return

                    # Yield RunContentCompletedEvent
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_run_content_completed_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )

                    # Execute post-hooks after output is generated but before response is returned
                    if self.post_hooks is not None:
                        yield from self._execute_post_hooks(
                            hooks=self.post_hooks,  # type: ignore
                            run_output=run_response,
                            run_context=run_context,
                            session=session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            stream_events=stream_events,
                            background_tasks=background_tasks,
                            **kwargs,
                        )

                    # 8. Wait for background memory creation and cultural knowledge creation
                    yield from wait_for_thread_tasks_stream(
                        memory_future=memory_future,  # type: ignore
                        cultural_knowledge_future=cultural_knowledge_future,  # type: ignore
                        learning_future=learning_future,  # type: ignore
                        stream_events=stream_events,
                        run_response=run_response,
                        events_to_skip=self.events_to_skip,
                        store_events=self.store_events,
                        get_memories_callback=lambda: self.get_user_memories(user_id=user_id),
                    )

                    # 9. Create session summary
                    if self.session_summary_manager is not None and self.enable_session_summaries:
                        # Upsert the RunOutput to Agent Session before creating the session summary
                        session.upsert_run(run=run_response)

                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_session_summary_started_event(from_run_response=run_response),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )
                        try:
                            self.session_summary_manager.create_session_summary(session=session)
                        except Exception as e:
                            log_warning(f"Error in session summary creation: {str(e)}")
                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_session_summary_completed_event(
                                    from_run_response=run_response, session_summary=session.summary
                                ),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )

                    # Update run_response.session_state before creating RunCompletedEvent
                    # This ensures the event has the final state after all tool modifications
                    if session.session_data is not None and "session_state" in session.session_data:
                        run_response.session_state = session.session_data["session_state"]

                    # Create the run completed event
                    completed_event = handle_event(  # type: ignore
                        create_run_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                    # Set the run status to completed
                    run_response.status = RunStatus.completed

                    # 10. Cleanup and store the run response and session
                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                    if stream_events:
                        yield completed_event  # type: ignore

                    if yield_run_output:
                        yield run_response

                    # Log Agent Telemetry
                    self._log_agent_telemetry(session_id=session.session_id, run_id=run_response.run_id)

                    log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                    break
                except RunCancelledException as e:
                    # Handle run cancellation during streaming
                    log_info(f"Run {run_response.run_id} was cancelled during streaming")
                    run_response.content = str(e)
                    run_response.status = RunStatus.cancelled
                    yield handle_event(
                        create_run_cancelled_event(from_run_response=run_response, reason=str(e)),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                    # Cleanup and store the run response and session
                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )
                    break
                except (InputCheckError, OutputCheckError) as e:
                    # Handle exceptions during streaming
                    run_response.status = RunStatus.error
                    # Add error event to list of events
                    run_error = create_run_error_event(
                        run_response,
                        error=str(e),
                        error_id=e.error_id,
                        error_type=e.type,
                        additional_data=e.additional_data,
                    )
                    run_response.events = add_error_event(error=run_error, events=run_response.events)

                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )
                    yield run_error
                    break
                except KeyboardInterrupt:
                    run_response = cast(RunOutput, run_response)
                    yield handle_event(  # type: ignore
                        create_run_cancelled_event(
                            from_run_response=run_response, reason="Operation cancelled by user"
                        ),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )
                    break
                except Exception as e:
                    if attempt < num_attempts - 1:
                        # Calculate delay with exponential backoff if enabled
                        if self.exponential_backoff:
                            delay = self.delay_between_retries * (2**attempt)
                        else:
                            delay = self.delay_between_retries

                        log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                        time.sleep(delay)
                        continue

                    run_response.status = RunStatus.error
                    # Add error event to list of events
                    run_error = create_run_error_event(run_response, error=str(e))
                    run_response.events = add_error_event(error=run_error, events=run_response.events)

                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Error in Agent run: {str(e)}")

                    # Cleanup and store the run response and session
                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                    yield run_error
        finally:
            # Cancel background futures on error (wait_for_thread_tasks_stream handles waiting on success)
            if memory_future is not None and not memory_future.done():
                memory_future.cancel()
            if cultural_knowledge_future is not None and not cultural_knowledge_future.done():
                cultural_knowledge_future.cancel()
            if learning_future is not None and not learning_future.done():
                learning_future.cancel()

            # Always disconnect connectable tools
            self._disconnect_connectable_tools()
            # Always clean up the run tracking
            cleanup_run(run_response.run_id)  # type: ignore

    @overload
    def run(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Literal[False] = False,
        stream_events: Optional[bool] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
        run_id: Optional[str] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
        debug_mode: Optional[bool] = None,
        **kwargs: Any,
    ) -> RunOutput: ...

    @overload
    def run(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Literal[True] = True,
        stream_events: Optional[bool] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
        run_id: Optional[str] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
        yield_run_output: bool = False,
        debug_mode: Optional[bool] = None,
        **kwargs: Any,
    ) -> Iterator[Union[RunOutputEvent, RunOutput]]: ...

    def run(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Optional[bool] = None,
        stream_events: Optional[bool] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
        run_id: Optional[str] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
        yield_run_output: Optional[bool] = None,
        debug_mode: Optional[bool] = None,
        **kwargs: Any,
    ) -> Union[RunOutput, Iterator[Union[RunOutputEvent, RunOutput]]]:
        """Run the Agent and return the response."""
        if self._has_async_db():
            raise RuntimeError(
                "`run` method is not supported with an async database. Please use `arun` method instead."
            )

        # Initialize session early for error handling
        session_id, user_id = self._initialize_session(session_id=session_id, user_id=user_id)
        # Set the id for the run
        run_id = run_id or str(uuid4())
        register_run(run_id)

        if (add_history_to_context or self.add_history_to_context) and not self.db and not self.team_id:
            log_warning(
                "add_history_to_context is True, but no database has been assigned to the agent. History will not be added to the context."
            )

        background_tasks = kwargs.pop("background_tasks", None)
        if background_tasks is not None:
            from fastapi import BackgroundTasks

            background_tasks: BackgroundTasks = background_tasks  # type: ignore

        # Validate input against input_schema if provided
        validated_input = validate_input(input, self.input_schema)

        # Normalise hook & guardails
        if not self._hooks_normalised:
            if self.pre_hooks:
                self.pre_hooks = normalize_pre_hooks(self.pre_hooks)  # type: ignore
            if self.post_hooks:
                self.post_hooks = normalize_post_hooks(self.post_hooks)  # type: ignore
            self._hooks_normalised = True

        session_id, user_id = self._initialize_session(session_id=session_id, user_id=user_id)

        # Initialize the Agent
        self.initialize_agent(debug_mode=debug_mode)

        image_artifacts, video_artifacts, audio_artifacts, file_artifacts = validate_media_object_id(
            images=images, videos=videos, audios=audio, files=files
        )

        # Create RunInput to capture the original user input
        run_input = RunInput(
            input_content=validated_input,
            images=image_artifacts,
            videos=video_artifacts,
            audios=audio_artifacts,
            files=file_artifacts,
        )

        # Read existing session from database
        agent_session = self._read_or_create_session(session_id=session_id, user_id=user_id)
        self._update_metadata(session=agent_session)

        # Initialize session state. Get it from DB if relevant.
        session_state = session_state if session_state is not None else {}
        session_state = self._load_session_state(session=agent_session, session_state=session_state)

        # Determine runtime dependencies
        dependencies = dependencies if dependencies is not None else self.dependencies

        # Resolve output_schema parameter takes precedence, then fall back to self.output_schema
        if output_schema is None:
            output_schema = self.output_schema

        # Initialize run context
        run_context = run_context or RunContext(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            session_state=session_state,
            dependencies=dependencies,
            output_schema=output_schema,
        )
        # output_schema parameter takes priority, even if run_context was provided
        run_context.output_schema = output_schema

        # Resolve dependencies
        if run_context.dependencies is not None:
            self._resolve_run_dependencies(run_context=run_context)

        add_dependencies = (
            add_dependencies_to_context if add_dependencies_to_context is not None else self.add_dependencies_to_context
        )
        add_session_state = (
            add_session_state_to_context
            if add_session_state_to_context is not None
            else self.add_session_state_to_context
        )
        add_history = add_history_to_context if add_history_to_context is not None else self.add_history_to_context

        # When filters are passed manually
        if self.knowledge_filters or knowledge_filters:
            run_context.knowledge_filters = self._get_effective_filters(knowledge_filters)

        # Use stream override value when necessary
        if stream is None:
            stream = False if self.stream is None else self.stream

        # Can't stream events if streaming is disabled
        if stream is False:
            stream_events = False

        if stream_events is None:
            stream_events = False if self.stream_events is None else self.stream_events

        # Prepare arguments for the model
        response_format = self._get_response_format(run_context=run_context) if self.parser_model is None else None
        self.model = cast(Model, self.model)

        # Merge caller-provided metadata into run_context metadata
        if metadata is not None:
            if run_context.metadata is None:
                run_context.metadata = metadata
            else:
                merge_dictionaries(run_context.metadata, metadata)

        # Merge agent metadata with run metadata
        if self.metadata is not None:
            if run_context.metadata is None:
                run_context.metadata = self.metadata
            else:
                merge_dictionaries(run_context.metadata, self.metadata)

        # Create a new run_response for this attempt
        run_response = RunOutput(
            run_id=run_id,
            session_id=session_id,
            agent_id=self.id,
            user_id=user_id,
            agent_name=self.name,
            metadata=run_context.metadata,
            session_state=run_context.session_state,
            input=run_input,
        )

        run_response.model = self.model.id if self.model is not None else None
        run_response.model_provider = self.model.provider if self.model is not None else None

        # Start the run metrics timer, to calculate the run duration
        run_response.metrics = Metrics()
        run_response.metrics.start_timer()

        if stream:
            response_iterator = self._run_stream(
                run_response=run_response,
                run_context=run_context,
                session=agent_session,
                user_id=user_id,
                add_history_to_context=add_history,
                add_dependencies_to_context=add_dependencies,
                add_session_state_to_context=add_session_state,
                response_format=response_format,
                stream_events=stream_events,
                yield_run_output=yield_run_output,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )
            return response_iterator
        else:
            response = self._run(
                run_response=run_response,
                run_context=run_context,
                session=agent_session,
                user_id=user_id,
                add_history_to_context=add_history,
                add_dependencies_to_context=add_dependencies,
                add_session_state_to_context=add_session_state,
                response_format=response_format,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )
            return response

    async def _arun(
        self,
        run_response: RunOutput,
        run_context: RunContext,
        session_id: str,
        user_id: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> RunOutput:
        """Run the Agent and return the RunOutput.

        Steps:
        1. Read or create session
        2. Update metadata and session state
        3. Resolve dependencies
        4. Execute pre-hooks
        5. Determine tools for model
        6. Prepare run messages
        7. Start memory creation in background task
        8. Reason about the task if reasoning is enabled
        9. Generate a response from the Model (includes running function calls)
        10. Update the RunOutput with the model response
        11. Convert response to structured format
        12. Store media if enabled
        13. Execute post-hooks
        14. Wait for background memory creation
        15. Create session summary
        16. Cleanup and store (scrub, stop timer, save to file, add to session, calculate metrics, save session)
        """
        await aregister_run(run_context.run_id)
        log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

        memory_task = None
        learning_task = None
        cultural_knowledge_task = None

        # Set up retry logic
        num_attempts = self.retries + 1

        try:
            for attempt in range(num_attempts):
                if num_attempts > 1:
                    log_debug(f"Retrying Agent run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

                try:
                    # 1. Read or create session. Reads from the database if provided.
                    agent_session = await self._aread_or_create_session(session_id=session_id, user_id=user_id)

                    # 2. Update metadata and session state
                    self._update_metadata(session=agent_session)

                    # Initialize session state. Get it from DB if relevant.
                    run_context.session_state = self._load_session_state(
                        session=agent_session,
                        session_state=run_context.session_state if run_context.session_state is not None else {},
                    )

                    # 3. Resolve dependencies
                    if run_context.dependencies is not None:
                        await self._aresolve_run_dependencies(run_context=run_context)

                    # 4. Execute pre-hooks
                    run_input = cast(RunInput, run_response.input)
                    self.model = cast(Model, self.model)
                    if self.pre_hooks is not None:
                        # Can modify the run input
                        pre_hook_iterator = self._aexecute_pre_hooks(
                            hooks=self.pre_hooks,  # type: ignore
                            run_response=run_response,
                            run_context=run_context,
                            run_input=run_input,
                            session=agent_session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            background_tasks=background_tasks,
                            **kwargs,
                        )
                        # Consume the async iterator without yielding
                        async for _ in pre_hook_iterator:
                            pass

                    # 5. Determine tools for model
                    self.model = cast(Model, self.model)
                    processed_tools = await self.aget_tools(
                        run_response=run_response,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                    )

                    _tools = self._determine_tools_for_model(
                        model=self.model,
                        processed_tools=processed_tools,
                        run_response=run_response,
                        run_context=run_context,
                        session=agent_session,
                        async_mode=True,
                    )

                    # 6. Prepare run messages
                    run_messages: RunMessages = await self._aget_run_messages(
                        run_response=run_response,
                        run_context=run_context,
                        input=run_input.input_content,
                        session=agent_session,
                        user_id=user_id,
                        audio=run_input.audios,
                        images=run_input.images,
                        videos=run_input.videos,
                        files=run_input.files,
                        add_history_to_context=add_history_to_context,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                        tools=_tools,
                        **kwargs,
                    )
                    if len(run_messages.messages) == 0:
                        log_error("No messages to be sent to the model.")

                    # 7. Start memory creation as a background task (runs concurrently with the main execution)
                    memory_task = await self._astart_memory_task(
                        run_messages=run_messages,
                        user_id=user_id,
                        existing_task=memory_task,
                    )

                    # Start learning extraction as a background task
                    learning_task = await self._astart_learning_task(
                        run_messages=run_messages,
                        session=agent_session,
                        user_id=user_id,
                        existing_task=learning_task,
                    )

                    # Start cultural knowledge creation as a background task (runs concurrently with the main execution)
                    cultural_knowledge_task = await self._astart_cultural_knowledge_task(
                        run_messages=run_messages,
                        existing_task=cultural_knowledge_task,
                    )

                    # Check for cancellation before model call
                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 8. Reason about the task if reasoning is enabled
                    await self._ahandle_reasoning(
                        run_response=run_response, run_messages=run_messages, run_context=run_context
                    )

                    # Check for cancellation before model call
                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 9. Generate a response from the Model (includes running function calls)
                    model_response: ModelResponse = await self.model.aresponse(
                        messages=run_messages.messages,
                        tools=_tools,
                        tool_choice=self.tool_choice,
                        tool_call_limit=self.tool_call_limit,
                        response_format=response_format,
                        send_media_to_model=self.send_media_to_model,
                        run_response=run_response,
                        compression_manager=self.compression_manager if self.compress_tool_results else None,
                    )

                    # Check for cancellation after model call
                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # If an output model is provided, generate output using the output model
                    await self._agenerate_response_with_output_model(
                        model_response=model_response, run_messages=run_messages
                    )

                    # If a parser model is provided, structure the response separately
                    await self._aparse_response_with_parser_model(
                        model_response=model_response, run_messages=run_messages, run_context=run_context
                    )

                    # 10. Update the RunOutput with the model response
                    self._update_run_response(
                        model_response=model_response,
                        run_response=run_response,
                        run_messages=run_messages,
                        run_context=run_context,
                    )

                    # We should break out of the run function
                    if any(tool_call.is_paused for tool_call in run_response.tools or []):
                        await await_for_open_threads(
                            memory_task=memory_task,
                            cultural_knowledge_task=cultural_knowledge_task,
                            learning_task=learning_task,
                        )
                        return await self._ahandle_agent_run_paused(
                            run_response=run_response, session=agent_session, user_id=user_id
                        )

                    # 11. Convert the response to the structured format if needed
                    self._convert_response_to_structured_format(run_response, run_context=run_context)

                    # 12. Store media if enabled
                    if self.store_media:
                        store_media_util(run_response, model_response)

                    # 13. Execute post-hooks (after output is generated but before response is returned)
                    if self.post_hooks is not None:
                        async for _ in self._aexecute_post_hooks(
                            hooks=self.post_hooks,  # type: ignore
                            run_output=run_response,
                            run_context=run_context,
                            session=agent_session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            background_tasks=background_tasks,
                            **kwargs,
                        ):
                            pass

                    # Check for cancellation
                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 14. Wait for background memory creation
                    await await_for_open_threads(
                        memory_task=memory_task,
                        cultural_knowledge_task=cultural_knowledge_task,
                        learning_task=learning_task,
                    )

                    # 15. Create session summary
                    if self.session_summary_manager is not None and self.enable_session_summaries:
                        # Upsert the RunOutput to Agent Session before creating the session summary
                        agent_session.upsert_run(run=run_response)
                        try:
                            await self.session_summary_manager.acreate_session_summary(session=agent_session)
                        except Exception as e:
                            log_warning(f"Error in session summary creation: {str(e)}")

                    run_response.status = RunStatus.completed

                    # 16. Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                    # Log Agent Telemetry
                    await self._alog_agent_telemetry(session_id=agent_session.session_id, run_id=run_response.run_id)

                    log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                    return run_response

                except RunCancelledException as e:
                    # Handle run cancellation
                    log_info(f"Run {run_response.run_id} was cancelled")
                    run_response.content = str(e)
                    run_response.status = RunStatus.cancelled

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                    return run_response
                except (InputCheckError, OutputCheckError) as e:
                    # Handle exceptions during streaming
                    run_response.status = RunStatus.error
                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                    return run_response

                except KeyboardInterrupt:
                    run_response = cast(RunOutput, run_response)
                    run_response.status = RunStatus.cancelled
                    run_response.content = "Operation cancelled by user"
                    return run_response
                except Exception as e:
                    # Check if this is the last attempt
                    if attempt < num_attempts - 1:
                        # Calculate delay with exponential backoff if enabled
                        if self.exponential_backoff:
                            delay = self.delay_between_retries * (2**attempt)
                        else:
                            delay = self.delay_between_retries

                        log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                        time.sleep(delay)
                        continue

                    run_response.status = RunStatus.error

                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Error in Agent run: {str(e)}")

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                    return run_response
        finally:
            # Always disconnect connectable tools
            self._disconnect_connectable_tools()
            # Always disconnect MCP tools
            await self._disconnect_mcp_tools()

            # Cancel background tasks on error (await_for_open_threads handles waiting on success)
            if memory_task is not None and not memory_task.done():
                memory_task.cancel()
                try:
                    await memory_task
                except asyncio.CancelledError:
                    pass
            if cultural_knowledge_task is not None and not cultural_knowledge_task.done():
                cultural_knowledge_task.cancel()
                try:
                    await cultural_knowledge_task
                except asyncio.CancelledError:
                    pass
            if learning_task is not None and not learning_task.done():
                learning_task.cancel()
                try:
                    await learning_task
                except asyncio.CancelledError:
                    pass

            # Always clean up the run tracking
            await acleanup_run(run_response.run_id)  # type: ignore

        return run_response

    async def _arun_stream(
        self,
        run_response: RunOutput,
        run_context: RunContext,
        session_id: str,
        user_id: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        stream_events: bool = False,
        yield_run_output: Optional[bool] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]:
        """Run the Agent and yield the RunOutput.

        Steps:
        1. Read or create session
        2. Update metadata and session state
        3. Resolve dependencies
        4. Execute pre-hooks
        5. Determine tools for model
        6. Prepare run messages
        7. Start memory creation in background task
        8. Reason about the task if reasoning is enabled
        9. Generate a response from the Model (includes running function calls)
        10. Parse response with parser model if provided
        11. Wait for background memory creation
        12. Create session summary
        13. Cleanup and store (scrub, stop timer, save to file, add to session, calculate metrics, save session)
        """
        await aregister_run(run_context.run_id)
        log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

        memory_task = None
        cultural_knowledge_task = None
        learning_task = None

        # 1. Read or create session. Reads from the database if provided.
        agent_session = await self._aread_or_create_session(session_id=session_id, user_id=user_id)

        # Set up retry logic
        num_attempts = self.retries + 1
        try:
            for attempt in range(num_attempts):
                if num_attempts > 1:
                    log_debug(f"Retrying Agent run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

                try:
                    # Start the Run by yielding a RunStarted event
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_run_started_event(run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )

                    # 2. Update metadata and session state
                    self._update_metadata(session=agent_session)

                    # Initialize session state. Get it from DB if relevant.
                    run_context.session_state = self._load_session_state(
                        session=agent_session,
                        session_state=run_context.session_state if run_context.session_state is not None else {},
                    )

                    # 3. Resolve dependencies
                    if run_context.dependencies is not None:
                        await self._aresolve_run_dependencies(run_context=run_context)

                    # 4. Execute pre-hooks
                    run_input = cast(RunInput, run_response.input)
                    self.model = cast(Model, self.model)
                    if self.pre_hooks is not None:
                        pre_hook_iterator = self._aexecute_pre_hooks(
                            hooks=self.pre_hooks,  # type: ignore
                            run_response=run_response,
                            run_context=run_context,
                            run_input=run_input,
                            session=agent_session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            stream_events=stream_events,
                            background_tasks=background_tasks,
                            **kwargs,
                        )
                        async for event in pre_hook_iterator:
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                            yield event

                    # 5. Determine tools for model
                    self.model = cast(Model, self.model)
                    processed_tools = await self.aget_tools(
                        run_response=run_response,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                    )

                    _tools = self._determine_tools_for_model(
                        model=self.model,
                        processed_tools=processed_tools,
                        run_response=run_response,
                        run_context=run_context,
                        session=agent_session,
                        async_mode=True,
                    )

                    # 6. Prepare run messages
                    run_messages: RunMessages = await self._aget_run_messages(
                        run_response=run_response,
                        run_context=run_context,
                        input=run_input.input_content,
                        session=agent_session,
                        user_id=user_id,
                        audio=run_input.audios,
                        images=run_input.images,
                        videos=run_input.videos,
                        files=run_input.files,
                        add_history_to_context=add_history_to_context,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                        tools=_tools,
                        **kwargs,
                    )
                    if len(run_messages.messages) == 0:
                        log_error("No messages to be sent to the model.")

                    # 7. Start memory creation as a background task (runs concurrently with the main execution)
                    memory_task = await self._astart_memory_task(
                        run_messages=run_messages,
                        user_id=user_id,
                        existing_task=memory_task,
                    )

                    # Start learning extraction as a background task
                    learning_task = await self._astart_learning_task(
                        run_messages=run_messages,
                        session=agent_session,
                        user_id=user_id,
                        existing_task=learning_task,
                    )

                    # Start cultural knowledge creation as a background task (runs concurrently with the main execution)
                    cultural_knowledge_task = await self._astart_cultural_knowledge_task(
                        run_messages=run_messages,
                        existing_task=cultural_knowledge_task,
                    )

                    # 8. Reason about the task if reasoning is enabled
                    async for item in self._ahandle_reasoning_stream(
                        run_response=run_response,
                        run_messages=run_messages,
                        run_context=run_context,
                        stream_events=stream_events,
                    ):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield item

                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 9. Generate a response from the Model
                    if self.output_model is None:
                        async for event in self._ahandle_model_response_stream(
                            session=agent_session,
                            run_response=run_response,
                            run_messages=run_messages,
                            tools=_tools,
                            response_format=response_format,
                            stream_events=stream_events,
                            session_state=run_context.session_state,
                            run_context=run_context,
                        ):
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                            yield event
                    else:
                        from agno.run.agent import (
                            IntermediateRunContentEvent,
                            RunContentEvent,
                        )  # type: ignore

                        async for event in self._ahandle_model_response_stream(
                            session=agent_session,
                            run_response=run_response,
                            run_messages=run_messages,
                            tools=_tools,
                            response_format=response_format,
                            stream_events=stream_events,
                            session_state=run_context.session_state,
                            run_context=run_context,
                        ):
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                            if isinstance(event, RunContentEvent):
                                if stream_events:
                                    yield IntermediateRunContentEvent(
                                        content=event.content,
                                        content_type=event.content_type,
                                    )
                            else:
                                yield event

                        # If an output model is provided, generate output using the output model
                        async for event in self._agenerate_response_with_output_model_stream(
                            session=agent_session,
                            run_response=run_response,
                            run_messages=run_messages,
                            stream_events=stream_events,
                        ):
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                            yield event  # type: ignore

                    # Check for cancellation after model processing
                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 10. Parse response with parser model if provided
                    async for event in self._aparse_response_with_parser_model_stream(
                        session=agent_session,
                        run_response=run_response,
                        stream_events=stream_events,
                        run_context=run_context,
                    ):
                        yield event  # type: ignore

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_run_content_completed_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )

                    # Break out of the run function if a tool call is paused
                    if any(tool_call.is_paused for tool_call in run_response.tools or []):
                        async for item in await_for_thread_tasks_stream(
                            memory_task=memory_task,
                            cultural_knowledge_task=cultural_knowledge_task,
                            learning_task=learning_task,
                            stream_events=stream_events,
                            run_response=run_response,
                            events_to_skip=self.events_to_skip,
                            store_events=self.store_events,
                            get_memories_callback=lambda: self.aget_user_memories(user_id=user_id),
                        ):
                            yield item

                        async for item in self._ahandle_agent_run_paused_stream(
                            run_response=run_response, session=agent_session, user_id=user_id
                        ):
                            yield item
                        return

                    # Execute post-hooks (after output is generated but before response is returned)
                    if self.post_hooks is not None:
                        async for event in self._aexecute_post_hooks(
                            hooks=self.post_hooks,  # type: ignore
                            run_output=run_response,
                            run_context=run_context,
                            session=agent_session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            stream_events=stream_events,
                            background_tasks=background_tasks,
                            **kwargs,
                        ):
                            yield event

                    # 11. Wait for background memory creation
                    async for item in await_for_thread_tasks_stream(
                        memory_task=memory_task,
                        cultural_knowledge_task=cultural_knowledge_task,
                        learning_task=learning_task,
                        stream_events=stream_events,
                        run_response=run_response,
                        events_to_skip=self.events_to_skip,
                        store_events=self.store_events,
                        get_memories_callback=lambda: self.aget_user_memories(user_id=user_id),
                    ):
                        yield item

                    # 12. Create session summary
                    if self.session_summary_manager is not None and self.enable_session_summaries:
                        # Upsert the RunOutput to Agent Session before creating the session summary
                        agent_session.upsert_run(run=run_response)

                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_session_summary_started_event(from_run_response=run_response),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )
                        try:
                            await self.session_summary_manager.acreate_session_summary(session=agent_session)
                        except Exception as e:
                            log_warning(f"Error in session summary creation: {str(e)}")
                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_session_summary_completed_event(
                                    from_run_response=run_response, session_summary=agent_session.summary
                                ),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )

                    # Update run_response.session_state before creating RunCompletedEvent
                    # This ensures the event has the final state after all tool modifications
                    if agent_session.session_data is not None and "session_state" in agent_session.session_data:
                        run_response.session_state = agent_session.session_data["session_state"]

                    # Create the run completed event
                    completed_event = handle_event(
                        create_run_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                    # Set the run status to completed
                    run_response.status = RunStatus.completed

                    # 13. Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                    if stream_events:
                        yield completed_event  # type: ignore

                    if yield_run_output:
                        yield run_response

                    # Log Agent Telemetry
                    await self._alog_agent_telemetry(session_id=agent_session.session_id, run_id=run_response.run_id)

                    log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                    # Break out of the run function
                    break

                except RunCancelledException as e:
                    # Handle run cancellation during async streaming
                    log_info(f"Run {run_response.run_id} was cancelled during async streaming")
                    run_response.status = RunStatus.cancelled
                    # Don't overwrite content - preserve any partial content that was streamed
                    # Only set content if it's empty
                    if not run_response.content:
                        run_response.content = str(e)

                    # Yield the cancellation event
                    yield handle_event(  # type: ignore
                        create_run_cancelled_event(from_run_response=run_response, reason=str(e)),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )
                    break

                except (InputCheckError, OutputCheckError) as e:
                    # Handle exceptions during async streaming
                    run_response.status = RunStatus.error
                    # Add error event to list of events
                    run_error = create_run_error_event(
                        run_response,
                        error=str(e),
                        error_id=e.error_id,
                        error_type=e.type,
                        additional_data=e.additional_data,
                    )
                    run_response.events = add_error_event(error=run_error, events=run_response.events)

                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                    # Yield the error event
                    yield run_error
                    break

                except KeyboardInterrupt:
                    run_response = cast(RunOutput, run_response)
                    yield handle_event(  # type: ignore
                        create_run_cancelled_event(
                            from_run_response=run_response, reason="Operation cancelled by user"
                        ),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )
                    break
                except Exception as e:
                    # Check if this is the last attempt
                    if attempt < num_attempts - 1:
                        # Calculate delay with exponential backoff if enabled
                        if self.exponential_backoff:
                            delay = self.delay_between_retries * (2**attempt)
                        else:
                            delay = self.delay_between_retries

                        log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                        time.sleep(delay)
                        continue

                    # Handle exceptions during async streaming
                    run_response.status = RunStatus.error
                    # Add error event to list of events
                    run_error = create_run_error_event(run_response, error=str(e))
                    run_response.events = add_error_event(error=run_error, events=run_response.events)

                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Error in Agent run: {str(e)}")

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                    # Yield the error event
                    yield run_error
        finally:
            # Always disconnect connectable tools
            self._disconnect_connectable_tools()
            # Always disconnect MCP tools
            await self._disconnect_mcp_tools()

            # Cancel background tasks on error (await_for_thread_tasks_stream handles waiting on success)
            if memory_task is not None and not memory_task.done():
                memory_task.cancel()
                try:
                    await memory_task
                except asyncio.CancelledError:
                    pass

            if cultural_knowledge_task is not None and not cultural_knowledge_task.done():
                cultural_knowledge_task.cancel()
                try:
                    await cultural_knowledge_task
                except asyncio.CancelledError:
                    pass

            if learning_task is not None and not learning_task.done():
                learning_task.cancel()
                try:
                    await learning_task
                except asyncio.CancelledError:
                    pass

            # Always clean up the run tracking
            await acleanup_run(run_response.run_id)  # type: ignore

    @overload
    async def arun(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Literal[False] = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
        run_id: Optional[str] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
        debug_mode: Optional[bool] = None,
        **kwargs: Any,
    ) -> RunOutput: ...

    @overload
    def arun(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Literal[True] = True,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        run_context: Optional[RunContext] = None,
        run_id: Optional[str] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
        yield_run_output: Optional[bool] = None,
        debug_mode: Optional[bool] = None,
        **kwargs: Any,
    ) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]: ...

    def arun(  # type: ignore
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Optional[bool] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
        run_id: Optional[str] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
        yield_run_output: Optional[bool] = None,
        debug_mode: Optional[bool] = None,
        **kwargs: Any,
    ) -> Union[RunOutput, AsyncIterator[RunOutputEvent]]:
        """Async Run the Agent and return the response."""

        # Set the id for the run and register it immediately for cancellation tracking
        run_id = run_id or str(uuid4())

        if (add_history_to_context or self.add_history_to_context) and not self.db and not self.team_id:
            log_warning(
                "add_history_to_context is True, but no database has been assigned to the agent. History will not be added to the context."
            )

        background_tasks = kwargs.pop("background_tasks", None)
        if background_tasks is not None:
            from fastapi import BackgroundTasks

            background_tasks: BackgroundTasks = background_tasks  # type: ignore

        # 2. Validate input against input_schema if provided
        validated_input = validate_input(input, self.input_schema)

        # Normalise hooks & guardails
        if not self._hooks_normalised:
            if self.pre_hooks:
                self.pre_hooks = normalize_pre_hooks(self.pre_hooks, async_mode=True)  # type: ignore
            if self.post_hooks:
                self.post_hooks = normalize_post_hooks(self.post_hooks, async_mode=True)  # type: ignore
            self._hooks_normalised = True

        # Initialize session
        session_id, user_id = self._initialize_session(session_id=session_id, user_id=user_id)

        # Initialize the Agent
        self.initialize_agent(debug_mode=debug_mode)

        image_artifacts, video_artifacts, audio_artifacts, file_artifacts = validate_media_object_id(
            images=images, videos=videos, audios=audio, files=files
        )

        # Resolve variables
        dependencies = dependencies if dependencies is not None else self.dependencies
        add_dependencies = (
            add_dependencies_to_context if add_dependencies_to_context is not None else self.add_dependencies_to_context
        )
        add_session_state = (
            add_session_state_to_context
            if add_session_state_to_context is not None
            else self.add_session_state_to_context
        )
        add_history = add_history_to_context if add_history_to_context is not None else self.add_history_to_context

        # Create RunInput to capture the original user input
        run_input = RunInput(
            input_content=validated_input,
            images=image_artifacts,
            videos=video_artifacts,
            audios=audio_artifacts,
            files=files,
        )

        # Use stream override value when necessary
        if stream is None:
            stream = False if self.stream is None else self.stream

        # Can't stream events if streaming is disabled
        if stream is False:
            stream_events = False

        if stream_events is None:
            stream_events = False if self.stream_events is None else self.stream_events

        self.model = cast(Model, self.model)

        # Get knowledge filters
        knowledge_filters = knowledge_filters
        if self.knowledge_filters or knowledge_filters:
            knowledge_filters = self._get_effective_filters(knowledge_filters)

        # Merge agent metadata with run metadata
        if self.metadata is not None:
            if metadata is None:
                metadata = self.metadata
            else:
                merge_dictionaries(metadata, self.metadata)

        # Resolve output_schema parameter takes precedence, then fall back to self.output_schema
        if output_schema is None:
            output_schema = self.output_schema

        # Initialize run context
        run_context = run_context or RunContext(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            session_state=session_state,
            dependencies=dependencies,
            knowledge_filters=knowledge_filters,
            metadata=metadata,
            output_schema=output_schema,
        )
        # output_schema parameter takes priority, even if run_context was provided
        run_context.output_schema = output_schema

        # Prepare arguments for the model (must be after run_context is fully initialized)
        response_format = self._get_response_format(run_context=run_context) if self.parser_model is None else None

        # Create a new run_response for this attempt
        run_response = RunOutput(
            run_id=run_id,
            session_id=session_id,
            agent_id=self.id,
            user_id=user_id,
            agent_name=self.name,
            metadata=run_context.metadata,
            session_state=run_context.session_state,
            input=run_input,
        )

        run_response.model = self.model.id if self.model is not None else None
        run_response.model_provider = self.model.provider if self.model is not None else None

        # Start the run metrics timer, to calculate the run duration
        run_response.metrics = Metrics()
        run_response.metrics.start_timer()

        yield_run_output = yield_run_output

        # Pass the new run_response to _arun
        if stream:
            return self._arun_stream(  # type: ignore
                run_response=run_response,
                run_context=run_context,
                user_id=user_id,
                response_format=response_format,
                stream_events=stream_events,
                yield_run_output=yield_run_output,
                session_id=session_id,
                add_history_to_context=add_history,
                add_dependencies_to_context=add_dependencies,
                add_session_state_to_context=add_session_state,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )  # type: ignore[assignment]
        else:
            return self._arun(  # type: ignore
                run_response=run_response,
                run_context=run_context,
                user_id=user_id,
                response_format=response_format,
                session_id=session_id,
                add_history_to_context=add_history,
                add_dependencies_to_context=add_dependencies,
                add_session_state_to_context=add_session_state,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )

    @overload
    def continue_run(
        self,
        run_response: Optional[RunOutput] = None,
        *,
        run_id: Optional[str] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        requirements: Optional[List[RunRequirement]] = None,
        stream: Literal[False] = False,
        stream_events: Optional[bool] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        debug_mode: Optional[bool] = None,
        yield_run_output: bool = False,
    ) -> RunOutput: ...

    @overload
    def continue_run(
        self,
        run_response: Optional[RunOutput] = None,
        *,
        run_id: Optional[str] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        requirements: Optional[List[RunRequirement]] = None,
        stream: Literal[True] = True,
        stream_events: Optional[bool] = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        debug_mode: Optional[bool] = None,
        yield_run_output: bool = False,
    ) -> Iterator[RunOutputEvent]: ...

    def continue_run(
        self,
        run_response: Optional[RunOutput] = None,
        *,
        run_id: Optional[str] = None,  # type: ignore
        updated_tools: Optional[List[ToolExecution]] = None,
        requirements: Optional[List[RunRequirement]] = None,
        stream: Optional[bool] = None,
        stream_events: Optional[bool] = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        run_context: Optional[RunContext] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        debug_mode: Optional[bool] = None,
        yield_run_output: bool = False,
        **kwargs,
    ) -> Union[RunOutput, Iterator[Union[RunOutputEvent, RunOutput]]]:
        """Continue a previous run.

        Args:
            run_response: The run response to continue.
            run_id: The run id to continue. Alternative to passing run_response.
            requirements: The requirements to continue the run. This or updated_tools is required with `run_id`.
            stream: Whether to stream the response.
            stream_events: Whether to stream all events.
            user_id: The user id to continue the run for.
            session_id: The session id to continue the run for.
            run_context: The run context to use for the run.
            knowledge_filters: The knowledge filters to use for the run.
            dependencies: The dependencies to use for the run.
            metadata: The metadata to use for the run.
            debug_mode: Whether to enable debug mode.
        """
        if run_response is None and run_id is None:
            raise ValueError("Either run_response or run_id must be provided.")

        if run_response is None and (run_id is not None and (session_id is None and self.session_id is None)):
            raise ValueError("Session ID is required to continue a run from a run_id.")

        if self._has_async_db():
            raise Exception("continue_run() is not supported with an async DB. Please use acontinue_arun() instead.")

        background_tasks = kwargs.pop("background_tasks", None)
        if background_tasks is not None:
            from fastapi import BackgroundTasks

            background_tasks: BackgroundTasks = background_tasks  # type: ignore

        session_id = run_response.session_id if run_response else session_id
        run_id: str = run_response.run_id if run_response else run_id  # type: ignore

        session_id, user_id = self._initialize_session(
            session_id=session_id,
            user_id=user_id,
        )
        # Initialize the Agent
        self.initialize_agent(debug_mode=debug_mode)

        # Read existing session from storage
        agent_session = self._read_or_create_session(session_id=session_id, user_id=user_id)
        self._update_metadata(session=agent_session)

        # Initialize session state. Get it from DB if relevant.
        session_state = self._load_session_state(session=agent_session, session_state={})

        dependencies = dependencies if dependencies is not None else self.dependencies

        # Initialize run context
        run_context = run_context or RunContext(
            run_id=run_id,  # type: ignore
            session_id=session_id,
            user_id=user_id,
            session_state=session_state,
            dependencies=dependencies,
        )

        # Resolve dependencies
        if run_context.dependencies is not None:
            self._resolve_run_dependencies(run_context=run_context)

        # When filters are passed manually
        if self.knowledge_filters or run_context.knowledge_filters or knowledge_filters:
            run_context.knowledge_filters = self._get_effective_filters(knowledge_filters)

        # Merge caller-provided metadata into run_context metadata
        if metadata is not None:
            if run_context.metadata is None:
                run_context.metadata = metadata
            else:
                merge_dictionaries(run_context.metadata, metadata)

        # Merge agent metadata with run metadata
        if self.metadata is not None:
            if run_context.metadata is None:
                run_context.metadata = self.metadata
            else:
                merge_dictionaries(run_context.metadata, self.metadata)

        # Use stream override value when necessary
        if stream is None:
            stream = False if self.stream is None else self.stream

        # Can't stream events if streaming is disabled
        if stream is False:
            stream_events = False

        if stream_events is None:
            stream_events = False if self.stream_events is None else self.stream_events

        # Run can be continued from previous run response or from passed run_response context
        if run_response is not None:
            # The run is continued from a provided run_response. This contains the updated tools.
            input = run_response.messages or []
        elif run_id is not None:
            # The run is continued from a run_id, one of requirements or updated_tool (deprecated) is required.
            if updated_tools is None and requirements is None:
                raise ValueError("To continue a run from a given run_id, the requirements parameter must be provided.")

            runs = agent_session.runs
            run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
            if run_response is None:
                raise RuntimeError(f"No runs found for run ID {run_id}")

            input = run_response.messages or []

            # If we have updated_tools, set them in the run_response
            if updated_tools is not None:
                warnings.warn(
                    "The 'updated_tools' parameter is deprecated and will be removed in future versions. Use 'requirements' instead.",
                    DeprecationWarning,
                    stacklevel=2,
                )
                run_response.tools = updated_tools

            # If we have requirements, get the updated tools and set them in the run_response
            elif requirements is not None:
                run_response.requirements = requirements
                updated_tools = [req.tool_execution for req in requirements if req.tool_execution is not None]
                if updated_tools and run_response.tools:
                    updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
                    run_response.tools = [updated_tools_map.get(tool.tool_call_id, tool) for tool in run_response.tools]
                else:
                    run_response.tools = updated_tools
        else:
            raise ValueError("Either run_response or run_id must be provided.")

        # Prepare arguments for the model
        self._set_default_model()
        response_format = self._get_response_format(run_context=run_context)
        self.model = cast(Model, self.model)

        processed_tools = self.get_tools(
            run_response=run_response,
            run_context=run_context,
            session=agent_session,
            user_id=user_id,
        )

        _tools = self._determine_tools_for_model(
            model=self.model,
            processed_tools=processed_tools,
            run_response=run_response,
            run_context=run_context,
            session=agent_session,
        )

        run_response = cast(RunOutput, run_response)

        log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

        # Prepare run messages
        run_messages = self._get_continue_run_messages(
            input=input,
        )

        # Reset the run state
        run_response.status = RunStatus.running

        if stream:
            response_iterator = self._continue_run_stream(
                run_response=run_response,
                run_messages=run_messages,
                run_context=run_context,
                tools=_tools,
                user_id=user_id,
                session=agent_session,
                response_format=response_format,
                stream_events=stream_events,
                yield_run_output=yield_run_output,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )
            return response_iterator
        else:
            response = self._continue_run(
                run_response=run_response,
                run_messages=run_messages,
                run_context=run_context,
                tools=_tools,
                user_id=user_id,
                session=agent_session,
                response_format=response_format,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )
            return response

    def _continue_run(
        self,
        run_response: RunOutput,
        run_messages: RunMessages,
        run_context: RunContext,
        session: AgentSession,
        tools: List[Union[Function, dict]],
        user_id: Optional[str] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs,
    ) -> RunOutput:
        """Continue a previous run.

        Steps:
        1. Handle any updated tools
        2. Generate a response from the Model
        3. Update the RunOutput with the model response
        4. Convert response to structured format
        5. Store media if enabled
        6. Execute post-hooks
        7. Create session summary
        8. Cleanup and store (scrub, stop timer, save to file, add to session, calculate metrics, save session)
        """
        # Register run for cancellation tracking
        register_run(run_response.run_id)  # type: ignore

        self.model = cast(Model, self.model)

        # 1. Handle the updated tools
        self._handle_tool_call_updates(run_response=run_response, run_messages=run_messages, tools=tools)

        try:
            num_attempts = self.retries + 1
            for attempt in range(num_attempts):
                try:
                    # Check for cancellation before model call
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 2. Generate a response from the Model (includes running function calls)
                    self.model = cast(Model, self.model)
                    model_response: ModelResponse = self.model.response(
                        messages=run_messages.messages,
                        response_format=response_format,
                        tools=tools,
                        tool_choice=self.tool_choice,
                        tool_call_limit=self.tool_call_limit,
                        run_response=run_response,
                        send_media_to_model=self.send_media_to_model,
                        compression_manager=self.compression_manager if self.compress_tool_results else None,
                    )

                    # Check for cancellation after model processing
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 3. Update the RunOutput with the model response
                    self._update_run_response(
                        model_response=model_response, run_response=run_response, run_messages=run_messages
                    )

                    # We should break out of the run function
                    if any(tool_call.is_paused for tool_call in run_response.tools or []):
                        return self._handle_agent_run_paused(
                            run_response=run_response, session=session, user_id=user_id
                        )

                    # 4. Convert the response to the structured format if needed
                    self._convert_response_to_structured_format(run_response, run_context=run_context)

                    # 5. Store media if enabled
                    if self.store_media:
                        store_media_util(run_response, model_response)

                    # 6. Execute post-hooks
                    if self.post_hooks is not None:
                        post_hook_iterator = self._execute_post_hooks(
                            hooks=self.post_hooks,  # type: ignore
                            run_output=run_response,
                            run_context=run_context,
                            session=session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            background_tasks=background_tasks,
                            **kwargs,
                        )
                        deque(post_hook_iterator, maxlen=0)
                    # Check for cancellation
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 7. Create session summary
                    if self.session_summary_manager is not None and self.enable_session_summaries:
                        # Upsert the RunOutput to Agent Session before creating the session summary
                        session.upsert_run(run=run_response)

                        try:
                            self.session_summary_manager.create_session_summary(session=session)
                        except Exception as e:
                            log_warning(f"Error in session summary creation: {str(e)}")

                    # Set the run status to completed
                    run_response.status = RunStatus.completed

                    # 8. Cleanup and store the run response and session
                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                    # Log Agent Telemetry
                    self._log_agent_telemetry(session_id=session.session_id, run_id=run_response.run_id)

                    return run_response
                except RunCancelledException as e:
                    run_response = cast(RunOutput, run_response)
                    # Handle run cancellation during async streaming
                    log_info(f"Run {run_response.run_id} was cancelled")
                    run_response.status = RunStatus.cancelled
                    run_response.content = str(e)

                    # Cleanup and store the run response and session
                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                    return run_response
                except (InputCheckError, OutputCheckError) as e:
                    run_response = cast(RunOutput, run_response)
                    # Handle exceptions during streaming
                    run_response.status = RunStatus.error
                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                    return run_response
                except KeyboardInterrupt:
                    run_response = cast(RunOutput, run_response)
                    run_response.status = RunStatus.cancelled
                    run_response.content = "Operation cancelled by user"
                    return run_response

                except Exception as e:
                    run_response = cast(RunOutput, run_response)
                    # Check if this is the last attempt
                    if attempt < num_attempts - 1:
                        # Calculate delay with exponential backoff if enabled
                        if self.exponential_backoff:
                            delay = self.delay_between_retries * (2**attempt)
                        else:
                            delay = self.delay_between_retries

                        log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                    run_response.status = RunStatus.error

                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Error in Agent run: {str(e)}")

                    # Cleanup and store the run response and session
                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                    return run_response
        finally:
            # Always disconnect connectable tools
            self._disconnect_connectable_tools()
            # Always clean up the run tracking
            cleanup_run(run_response.run_id)  # type: ignore
        return run_response

    def _continue_run_stream(
        self,
        run_response: RunOutput,
        run_messages: RunMessages,
        run_context: RunContext,
        session: AgentSession,
        tools: List[Union[Function, dict]],
        user_id: Optional[str] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        stream_events: bool = False,
        debug_mode: Optional[bool] = None,
        yield_run_output: bool = False,
        background_tasks: Optional[Any] = None,
        **kwargs,
    ) -> Iterator[Union[RunOutputEvent, RunOutput]]:
        """Continue a previous run.

        Steps:
        1. Resolve dependencies
        2. Handle any updated tools
        3. Process model response
        4. Execute post-hooks
        5. Create session summary
        6. Cleanup and store the run response and session
        """

        # Set up retry logic
        num_attempts = self.retries + 1
        try:
            for attempt in range(num_attempts):
                try:
                    # 1. Resolve dependencies
                    if run_context.dependencies is not None:
                        self._resolve_run_dependencies(run_context=run_context)

                    # Start the Run by yielding a RunContinued event
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_run_continued_event(run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )

                    # 2. Handle the updated tools
                    yield from self._handle_tool_call_updates_stream(
                        run_response=run_response, run_messages=run_messages, tools=tools, stream_events=stream_events
                    )

                    # 3. Process model response
                    for event in self._handle_model_response_stream(
                        session=session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        session_state=run_context.session_state,
                        run_context=run_context,
                    ):
                        yield event

                    # Parse response with parser model if provided
                    yield from self._parse_response_with_parser_model_stream(  # type: ignore
                        session=session, run_response=run_response, stream_events=stream_events
                    )

                    # Yield RunContentCompletedEvent
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_run_content_completed_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )

                    # We should break out of the run function
                    if any(tool_call.is_paused for tool_call in run_response.tools or []):
                        yield from self._handle_agent_run_paused_stream(
                            run_response=run_response, session=session, user_id=user_id
                        )
                        return

                    # Execute post-hooks
                    if self.post_hooks is not None:
                        yield from self._execute_post_hooks(
                            hooks=self.post_hooks,  # type: ignore
                            run_output=run_response,
                            session=session,
                            run_context=run_context,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            stream_events=stream_events,
                            background_tasks=background_tasks,
                            **kwargs,
                        )

                    # Check for cancellation before model call
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 4. Create session summary
                    if self.session_summary_manager is not None and self.enable_session_summaries:
                        # Upsert the RunOutput to Agent Session before creating the session summary
                        session.upsert_run(run=run_response)

                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_session_summary_started_event(from_run_response=run_response),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )
                        try:
                            self.session_summary_manager.create_session_summary(session=session)
                        except Exception as e:
                            log_warning(f"Error in session summary creation: {str(e)}")

                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_session_summary_completed_event(
                                    from_run_response=run_response, session_summary=session.summary
                                ),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )

                    # Update run_response.session_state before creating RunCompletedEvent
                    # This ensures the event has the final state after all tool modifications
                    if session.session_data is not None and "session_state" in session.session_data:
                        run_response.session_state = session.session_data["session_state"]

                    # Create the run completed event
                    completed_event = handle_event(
                        create_run_completed_event(run_response),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                    # Set the run status to completed
                    run_response.status = RunStatus.completed

                    # 5. Cleanup and store the run response and session
                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                    if stream_events:
                        yield completed_event  # type: ignore

                    if yield_run_output:
                        yield run_response

                    # Log Agent Telemetry
                    self._log_agent_telemetry(session_id=session.session_id, run_id=run_response.run_id)

                    log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                    break
                except RunCancelledException as e:
                    run_response = cast(RunOutput, run_response)
                    # Handle run cancellation during async streaming
                    log_info(f"Run {run_response.run_id} was cancelled during streaming")
                    run_response.status = RunStatus.cancelled
                    run_response.content = str(e)

                    # Yield the cancellation event
                    yield handle_event(  # type: ignore
                        create_run_cancelled_event(from_run_response=run_response, reason=str(e)),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                    # Cleanup and store the run response and session
                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )
                    break
                except (InputCheckError, OutputCheckError) as e:
                    run_response = cast(RunOutput, run_response)
                    # Handle exceptions during streaming
                    run_response.status = RunStatus.error
                    # Add error event to list of events
                    run_error = create_run_error_event(
                        run_response,
                        error=str(e),
                        error_id=e.error_id,
                        error_type=e.type,
                        additional_data=e.additional_data,
                    )
                    run_response.events = add_error_event(error=run_error, events=run_response.events)

                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )
                    yield run_error
                    break
                except KeyboardInterrupt:
                    run_response = cast(RunOutput, run_response)
                    yield handle_event(  # type: ignore
                        create_run_cancelled_event(
                            from_run_response=run_response, reason="Operation cancelled by user"
                        ),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )
                    break

                except Exception as e:
                    run_response = cast(RunOutput, run_response)
                    # Check if this is the last attempt
                    if attempt < num_attempts - 1:
                        # Calculate delay with exponential backoff if enabled
                        if self.exponential_backoff:
                            delay = self.delay_between_retries * (2**attempt)
                        else:
                            delay = self.delay_between_retries

                        log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                    run_response.status = RunStatus.error
                    # Add error event to list of events
                    run_error = create_run_error_event(run_response, error=str(e))
                    run_response.events = add_error_event(error=run_error, events=run_response.events)

                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Error in Agent run: {str(e)}")

                    # Cleanup and store the run response and session
                    self._cleanup_and_store(
                        run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                    yield run_error
        finally:
            # Always disconnect connectable tools
            self._disconnect_connectable_tools()
            # Always clean up the run tracking
            cleanup_run(run_response.run_id)  # type: ignore

    @overload
    async def acontinue_run(
        self,
        run_response: Optional[RunOutput] = None,
        *,
        stream: Literal[False] = False,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        requirements: Optional[List[RunRequirement]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        debug_mode: Optional[bool] = None,
        **kwargs: Any,
    ) -> RunOutput: ...

    @overload
    def acontinue_run(
        self,
        run_response: Optional[RunOutput] = None,
        *,
        stream: Literal[True] = True,
        stream_events: Optional[bool] = None,
        run_id: Optional[str] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        requirements: Optional[List[RunRequirement]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        debug_mode: Optional[bool] = None,
        **kwargs: Any,
    ) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]: ...

    def acontinue_run(  # type: ignore
        self,
        run_response: Optional[RunOutput] = None,
        *,
        run_id: Optional[str] = None,  # type: ignore
        updated_tools: Optional[List[ToolExecution]] = None,
        requirements: Optional[List[RunRequirement]] = None,
        stream: Optional[bool] = None,
        stream_events: Optional[bool] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        run_context: Optional[RunContext] = None,
        knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        debug_mode: Optional[bool] = None,
        yield_run_output: bool = False,
        **kwargs,
    ) -> Union[RunOutput, AsyncIterator[Union[RunOutputEvent, RunOutput]]]:
        """Continue a previous run.

        Args:
            run_response: The run response to continue.
            run_id: The run id to continue. Alternative to passing run_response.

            requirements: The requirements to continue the run. This or updated_tools is required with `run_id`.
            stream: Whether to stream the response.
            stream_events: Whether to stream all events.
            user_id: The user id to continue the run for.
            session_id: The session id to continue the run for.
            run_context: The run context to use for the run.
            knowledge_filters: The knowledge filters to use for the run.
            dependencies: The dependencies to use for continuing the run.
            metadata: The metadata to use for continuing the run.
            debug_mode: Whether to enable debug mode.
            yield_run_output: Whether to yield the run response.
            (deprecated) updated_tools: Use 'requirements' instead.
        """
        if run_response is None and run_id is None:
            raise ValueError("Either run_response or run_id must be provided.")

        if run_response is None and (run_id is not None and (session_id is None and self.session_id is None)):
            raise ValueError("Session ID is required to continue a run from a run_id.")

        if updated_tools is not None:
            warnings.warn(
                "The 'updated_tools' parameter is deprecated and will be removed in future versions. Use 'requirements' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        background_tasks = kwargs.pop("background_tasks", None)
        if background_tasks is not None:
            from fastapi import BackgroundTasks

            background_tasks: BackgroundTasks = background_tasks  # type: ignore

        session_id, user_id = self._initialize_session(
            session_id=session_id,
            user_id=user_id,
        )
        run_id: str = run_id or run_response.run_id if run_response else run_id  # type: ignore

        # Initialize the Agent
        self.initialize_agent(debug_mode=debug_mode)

        dependencies = dependencies if dependencies is not None else self.dependencies

        # Use stream override value when necessary
        if stream is None:
            stream = False if self.stream is None else self.stream

        # Can't stream events if streaming is disabled
        if stream is False:
            stream_events = False

        if stream_events is None:
            stream_events = False if self.stream_events is None else self.stream_events

        # Can't have stream_events if stream is False
        if stream is False:
            stream_events = False

        # Get knowledge filters
        knowledge_filters = knowledge_filters
        if self.knowledge_filters or knowledge_filters:
            knowledge_filters = self._get_effective_filters(knowledge_filters)

        # Merge agent metadata with run metadata
        if self.metadata is not None:
            if metadata is None:
                metadata = self.metadata
            else:
                merge_dictionaries(metadata, self.metadata)

        # Prepare arguments for the model
        response_format = self._get_response_format(run_context=run_context)
        self.model = cast(Model, self.model)

        # Initialize run context
        run_context = run_context or RunContext(
            run_id=run_id,  # type: ignore
            session_id=session_id,
            user_id=user_id,
            session_state={},
            dependencies=dependencies,
            knowledge_filters=knowledge_filters,
            metadata=metadata,
        )

        if stream:
            return self._acontinue_run_stream(
                run_response=run_response,
                run_context=run_context,
                updated_tools=updated_tools,
                requirements=requirements,
                run_id=run_id,
                user_id=user_id,
                session_id=session_id,
                response_format=response_format,
                stream_events=stream_events,
                yield_run_output=yield_run_output,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )
        else:
            return self._acontinue_run(  # type: ignore
                session_id=session_id,
                run_response=run_response,
                run_context=run_context,
                updated_tools=updated_tools,
                requirements=requirements,
                run_id=run_id,
                user_id=user_id,
                response_format=response_format,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )

    async def _acontinue_run(
        self,
        session_id: str,
        run_context: RunContext,
        run_response: Optional[RunOutput] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        requirements: Optional[List[RunRequirement]] = None,
        run_id: Optional[str] = None,
        user_id: Optional[str] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs,
    ) -> RunOutput:
        """Continue a previous run.

        Steps:
        1. Read existing session from db
        2. Resolve dependencies
        3. Update metadata and session state
        4. Prepare run response
        5. Determine tools for model
        6. Prepare run messages
        7. Handle the updated tools
        8. Get model response
        9. Update the RunOutput with the model response
        10. Convert response to structured format
        11. Store media if enabled
        12. Execute post-hooks
        13. Create session summary
        14. Cleanup and store (scrub, stop timer, save to file, add to session, calculate metrics, save session)
        """
        log_debug(f"Agent Run Continue: {run_response.run_id if run_response else run_id}", center=True)  # type: ignore

        # Resolve retry parameters
        try:
            num_attempts = self.retries + 1
            for attempt in range(num_attempts):
                try:
                    if num_attempts > 1:
                        log_debug(f"Retrying Agent acontinue_run {run_id}. Attempt {attempt + 1} of {num_attempts}...")

                    # 1. Read existing session from db
                    agent_session = await self._aread_or_create_session(session_id=session_id, user_id=user_id)

                    # 2. Resolve dependencies
                    if run_context.dependencies is not None:
                        await self._aresolve_run_dependencies(run_context=run_context)

                    # 3. Update metadata and session state
                    self._update_metadata(session=agent_session)

                    # Initialize session state. Get it from DB if relevant.
                    run_context.session_state = self._load_session_state(
                        session=agent_session,
                        session_state=run_context.session_state if run_context.session_state is not None else {},
                    )

                    # 4. Prepare run response
                    if run_response is not None:
                        # The run is continued from a provided run_response. This contains the updated tools.
                        input = run_response.messages or []
                    elif run_id is not None:
                        # The run is continued from a run_id. This requires the updated tools to be passed.
                        if updated_tools is None and requirements is None:
                            raise ValueError(
                                "Either updated tools or requirements are required to continue a run from a run_id."
                            )

                        runs = agent_session.runs
                        run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
                        if run_response is None:
                            raise RuntimeError(f"No runs found for run ID {run_id}")

                        input = run_response.messages or []

                        # If we have updated_tools, set them in the run_response
                        if updated_tools is not None:
                            run_response.tools = updated_tools

                        # If we have requirements, get the updated tools and set them in the run_response
                        elif requirements is not None:
                            run_response.requirements = requirements
                            updated_tools = [
                                req.tool_execution for req in requirements if req.tool_execution is not None
                            ]
                            if updated_tools and run_response.tools:
                                updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
                                run_response.tools = [
                                    updated_tools_map.get(tool.tool_call_id, tool) for tool in run_response.tools
                                ]
                            else:
                                run_response.tools = updated_tools
                    else:
                        raise ValueError("Either run_response or run_id must be provided.")

                    run_response = cast(RunOutput, run_response)
                    run_response.status = RunStatus.running

                    # 5. Determine tools for model
                    self.model = cast(Model, self.model)
                    processed_tools = await self.aget_tools(
                        run_response=run_response,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                    )

                    _tools = self._determine_tools_for_model(
                        model=self.model,
                        processed_tools=processed_tools,
                        run_response=run_response,
                        run_context=run_context,
                        session=agent_session,
                        async_mode=True,
                    )

                    # 6. Prepare run messages
                    run_messages: RunMessages = self._get_continue_run_messages(
                        input=input,
                    )

                    # Register run for cancellation tracking
                    register_run(run_response.run_id)  # type: ignore

                    # 7. Handle the updated tools
                    await self._ahandle_tool_call_updates(
                        run_response=run_response, run_messages=run_messages, tools=_tools
                    )

                    # 8. Get model response
                    model_response: ModelResponse = await self.model.aresponse(
                        messages=run_messages.messages,
                        response_format=response_format,
                        tools=_tools,
                        tool_choice=self.tool_choice,
                        tool_call_limit=self.tool_call_limit,
                        run_response=run_response,
                        send_media_to_model=self.send_media_to_model,
                        compression_manager=self.compression_manager if self.compress_tool_results else None,
                    )
                    # Check for cancellation after model call
                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # If an output model is provided, generate output using the output model
                    await self._agenerate_response_with_output_model(
                        model_response=model_response, run_messages=run_messages
                    )

                    # If a parser model is provided, structure the response separately
                    await self._aparse_response_with_parser_model(
                        model_response=model_response, run_messages=run_messages, run_context=run_context
                    )

                    # 9. Update the RunOutput with the model response
                    self._update_run_response(
                        model_response=model_response,
                        run_response=run_response,
                        run_messages=run_messages,
                        run_context=run_context,
                    )

                    # Break out of the run function if a tool call is paused
                    if any(tool_call.is_paused for tool_call in run_response.tools or []):
                        return await self._ahandle_agent_run_paused(
                            run_response=run_response, session=agent_session, user_id=user_id
                        )

                    # 10. Convert the response to the structured format if needed
                    self._convert_response_to_structured_format(run_response, run_context=run_context)

                    # 11. Store media if enabled
                    if self.store_media:
                        store_media_util(run_response, model_response)

                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 12. Execute post-hooks
                    if self.post_hooks is not None:
                        async for _ in self._aexecute_post_hooks(
                            hooks=self.post_hooks,  # type: ignore
                            run_output=run_response,
                            run_context=run_context,
                            session=agent_session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            background_tasks=background_tasks,
                            **kwargs,
                        ):
                            pass

                    # Check for cancellation
                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 13. Create session summary
                    if self.session_summary_manager is not None and self.enable_session_summaries:
                        # Upsert the RunOutput to Agent Session before creating the session summary
                        agent_session.upsert_run(run=run_response)

                        try:
                            await self.session_summary_manager.acreate_session_summary(session=agent_session)
                        except Exception as e:
                            log_warning(f"Error in session summary creation: {str(e)}")

                    # Set the run status to completed
                    run_response.status = RunStatus.completed

                    # 14. Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                    # Log Agent Telemetry
                    await self._alog_agent_telemetry(session_id=agent_session.session_id, run_id=run_response.run_id)

                    log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                    return run_response

                except RunCancelledException as e:
                    run_response = cast(RunOutput, run_response)
                    # Handle run cancellation
                    log_info(f"Run {run_response.run_id if run_response else run_id} was cancelled")

                    run_response = RunOutput(
                        run_id=run_id,
                        status=RunStatus.cancelled,
                        content=str(e),
                    )
                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                    return run_response
                except (InputCheckError, OutputCheckError) as e:
                    run_response = cast(RunOutput, run_response)
                    # Handle exceptions during streaming
                    run_response.status = RunStatus.error
                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                    self._cleanup_and_store(
                        run_response=run_response, session=agent_session, run_context=run_context, user_id=user_id
                    )

                    return run_response

                except KeyboardInterrupt:
                    run_response = cast(RunOutput, run_response)
                    run_response.status = RunStatus.cancelled
                    run_response.content = "Operation cancelled by user"
                    return run_response
                except Exception as e:
                    run_response = cast(RunOutput, run_response)
                    # Check if this is the last attempt
                    if attempt < num_attempts - 1:
                        # Calculate delay with exponential backoff if enabled
                        if self.exponential_backoff:
                            delay = self.delay_between_retries * (2**attempt)
                        else:
                            delay = self.delay_between_retries

                        log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                        time.sleep(delay)
                        continue

                    if not run_response:
                        run_response = RunOutput(run_id=run_id)

                    run_response.status = RunStatus.error
                    # Add error event to list of events
                    run_error = create_run_error_event(run_response, error=str(e))  # type: ignore
                    run_response.events = add_error_event(error=run_error, events=run_response.events)  # type: ignore

                    # If the content is None, set it to the error message
                    if run_response.content is None:  # type: ignore
                        run_response.content = str(e)  # type: ignore

                    log_error(f"Error in Agent run: {str(e)}")

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,  # type: ignore
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                    return run_response  # type: ignore

        finally:
            # Always disconnect connectable tools
            self._disconnect_connectable_tools()
            # Always disconnect MCP tools
            await self._disconnect_mcp_tools()

            # Always clean up the run tracking
            cleanup_run(run_response.run_id)  # type: ignore
        return run_response  # type: ignore

    async def _acontinue_run_stream(
        self,
        session_id: str,
        run_context: RunContext,
        run_response: Optional[RunOutput] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        requirements: Optional[List[RunRequirement]] = None,
        run_id: Optional[str] = None,
        user_id: Optional[str] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        stream_events: bool = False,
        yield_run_output: bool = False,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs,
    ) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]:
        """Continue a previous run.

        Steps:
        1. Resolve dependencies
        2. Read existing session from db
        3. Update session state and metadata
        4. Prepare run response
        5. Determine tools for model
        6. Prepare run messages
        7. Handle the updated tools
        8. Process model response
        9. Create session summary
        10. Execute post-hooks
        11. Cleanup and store the run response and session
        """
        log_debug(f"Agent Run Continue: {run_response.run_id if run_response else run_id}", center=True)  # type: ignore

        # Resolve retry parameters
        try:
            num_attempts = self.retries + 1
            for attempt in range(num_attempts):
                try:
                    # 1. Read` existing session from db
                    agent_session = await self._aread_or_create_session(session_id=session_id, user_id=user_id)

                    # 2. Update session state and metadata
                    self._update_metadata(session=agent_session)

                    # Initialize session state. Get it from DB if relevant.
                    run_context.session_state = self._load_session_state(
                        session=agent_session,
                        session_state=run_context.session_state if run_context.session_state is not None else {},
                    )

                    # 3. Resolve dependencies
                    if run_context.dependencies is not None:
                        await self._aresolve_run_dependencies(run_context=run_context)

                    # 4. Prepare run response
                    if run_response is not None:
                        # The run is continued from a provided run_response. This contains the updated tools.
                        input = run_response.messages or []

                    elif run_id is not None:
                        # The run is continued from a run_id. This requires the updated tools or requirements to be passed.
                        if updated_tools is None and requirements is None:
                            raise ValueError(
                                "Either updated tools or requirements are required to continue a run from a run_id."
                            )

                        runs = agent_session.runs
                        run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
                        if run_response is None:
                            raise RuntimeError(f"No runs found for run ID {run_id}")

                        input = run_response.messages or []

                        # If we have updated_tools, set them in the run_response
                        if updated_tools is not None:
                            run_response.tools = updated_tools

                        # If we have requirements, get the updated tools and set them in the run_response
                        elif requirements is not None:
                            run_response.requirements = requirements
                            updated_tools = [
                                req.tool_execution for req in requirements if req.tool_execution is not None
                            ]
                            if updated_tools and run_response.tools:
                                updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
                                run_response.tools = [
                                    updated_tools_map.get(tool.tool_call_id, tool) for tool in run_response.tools
                                ]
                            else:
                                run_response.tools = updated_tools
                    else:
                        raise ValueError("Either run_response or run_id must be provided.")

                    run_response = cast(RunOutput, run_response)
                    run_response.status = RunStatus.running

                    # 5. Determine tools for model
                    self.model = cast(Model, self.model)
                    processed_tools = await self.aget_tools(
                        run_response=run_response,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                    )

                    _tools = self._determine_tools_for_model(
                        model=self.model,
                        processed_tools=processed_tools,
                        run_response=run_response,
                        run_context=run_context,
                        session=agent_session,
                        async_mode=True,
                    )

                    # 6. Prepare run messages
                    run_messages: RunMessages = self._get_continue_run_messages(
                        input=input,
                    )

                    # Register run for cancellation tracking
                    register_run(run_response.run_id)  # type: ignore

                    # Start the Run by yielding a RunContinued event
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_run_continued_event(run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )

                    # 7. Handle the updated tools
                    async for event in self._ahandle_tool_call_updates_stream(
                        run_response=run_response, run_messages=run_messages, tools=_tools, stream_events=stream_events
                    ):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event

                    # 8. Process model response
                    if self.output_model is None:
                        async for event in self._ahandle_model_response_stream(
                            session=agent_session,
                            run_response=run_response,
                            run_messages=run_messages,
                            tools=_tools,
                            response_format=response_format,
                            stream_events=stream_events,
                            run_context=run_context,
                        ):
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                            yield event
                    else:
                        from agno.run.agent import (
                            IntermediateRunContentEvent,
                            RunContentEvent,
                        )  # type: ignore

                        async for event in self._ahandle_model_response_stream(
                            session=agent_session,
                            run_response=run_response,
                            run_messages=run_messages,
                            tools=_tools,
                            response_format=response_format,
                            stream_events=stream_events,
                            run_context=run_context,
                        ):
                            raise_if_cancelled(run_response.run_id)  # type: ignore
                            if isinstance(event, RunContentEvent):
                                if stream_events:
                                    yield IntermediateRunContentEvent(
                                        content=event.content,
                                        content_type=event.content_type,
                                    )
                            else:
                                yield event

                        # If an output model is provided, generate output using the output model
                        async for event in self._agenerate_response_with_output_model_stream(
                            session=agent_session,
                            run_response=run_response,
                            run_messages=run_messages,
                            stream_events=stream_events,
                        ):
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                            yield event  # type: ignore

                    # Check for cancellation after model processing
                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # Parse response with parser model if provided
                    async for event in self._aparse_response_with_parser_model_stream(
                        session=agent_session,
                        run_response=run_response,
                        stream_events=stream_events,
                        run_context=run_context,
                    ):
                        yield event  # type: ignore

                    # Yield RunContentCompletedEvent
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_run_content_completed_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,  # type: ignore
                            store_events=self.store_events,
                        )

                    # Break out of the run function if a tool call is paused
                    if any(tool_call.is_paused for tool_call in run_response.tools or []):
                        async for item in self._ahandle_agent_run_paused_stream(
                            run_response=run_response, session=agent_session, user_id=user_id
                        ):
                            yield item
                        return

                    # 8. Execute post-hooks
                    if self.post_hooks is not None:
                        async for event in self._aexecute_post_hooks(
                            hooks=self.post_hooks,  # type: ignore
                            run_output=run_response,
                            run_context=run_context,
                            session=agent_session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            stream_events=stream_events,
                            background_tasks=background_tasks,
                            **kwargs,
                        ):
                            yield event

                    # Check for cancellation before model call
                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 9. Create session summary
                    if self.session_summary_manager is not None and self.enable_session_summaries:
                        # Upsert the RunOutput to Agent Session before creating the session summary
                        agent_session.upsert_run(run=run_response)

                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_session_summary_started_event(from_run_response=run_response),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )
                        try:
                            await self.session_summary_manager.acreate_session_summary(session=agent_session)
                        except Exception as e:
                            log_warning(f"Error in session summary creation: {str(e)}")
                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_session_summary_completed_event(
                                    from_run_response=run_response, session_summary=agent_session.summary
                                ),
                                run_response,
                                events_to_skip=self.events_to_skip,  # type: ignore
                                store_events=self.store_events,
                            )

                    # Update run_response.session_state before creating RunCompletedEvent
                    # This ensures the event has the final state after all tool modifications
                    if agent_session.session_data is not None and "session_state" in agent_session.session_data:
                        run_response.session_state = agent_session.session_data["session_state"]

                    # Create the run completed event
                    completed_event = handle_event(
                        create_run_completed_event(run_response),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                    # Set the run status to completed
                    run_response.status = RunStatus.completed

                    # 10. Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response, session=agent_session, run_context=run_context, user_id=user_id
                    )

                    if stream_events:
                        yield completed_event  # type: ignore

                    if yield_run_output:
                        yield run_response

                    # Log Agent Telemetry
                    await self._alog_agent_telemetry(session_id=agent_session.session_id, run_id=run_response.run_id)

                    log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                    break
                except RunCancelledException as e:
                    run_response = cast(RunOutput, run_response)
                    # Handle run cancellation during streaming
                    log_info(f"Run {run_response.run_id} was cancelled during streaming")
                    run_response.status = RunStatus.cancelled
                    # Don't overwrite content - preserve any partial content that was streamed
                    # Only set content if it's empty
                    if not run_response.content:
                        run_response.content = str(e)

                    # Yield the cancellation event
                    yield handle_event(  # type: ignore
                        create_run_cancelled_event(from_run_response=run_response, reason=str(e)),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )
                    break

                except (InputCheckError, OutputCheckError) as e:
                    run_response = cast(RunOutput, run_response)
                    # Handle exceptions during async streaming
                    run_response.status = RunStatus.error
                    # Add error event to list of events
                    run_error = create_run_error_event(
                        run_response,
                        error=str(e),
                        error_id=e.error_id,
                        error_type=e.type,
                        additional_data=e.additional_data,
                    )
                    run_response.events = add_error_event(error=run_error, events=run_response.events)

                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                    # Yield the error event
                    yield run_error
                    break
                except KeyboardInterrupt:
                    run_response = cast(RunOutput, run_response)
                    yield handle_event(  # type: ignore
                        create_run_cancelled_event(
                            from_run_response=run_response, reason="Operation cancelled by user"
                        ),
                        run_response,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                    )
                    break

                except Exception as e:
                    run_response = cast(RunOutput, run_response)
                    # Check if this is the last attempt
                    if attempt < num_attempts - 1:
                        # Calculate delay with exponential backoff if enabled
                        if self.exponential_backoff:
                            delay = self.delay_between_retries * (2**attempt)
                        else:
                            delay = self.delay_between_retries

                        log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                        time.sleep(delay)
                        continue

                    # Handle exceptions during async streaming
                    run_response.status = RunStatus.error
                    # Add error event to list of events
                    run_error = create_run_error_event(run_response, error=str(e))
                    run_response.events = add_error_event(error=run_error, events=run_response.events)

                    # If the content is None, set it to the error message
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Error in Agent run: {str(e)}")

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                    # Yield the error event
                    yield run_error
        finally:
            # Always disconnect connectable tools
            self._disconnect_connectable_tools()
            # Always disconnect MCP tools
            await self._disconnect_mcp_tools()

            # Always clean up the run tracking
            await acleanup_run(run_response.run_id)  # type: ignore
