"""Run lifecycle and sync/async execution trait for Team."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Sequence,
    Type,
    Union,
    cast,
    overload,
)
from uuid import uuid4

from pydantic import BaseModel

from agno.exceptions import (
    InputCheckError,
    OutputCheckError,
    RunCancelledException,
)
from agno.filters import FilterExpr
from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
from agno.models.response import ModelResponse
from agno.run import RunContext, RunStatus
from agno.run.agent import RunOutputEvent
from agno.run.cancel import (
    acleanup_run,
    araise_if_cancelled,
    aregister_run,
    cleanup_run,
    raise_if_cancelled,
    register_run,
)
from agno.run.messages import RunMessages
from agno.run.team import (
    TeamRunInput,
    TeamRunOutput,
    TeamRunOutputEvent,
)
from agno.session import TeamSession
from agno.team.trait.base import TeamTraitBase
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
    add_team_error_event,
    create_team_run_cancelled_event,
    create_team_run_completed_event,
    create_team_run_content_completed_event,
    create_team_run_error_event,
    create_team_run_started_event,
    create_team_session_summary_completed_event,
    create_team_session_summary_started_event,
    handle_event,
)
from agno.utils.hooks import (
    normalize_post_hooks,
    normalize_pre_hooks,
)
from agno.utils.log import (
    log_debug,
    log_error,
    log_info,
    log_warning,
)
from agno.utils.merge_dict import merge_dictionaries


class TeamRunTrait(TeamTraitBase):
    def _run(
        self,
        run_response: TeamRunOutput,
        session: TeamSession,
        run_context: RunContext,
        user_id: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> TeamRunOutput:
        """Run the Team and return the response.
        Steps:
        1. Execute pre-hooks
        2. Determine tools for model
        3. Prepare run messages
        4. Start memory creation in background thread
        5. Reason about the task if reasoning is enabled
        6. Get a response from the model
        7. Update TeamRunOutput with the model response
        8. Store media if enabled
        9. Convert response to structured format
        10. Execute post-hooks
        11. Wait for background memory creation
        12. Create session summary
        13. Cleanup and store (scrub, stop timer, add to session, calculate metrics, save session)
        """
        log_debug(f"Team Run Start: {run_response.run_id}", center=True)

        memory_future = None
        try:
            # Set up retry logic
            num_attempts = self.retries + 1
            for attempt in range(num_attempts):
                try:
                    # 1. Execute pre-hooks
                    run_input = cast(TeamRunInput, run_response.input)
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
                    # Initialize team run context
                    team_run_context: Dict[str, Any] = {}
                    # Note: MCP tool refresh is async-only by design (_check_and_refresh_mcp_tools
                    # is called in _arun/_arun_stream). Sync paths do not support MCP tools.

                    _tools = self._determine_tools_for_model(
                        model=self.model,
                        run_response=run_response,
                        run_context=run_context,
                        team_run_context=team_run_context,
                        session=session,
                        user_id=user_id,
                        async_mode=False,
                        input_message=run_input.input_content,
                        images=run_input.images,
                        videos=run_input.videos,
                        audio=run_input.audios,
                        files=run_input.files,
                        debug_mode=debug_mode,
                        add_history_to_context=add_history_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                        add_dependencies_to_context=add_dependencies_to_context,
                        stream=False,
                        stream_events=False,
                    )

                    # 3. Prepare run messages
                    run_messages: RunMessages = self._get_run_messages(
                        run_response=run_response,
                        session=session,
                        run_context=run_context,
                        user_id=user_id,
                        input_message=run_input.input_content,
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

                    # 4. Start memory creation in background thread
                    memory_future = self._start_memory_future(
                        run_messages=run_messages,
                        user_id=user_id,
                        existing_future=None,
                    )

                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 5. Reason about the task if reasoning is enabled
                    self._handle_reasoning(
                        run_response=run_response, run_messages=run_messages, run_context=run_context
                    )

                    # Check for cancellation before model call
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 6. Get the model response for the team leader
                    self.model = cast(Model, self.model)
                    model_response: ModelResponse = self.model.response(
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
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # If an output model is provided, generate output using the output model
                    self._parse_response_with_output_model(model_response, run_messages)

                    # If a parser model is provided, structure the response separately
                    self._parse_response_with_parser_model(model_response, run_messages, run_context=run_context)

                    # 7. Update TeamRunOutput with the model response
                    self._update_run_response(
                        model_response=model_response,
                        run_response=run_response,
                        run_messages=run_messages,
                        run_context=run_context,
                    )

                    # 8. Store media if enabled
                    if self.store_media:
                        store_media_util(run_response, model_response)

                    # 9. Convert response to structured format
                    self._convert_response_to_structured_format(run_response=run_response, run_context=run_context)

                    # 10. Execute post-hooks after output is generated but before response is returned
                    if self.post_hooks is not None:
                        iterator = self._execute_post_hooks(
                            hooks=self.post_hooks,  # type: ignore
                            run_output=run_response,
                            run_context=run_context,
                            session=session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            background_tasks=background_tasks,
                            **kwargs,
                        )
                        deque(iterator, maxlen=0)
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 11. Wait for background memory creation
                    wait_for_open_threads(memory_future=memory_future)  # type: ignore

                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 12. Create session summary
                    if self.session_summary_manager is not None:
                        # Upsert the RunOutput to Team Session before creating the session summary
                        session.upsert_run(run_response=run_response)
                        try:
                            self.session_summary_manager.create_session_summary(session=session)
                        except Exception as e:
                            log_warning(f"Error in session summary creation: {str(e)}")

                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # Set the run status to completed
                    run_response.status = RunStatus.completed

                    # 13. Cleanup and store the run response
                    self._cleanup_and_store(run_response=run_response, session=session)

                    # Log Team Telemetry
                    self._log_team_telemetry(session_id=session.session_id, run_id=run_response.run_id)

                    log_debug(f"Team Run End: {run_response.run_id}", center=True, symbol="*")

                    return run_response
                except RunCancelledException as e:
                    # Handle run cancellation during streaming
                    log_info(f"Team run {run_response.run_id} was cancelled during streaming")
                    run_response.status = RunStatus.cancelled
                    run_response.content = str(e)

                    # Cleanup and store the run response and session
                    self._cleanup_and_store(run_response=run_response, session=session)

                    return run_response
                except (InputCheckError, OutputCheckError) as e:
                    run_response.status = RunStatus.error

                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Validation failed: {str(e)} | Check: {e.check_trigger}")

                    self._cleanup_and_store(run_response=run_response, session=session)

                    return run_response
                except KeyboardInterrupt:
                    run_response = cast(TeamRunOutput, run_response)
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

                    log_error(f"Error in Team run: {str(e)}")

                    # Cleanup and store the run response and session
                    self._cleanup_and_store(run_response=run_response, session=session)

                    return run_response
        finally:
            # Cancel background futures on error (wait_for_open_threads handles waiting on success)
            if memory_future is not None and not memory_future.done():
                memory_future.cancel()

            # Always disconnect connectable tools
            self._disconnect_connectable_tools()
            # Always clean up the run tracking
            cleanup_run(run_response.run_id)  # type: ignore
        return run_response  # Defensive fallback for type-checker; all paths return inside the loop

    def _run_stream(
        self,
        run_response: TeamRunOutput,
        run_context: RunContext,
        session: TeamSession,
        user_id: Optional[str] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        stream_events: bool = False,
        yield_run_output: bool = False,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> Iterator[Union[TeamRunOutputEvent, RunOutputEvent, TeamRunOutput]]:
        """Run the Team and return the response iterator.
        Steps:
        1. Execute pre-hooks
        2. Determine tools for model
        3. Prepare run messages
        4. Start memory creation in background thread
        5. Reason about the task if reasoning is enabled
        6. Get a response from the model
        7. Parse response with parser model if provided
        8. Wait for background memory creation
        9. Create session summary
        10. Cleanup and store (scrub, add to session, calculate metrics, save session)
        """
        log_debug(f"Team Run Start: {run_response.run_id}", center=True)

        memory_future = None
        try:
            # Set up retry logic
            num_attempts = self.retries + 1
            for attempt in range(num_attempts):
                if num_attempts > 1:
                    log_debug(f"Retrying Team run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

                try:
                    # 1. Execute pre-hooks
                    run_input = cast(TeamRunInput, run_response.input)
                    self.model = cast(Model, self.model)
                    if self.pre_hooks is not None:
                        # Can modify the run input
                        pre_hook_iterator = self._execute_pre_hooks(
                            hooks=self.pre_hooks,  # type: ignore
                            run_response=run_response,
                            run_context=run_context,
                            run_input=run_input,
                            session=session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            stream_events=stream_events,
                            background_tasks=background_tasks,
                            **kwargs,
                        )
                        for pre_hook_event in pre_hook_iterator:
                            yield pre_hook_event

                    # 2. Determine tools for model
                    # Initialize team run context
                    team_run_context: Dict[str, Any] = {}
                    # Note: MCP tool refresh is async-only by design (_check_and_refresh_mcp_tools
                    # is called in _arun/_arun_stream). Sync paths do not support MCP tools.

                    _tools = self._determine_tools_for_model(
                        model=self.model,
                        run_response=run_response,
                        run_context=run_context,
                        team_run_context=team_run_context,
                        session=session,
                        user_id=user_id,
                        async_mode=False,
                        input_message=run_input.input_content,
                        images=run_input.images,
                        videos=run_input.videos,
                        audio=run_input.audios,
                        files=run_input.files,
                        debug_mode=debug_mode,
                        add_history_to_context=add_history_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                        add_dependencies_to_context=add_dependencies_to_context,
                        stream=True,
                        stream_events=stream_events,
                    )

                    # 3. Prepare run messages
                    run_messages: RunMessages = self._get_run_messages(
                        run_response=run_response,
                        run_context=run_context,
                        session=session,
                        user_id=user_id,
                        input_message=run_input.input_content,
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

                    # 4. Start memory creation in background thread
                    memory_future = self._start_memory_future(
                        run_messages=run_messages,
                        user_id=user_id,
                        existing_future=None,
                    )

                    # Start the Run by yielding a RunStarted event
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_team_run_started_event(run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,
                            store_events=self.store_events,
                        )

                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 5. Reason about the task if reasoning is enabled
                    yield from self._handle_reasoning_stream(
                        run_response=run_response,
                        run_messages=run_messages,
                        run_context=run_context,
                        stream_events=stream_events,
                    )

                    # Check for cancellation before model processing
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 6. Get a response from the model
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
                            from agno.run.team import IntermediateRunContentEvent, RunContentEvent

                            if isinstance(event, RunContentEvent):
                                if stream_events:
                                    yield IntermediateRunContentEvent(
                                        content=event.content,
                                        content_type=event.content_type,
                                    )
                            else:
                                yield event

                        for event in self._generate_response_with_output_model_stream(
                            session=session,
                            run_response=run_response,
                            run_messages=run_messages,
                            stream_events=stream_events,
                        ):
                            raise_if_cancelled(run_response.run_id)  # type: ignore
                            yield event

                    # Check for cancellation after model processing
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 7. Parse response with parser model if provided
                    yield from self._parse_response_with_parser_model_stream(
                        session=session, run_response=run_response, stream_events=stream_events, run_context=run_context
                    )

                    # Yield RunContentCompletedEvent
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_team_run_content_completed_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,
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
                    raise_if_cancelled(run_response.run_id)  # type: ignore

                    # 8. Wait for background memory creation
                    yield from wait_for_thread_tasks_stream(
                        run_response=run_response,
                        memory_future=memory_future,  # type: ignore
                        stream_events=stream_events,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                        get_memories_callback=lambda: self.get_user_memories(user_id=user_id),
                    )

                    raise_if_cancelled(run_response.run_id)  # type: ignore
                    # 9. Create session summary
                    if self.session_summary_manager is not None:
                        # Upsert the RunOutput to Team Session before creating the session summary
                        session.upsert_run(run_response=run_response)

                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_team_session_summary_started_event(from_run_response=run_response),
                                run_response,
                                events_to_skip=self.events_to_skip,
                                store_events=self.store_events,
                            )
                        try:
                            self.session_summary_manager.create_session_summary(session=session)
                        except Exception as e:
                            log_warning(f"Error in session summary creation: {str(e)}")
                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_team_session_summary_completed_event(
                                    from_run_response=run_response, session_summary=session.summary
                                ),
                                run_response,
                                events_to_skip=self.events_to_skip,
                                store_events=self.store_events,
                            )

                    raise_if_cancelled(run_response.run_id)  # type: ignore
                    # Create the run completed event
                    completed_event = handle_event(
                        create_team_run_completed_event(
                            from_run_response=run_response,
                        ),
                        run_response,
                        events_to_skip=self.events_to_skip,
                        store_events=self.store_events,
                    )

                    # Set the run status to completed
                    run_response.status = RunStatus.completed

                    # 10. Cleanup and store the run response
                    self._cleanup_and_store(run_response=run_response, session=session)

                    if stream_events:
                        yield completed_event

                    if yield_run_output:
                        yield run_response

                    # Log Team Telemetry
                    self._log_team_telemetry(session_id=session.session_id, run_id=run_response.run_id)

                    log_debug(f"Team Run End: {run_response.run_id}", center=True, symbol="*")

                    break
                except RunCancelledException as e:
                    # Handle run cancellation during streaming
                    log_info(f"Team run {run_response.run_id} was cancelled during streaming")
                    run_response.status = RunStatus.cancelled
                    run_response.content = str(e)

                    # Yield the cancellation event
                    yield handle_event(
                        create_team_run_cancelled_event(from_run_response=run_response, reason=str(e)),
                        run_response,
                        events_to_skip=self.events_to_skip,
                        store_events=self.store_events,
                    )
                    self._cleanup_and_store(run_response=run_response, session=session)
                    break
                except (InputCheckError, OutputCheckError) as e:
                    run_response.status = RunStatus.error

                    # Add error event to list of events
                    run_error = create_team_run_error_event(
                        run_response,
                        error=str(e),
                        error_id=e.error_id,
                        error_type=e.type,
                        additional_data=e.additional_data,
                    )
                    run_response.events = add_team_error_event(error=run_error, events=run_response.events)

                    if run_response.content is None:
                        run_response.content = str(e)
                    self._cleanup_and_store(run_response=run_response, session=session)
                    yield run_error
                    break

                except KeyboardInterrupt:
                    run_response = cast(TeamRunOutput, run_response)
                    yield handle_event(  # type: ignore
                        create_team_run_cancelled_event(
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
                    run_error = create_team_run_error_event(run_response, error=str(e))
                    run_response.events = add_team_error_event(error=run_error, events=run_response.events)
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Error in Team run: {str(e)}")

                    self._cleanup_and_store(run_response=run_response, session=session)
                    yield run_error
        finally:
            # Cancel background futures on error (wait_for_thread_tasks_stream handles waiting on success)
            if memory_future is not None and not memory_future.done():
                memory_future.cancel()

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
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
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
        debug_mode: Optional[bool] = None,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> TeamRunOutput: ...

    @overload
    def run(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Literal[True] = True,
        stream_events: Optional[bool] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
        user_id: Optional[str] = None,
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
        debug_mode: Optional[bool] = None,
        yield_run_output: bool = False,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent]]: ...

    def run(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Optional[bool] = None,
        stream_events: Optional[bool] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
        run_id: Optional[str] = None,
        user_id: Optional[str] = None,
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
        debug_mode: Optional[bool] = None,
        yield_run_output: bool = False,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Union[TeamRunOutput, Iterator[Union[RunOutputEvent, TeamRunOutputEvent]]]:
        """Run the Team and return the response."""
        if self._has_async_db():
            raise Exception("run() is not supported with an async DB. Please use arun() instead.")

        # Set the id for the run
        run_id = run_id or str(uuid4())

        # Initialize Team
        self.initialize_team(debug_mode=debug_mode)

        if (add_history_to_context or self.add_history_to_context) and not self.db and not self.parent_team_id:
            log_warning(
                "add_history_to_context is True, but no database has been assigned to the team. History will not be added to the context."
            )

        # Register run for cancellation tracking
        register_run(run_id)  # type: ignore

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

        image_artifacts, video_artifacts, audio_artifacts, file_artifacts = validate_media_object_id(
            images=images, videos=videos, audios=audio, files=files
        )

        # Create RunInput to capture the original user input
        run_input = TeamRunInput(
            input_content=validated_input,
            images=image_artifacts,
            videos=video_artifacts,
            audios=audio_artifacts,
            files=file_artifacts,
        )

        # Read existing session from database
        team_session = self._read_or_create_session(session_id=session_id, user_id=user_id)
        self._update_metadata(session=team_session)

        # Initialize session state
        session_state = self._initialize_session_state(
            session_state=session_state if session_state is not None else {},
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
        )
        # Update session state from DB
        session_state = self._load_session_state(session=team_session, session_state=session_state)

        # Determine runtime dependencies
        dependencies = dependencies if dependencies is not None else self.dependencies

        # Determine runtime context parameters
        add_dependencies = (
            add_dependencies_to_context if add_dependencies_to_context is not None else self.add_dependencies_to_context
        )
        add_session_state = (
            add_session_state_to_context
            if add_session_state_to_context is not None
            else self.add_session_state_to_context
        )
        add_history = add_history_to_context if add_history_to_context is not None else self.add_history_to_context

        # Use stream override value when necessary
        if stream is None:
            stream = False if self.stream is None else self.stream

        # Can't stream events if streaming is disabled
        if stream is False:
            stream_events = False

        if stream_events is None:
            stream_events = False if self.stream_events is None else self.stream_events

        self.model = cast(Model, self.model)

        if self.metadata is not None:
            if metadata is None:
                metadata = self.metadata
            else:
                merge_dictionaries(metadata, self.metadata)

        #  Get knowledge filters
        effective_filters = knowledge_filters
        if self.knowledge_filters or knowledge_filters:
            effective_filters = self._get_effective_filters(knowledge_filters)

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
            knowledge_filters=effective_filters,
            metadata=metadata,
            output_schema=output_schema,
        )
        # output_schema parameter takes priority, even if run_context was provided
        run_context.output_schema = output_schema

        # Resolve callable dependencies once before retry loop
        if run_context.dependencies is not None:
            self._resolve_run_dependencies(run_context=run_context)

        # Configure the model for runs
        response_format: Optional[Union[Dict, Type[BaseModel]]] = (
            self._get_response_format(run_context=run_context) if self.parser_model is None else None
        )

        # Create a new run_response for this attempt
        run_response = TeamRunOutput(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            team_id=self.id,
            team_name=self.name,
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
            return self._run_stream(
                run_response=run_response,
                run_context=run_context,
                session=team_session,
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
            )  # type: ignore

        else:
            return self._run(
                run_response=run_response,
                run_context=run_context,
                session=team_session,
                user_id=user_id,
                add_history_to_context=add_history,
                add_dependencies_to_context=add_dependencies,
                add_session_state_to_context=add_session_state,
                response_format=response_format,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )

    async def _arun(
        self,
        run_response: TeamRunOutput,
        run_context: RunContext,
        session_id: str,
        user_id: Optional[str] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        add_history_to_context: Optional[bool] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> TeamRunOutput:
        """Run the Team and return the response.

        Steps:
        1. Read or create session
        2. Update metadata and session state
        3. Resolve callable dependencies
        4. Execute pre-hooks
        5. Determine tools for model
        6. Prepare run messages
        7. Start memory creation in background task
        8. Reason about the task if reasoning is enabled
        9. Get a response from the Model
        10. Update TeamRunOutput with the model response
        11. Store media if enabled
        12. Convert response to structured format
        13. Execute post-hooks
        14. Wait for background memory creation
        15. Create session summary
        16. Cleanup and store (scrub, add to session, calculate metrics, save session)
        """
        await aregister_run(run_context.run_id)
        log_debug(f"Team Run Start: {run_response.run_id}", center=True)
        memory_task = None

        try:
            # Read or create session once before retry loop
            if self._has_async_db():
                team_session = await self._aread_or_create_session(session_id=session_id, user_id=user_id)
            else:
                team_session = self._read_or_create_session(session_id=session_id, user_id=user_id)

            # Update metadata and session state
            self._update_metadata(session=team_session)
            run_context.session_state = self._initialize_session_state(
                session_state=run_context.session_state if run_context.session_state is not None else {},
                user_id=user_id,
                session_id=session_id,
                run_id=run_response.run_id,
            )
            if run_context.session_state is not None:
                run_context.session_state = self._load_session_state(
                    session=team_session, session_state=run_context.session_state
                )

            # Resolve callable dependencies after session state is loaded (matches sync run() order)
            if run_context.dependencies is not None:
                await self._aresolve_run_dependencies(run_context=run_context)

            # Set up retry logic
            num_attempts = self.retries + 1
            for attempt in range(num_attempts):
                if num_attempts > 1:
                    log_debug(f"Retrying Team run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

                try:
                    run_input = cast(TeamRunInput, run_response.input)

                    # 1. Execute pre-hooks after session is loaded but before processing starts
                    if self.pre_hooks is not None:
                        pre_hook_iterator = self._aexecute_pre_hooks(
                            hooks=self.pre_hooks,  # type: ignore
                            run_response=run_response,
                            run_context=run_context,
                            run_input=run_input,
                            session=team_session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            background_tasks=background_tasks,
                            **kwargs,
                        )

                        # Consume the async iterator without yielding
                        async for _ in pre_hook_iterator:
                            pass

                    # 4. Determine tools for model
                    team_run_context: Dict[str, Any] = {}
                    self.model = cast(Model, self.model)
                    await self._check_and_refresh_mcp_tools()
                    _tools = self._determine_tools_for_model(
                        model=self.model,
                        run_response=run_response,
                        run_context=run_context,
                        team_run_context=team_run_context,
                        session=team_session,
                        user_id=user_id,
                        async_mode=True,
                        input_message=run_input.input_content,
                        images=run_input.images,
                        videos=run_input.videos,
                        audio=run_input.audios,
                        files=run_input.files,
                        debug_mode=debug_mode,
                        add_history_to_context=add_history_to_context,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                        stream=False,
                        stream_events=False,
                    )

                    # 5. Prepare run messages
                    run_messages = await self._aget_run_messages(
                        run_response=run_response,
                        run_context=run_context,
                        session=team_session,  # type: ignore
                        user_id=user_id,
                        input_message=run_input.input_content,
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

                    self.model = cast(Model, self.model)

                    # 6. Start memory creation in background task
                    memory_task = await self._astart_memory_task(
                        run_messages=run_messages,
                        user_id=user_id,
                        existing_task=memory_task,
                    )

                    await araise_if_cancelled(run_response.run_id)  # type: ignore
                    # 7. Reason about the task if reasoning is enabled
                    await self._ahandle_reasoning(
                        run_response=run_response, run_messages=run_messages, run_context=run_context
                    )

                    # Check for cancellation before model call
                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 8. Get the model response for the team leader
                    model_response = await self.model.aresponse(
                        messages=run_messages.messages,
                        tools=_tools,
                        tool_choice=self.tool_choice,
                        tool_call_limit=self.tool_call_limit,
                        response_format=response_format,
                        send_media_to_model=self.send_media_to_model,
                        run_response=run_response,
                        compression_manager=self.compression_manager if self.compress_tool_results else None,
                    )  # type: ignore

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

                    # 9. Update TeamRunOutput with the model response
                    self._update_run_response(
                        model_response=model_response,
                        run_response=run_response,
                        run_messages=run_messages,
                        run_context=run_context,
                    )

                    # 10. Store media if enabled
                    if self.store_media:
                        store_media_util(run_response, model_response)

                    # 11. Convert response to structured format
                    self._convert_response_to_structured_format(run_response=run_response, run_context=run_context)

                    # 12. Execute post-hooks after output is generated but before response is returned
                    if self.post_hooks is not None:
                        async for _ in self._aexecute_post_hooks(
                            hooks=self.post_hooks,  # type: ignore
                            run_output=run_response,
                            run_context=run_context,
                            session=team_session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            background_tasks=background_tasks,
                            **kwargs,
                        ):
                            pass

                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 13. Wait for background memory creation
                    await await_for_open_threads(memory_task=memory_task)

                    await araise_if_cancelled(run_response.run_id)  # type: ignore
                    # 14. Create session summary
                    if self.session_summary_manager is not None:
                        # Upsert the RunOutput to Team Session before creating the session summary
                        team_session.upsert_run(run_response=run_response)
                        try:
                            await self.session_summary_manager.acreate_session_summary(session=team_session)
                        except Exception as e:
                            log_warning(f"Error in session summary creation: {str(e)}")

                    await araise_if_cancelled(run_response.run_id)  # type: ignore
                    run_response.status = RunStatus.completed

                    # 15. Cleanup and store the run response and session
                    await self._acleanup_and_store(run_response=run_response, session=team_session)

                    # Log Team Telemetry
                    await self._alog_team_telemetry(session_id=team_session.session_id, run_id=run_response.run_id)

                    log_debug(f"Team Run End: {run_response.run_id}", center=True, symbol="*")

                    return run_response

                except RunCancelledException as e:
                    # Handle run cancellation
                    log_info(f"Run {run_response.run_id} was cancelled")
                    run_response.content = str(e)
                    run_response.status = RunStatus.cancelled

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(run_response=run_response, session=team_session)

                    return run_response

                except (InputCheckError, OutputCheckError) as e:
                    run_response.status = RunStatus.error
                    run_error = create_team_run_error_event(
                        run_response,
                        error=str(e),
                        error_id=e.error_id,
                        error_type=e.type,
                        additional_data=e.additional_data,
                    )
                    run_response.events = add_team_error_event(error=run_error, events=run_response.events)
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Validation failed: {str(e)} | Check: {e.check_trigger}")

                    await self._acleanup_and_store(run_response=run_response, session=team_session)

                    return run_response

                except Exception as e:
                    if attempt < num_attempts - 1:
                        # Calculate delay with exponential backoff if enabled
                        if self.exponential_backoff:
                            delay = self.delay_between_retries * (2**attempt)
                        else:
                            delay = self.delay_between_retries

                        log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                        await asyncio.sleep(delay)
                        continue

                    run_response.status = RunStatus.error
                    run_error = create_team_run_error_event(run_response, error=str(e))
                    run_response.events = add_team_error_event(error=run_error, events=run_response.events)

                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Error in Team run: {str(e)}")

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(run_response=run_response, session=team_session)

                    return run_response
        finally:
            # Always disconnect connectable tools
            self._disconnect_connectable_tools()
            await self._disconnect_mcp_tools()

            # Cancel background task on error (await_for_open_threads handles waiting on success)
            if memory_task is not None and not memory_task.done():
                memory_task.cancel()
                try:
                    await memory_task
                except asyncio.CancelledError:
                    pass

            # Always clean up the run tracking
            await acleanup_run(run_response.run_id)  # type: ignore

        return run_response

    async def _arun_stream(
        self,
        run_response: TeamRunOutput,
        run_context: RunContext,
        session_id: str,
        user_id: Optional[str] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        stream_events: bool = False,
        yield_run_output: bool = False,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        add_history_to_context: Optional[bool] = None,
        debug_mode: Optional[bool] = None,
        background_tasks: Optional[Any] = None,
        **kwargs: Any,
    ) -> AsyncIterator[Union[TeamRunOutputEvent, RunOutputEvent, TeamRunOutput]]:
        """Run the Team and return the response.

        Steps:
        1. Read or create session
        2. Update metadata and session state
        3. Resolve callable dependencies
        4. Execute pre-hooks
        5. Determine tools for model
        6. Prepare run messages
        7. Start memory creation in background task
        8. Reason about the task if reasoning is enabled
        9. Get a response from the model
        10. Parse response with parser model if provided
        11. Wait for background memory creation
        12. Create session summary
        13. Cleanup and store (scrub, add to session, calculate metrics, save session)
        """
        log_debug(f"Team Run Start: {run_response.run_id}", center=True)

        await aregister_run(run_context.run_id)

        memory_task = None

        try:
            # Read or create session once before retry loop
            if self._has_async_db():
                team_session = await self._aread_or_create_session(session_id=session_id, user_id=user_id)
            else:
                team_session = self._read_or_create_session(session_id=session_id, user_id=user_id)

            # Update metadata and session state
            self._update_metadata(session=team_session)
            run_context.session_state = self._initialize_session_state(
                session_state=run_context.session_state if run_context.session_state is not None else {},
                user_id=user_id,
                session_id=session_id,
                run_id=run_response.run_id,
            )
            if run_context.session_state is not None:
                run_context.session_state = self._load_session_state(
                    session=team_session, session_state=run_context.session_state
                )

            # Resolve callable dependencies after session state is loaded (matches sync run() order)
            if run_context.dependencies is not None:
                await self._aresolve_run_dependencies(run_context=run_context)

            # Set up retry logic
            num_attempts = self.retries + 1
            for attempt in range(num_attempts):
                if num_attempts > 1:
                    log_debug(f"Retrying Team run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

                try:
                    # 1. Execute pre-hooks
                    run_input = cast(TeamRunInput, run_response.input)
                    self.model = cast(Model, self.model)
                    if self.pre_hooks is not None:
                        pre_hook_iterator = self._aexecute_pre_hooks(
                            hooks=self.pre_hooks,  # type: ignore
                            run_response=run_response,
                            run_context=run_context,
                            run_input=run_input,
                            session=team_session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            stream_events=stream_events,
                            background_tasks=background_tasks,
                            **kwargs,
                        )
                        async for pre_hook_event in pre_hook_iterator:
                            yield pre_hook_event

                    # 5. Determine tools for model
                    team_run_context: Dict[str, Any] = {}
                    self.model = cast(Model, self.model)
                    await self._check_and_refresh_mcp_tools()
                    _tools = self._determine_tools_for_model(
                        model=self.model,
                        run_response=run_response,
                        run_context=run_context,
                        team_run_context=team_run_context,
                        session=team_session,  # type: ignore
                        user_id=user_id,
                        async_mode=True,
                        input_message=run_input.input_content,
                        images=run_input.images,
                        videos=run_input.videos,
                        audio=run_input.audios,
                        files=run_input.files,
                        debug_mode=debug_mode,
                        add_history_to_context=add_history_to_context,
                        add_dependencies_to_context=add_dependencies_to_context,
                        add_session_state_to_context=add_session_state_to_context,
                        stream=True,
                        stream_events=stream_events,
                    )

                    # 6. Prepare run messages
                    run_messages = await self._aget_run_messages(
                        run_response=run_response,
                        run_context=run_context,
                        session=team_session,  # type: ignore
                        user_id=user_id,
                        input_message=run_input.input_content,
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

                    # 7. Start memory creation in background task
                    memory_task = await self._astart_memory_task(
                        run_messages=run_messages,
                        user_id=user_id,
                        existing_task=memory_task,
                    )

                    # Yield the run started event
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_team_run_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,
                            store_events=self.store_events,
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

                    # Check for cancellation before model processing
                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 9. Get a response from the model
                    if self.output_model is None:
                        async for event in self._ahandle_model_response_stream(
                            session=team_session,
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
                        async for event in self._ahandle_model_response_stream(
                            session=team_session,
                            run_response=run_response,
                            run_messages=run_messages,
                            tools=_tools,
                            response_format=response_format,
                            stream_events=stream_events,
                            session_state=run_context.session_state,
                            run_context=run_context,
                        ):
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                            from agno.run.team import IntermediateRunContentEvent, RunContentEvent

                            if isinstance(event, RunContentEvent):
                                if stream_events:
                                    yield IntermediateRunContentEvent(
                                        content=event.content,
                                        content_type=event.content_type,
                                    )
                            else:
                                yield event

                        async for event in self._agenerate_response_with_output_model_stream(
                            session=team_session,
                            run_response=run_response,
                            run_messages=run_messages,
                            stream_events=stream_events,
                        ):
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                            yield event

                    # Check for cancellation after model processing
                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 10. Parse response with parser model if provided
                    async for event in self._aparse_response_with_parser_model_stream(
                        session=team_session,
                        run_response=run_response,
                        stream_events=stream_events,
                        run_context=run_context,
                    ):
                        yield event

                    # Yield RunContentCompletedEvent
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_team_run_content_completed_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=self.events_to_skip,
                            store_events=self.store_events,
                        )

                    # Execute post-hooks after output is generated but before response is returned
                    if self.post_hooks is not None:
                        async for event in self._aexecute_post_hooks(
                            hooks=self.post_hooks,  # type: ignore
                            run_output=run_response,
                            run_context=run_context,
                            session=team_session,
                            user_id=user_id,
                            debug_mode=debug_mode,
                            stream_events=stream_events,
                            background_tasks=background_tasks,
                            **kwargs,
                        ):
                            yield event

                    await araise_if_cancelled(run_response.run_id)  # type: ignore
                    # 11. Wait for background memory creation
                    async for event in await_for_thread_tasks_stream(
                        run_response=run_response,
                        memory_task=memory_task,
                        stream_events=stream_events,
                        events_to_skip=self.events_to_skip,  # type: ignore
                        store_events=self.store_events,
                        get_memories_callback=lambda: self.aget_user_memories(user_id=user_id),
                    ):
                        yield event

                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # 12. Create session summary
                    if self.session_summary_manager is not None:
                        # Upsert the RunOutput to Team Session before creating the session summary
                        team_session.upsert_run(run_response=run_response)

                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_team_session_summary_started_event(from_run_response=run_response),
                                run_response,
                                events_to_skip=self.events_to_skip,
                                store_events=self.store_events,
                            )
                        try:
                            await self.session_summary_manager.acreate_session_summary(session=team_session)
                        except Exception as e:
                            log_warning(f"Error in session summary creation: {str(e)}")
                        if stream_events:
                            yield handle_event(  # type: ignore
                                create_team_session_summary_completed_event(
                                    from_run_response=run_response, session_summary=team_session.summary
                                ),
                                run_response,
                                events_to_skip=self.events_to_skip,
                                store_events=self.store_events,
                            )

                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # Create the run completed event
                    completed_event = handle_event(
                        create_team_run_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=self.events_to_skip,
                        store_events=self.store_events,
                    )

                    # Set the run status to completed
                    run_response.status = RunStatus.completed

                    # 13. Cleanup and store the run response and session
                    await self._acleanup_and_store(run_response=run_response, session=team_session)

                    if stream_events:
                        yield completed_event

                    if yield_run_output:
                        yield run_response

                    # Log Team Telemetry
                    await self._alog_team_telemetry(session_id=team_session.session_id, run_id=run_response.run_id)

                    log_debug(f"Team Run End: {run_response.run_id}", center=True, symbol="*")
                    break
                except RunCancelledException as e:
                    # Handle run cancellation during async streaming
                    log_info(f"Team run {run_response.run_id} was cancelled during async streaming")
                    run_response.status = RunStatus.cancelled
                    run_response.content = str(e)

                    # Yield the cancellation event
                    yield handle_event(  # type: ignore
                        create_team_run_cancelled_event(from_run_response=run_response, reason=str(e)),
                        run_response,
                        events_to_skip=self.events_to_skip,
                        store_events=self.store_events,
                    )

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(run_response=run_response, session=team_session)
                    break

                except (InputCheckError, OutputCheckError) as e:
                    run_response.status = RunStatus.error
                    run_error = create_team_run_error_event(
                        run_response,
                        error=str(e),
                        error_id=e.error_id,
                        error_type=e.type,
                        additional_data=e.additional_data,
                    )
                    run_response.events = add_team_error_event(error=run_error, events=run_response.events)
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Validation failed: {str(e)} | Check: {e.check_trigger}")

                    await self._acleanup_and_store(run_response=run_response, session=team_session)

                    yield run_error

                    break

                except Exception as e:
                    if attempt < num_attempts - 1:
                        # Calculate delay with exponential backoff if enabled
                        if self.exponential_backoff:
                            delay = self.delay_between_retries * (2**attempt)
                        else:
                            delay = self.delay_between_retries

                        log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                        await asyncio.sleep(delay)
                        continue

                    run_response.status = RunStatus.error
                    run_error = create_team_run_error_event(run_response, error=str(e))
                    run_response.events = add_team_error_event(error=run_error, events=run_response.events)
                    if run_response.content is None:
                        run_response.content = str(e)

                    log_error(f"Error in Team run: {str(e)}")

                    # Cleanup and store the run response and session
                    await self._acleanup_and_store(run_response=run_response, session=team_session)

                    yield run_error

        finally:
            # Always disconnect connectable tools
            self._disconnect_connectable_tools()
            await self._disconnect_mcp_tools()

            # Cancel background task on error (await_for_thread_tasks_stream handles waiting on success)
            if memory_task is not None and not memory_task.done():
                memory_task.cancel()
                try:
                    await memory_task
                except asyncio.CancelledError:
                    pass

            # Always clean up the run tracking
            await acleanup_run(run_response.run_id)  # type: ignore

    @overload
    async def arun(
        self,
        input: Union[str, List, Dict, Message, BaseModel],
        *,
        stream: Literal[False] = False,
        stream_events: Optional[bool] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        run_context: Optional[RunContext] = None,
        user_id: Optional[str] = None,
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
        debug_mode: Optional[bool] = None,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> TeamRunOutput: ...

    @overload
    def arun(
        self,
        input: Union[str, List, Dict, Message, BaseModel],
        *,
        stream: Literal[True] = True,
        stream_events: Optional[bool] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        run_context: Optional[RunContext] = None,
        user_id: Optional[str] = None,
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
        debug_mode: Optional[bool] = None,
        yield_run_output: bool = False,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent]]: ...

    def arun(  # type: ignore
        self,
        input: Union[str, List, Dict, Message, BaseModel],
        *,
        stream: Optional[bool] = None,
        stream_events: Optional[bool] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        run_context: Optional[RunContext] = None,
        user_id: Optional[str] = None,
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
        debug_mode: Optional[bool] = None,
        yield_run_output: bool = False,
        output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Union[TeamRunOutput, AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent]]]:
        """Run the Team asynchronously and return the response."""

        # Set the id for the run and register it immediately for cancellation tracking
        run_id = run_id or str(uuid4())

        if (add_history_to_context or self.add_history_to_context) and not self.db and not self.parent_team_id:
            log_warning(
                "add_history_to_context is True, but no database has been assigned to the team. History will not be added to the context."
            )

        background_tasks = kwargs.pop("background_tasks", None)
        if background_tasks is not None:
            from fastapi import BackgroundTasks

            background_tasks: BackgroundTasks = background_tasks  # type: ignore

        # Validate input against input_schema if provided
        validated_input = validate_input(input, self.input_schema)

        # Initialize Team
        self.initialize_team(debug_mode=debug_mode)

        # Normalise hook & guardails
        if not self._hooks_normalised:
            if self.pre_hooks:
                self.pre_hooks = normalize_pre_hooks(self.pre_hooks, async_mode=True)  # type: ignore
            if self.post_hooks:
                self.post_hooks = normalize_post_hooks(self.post_hooks, async_mode=True)  # type: ignore
            self._hooks_normalised = True

        session_id, user_id = self._initialize_session(session_id=session_id, user_id=user_id)

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
        run_input = TeamRunInput(
            input_content=validated_input,
            images=image_artifacts,
            videos=video_artifacts,
            audios=audio_artifacts,
            files=file_artifacts,
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

        if self.metadata is not None:
            if metadata is None:
                metadata = self.metadata
            else:
                merge_dictionaries(metadata, self.metadata)

        #  Get knowledge filters
        effective_filters = knowledge_filters
        if self.knowledge_filters or knowledge_filters:
            effective_filters = self._get_effective_filters(knowledge_filters)

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
            knowledge_filters=effective_filters,
            metadata=metadata,
            output_schema=output_schema,
        )
        # output_schema parameter takes priority, even if run_context was provided
        run_context.output_schema = output_schema

        # Configure the model for runs
        response_format: Optional[Union[Dict, Type[BaseModel]]] = (
            self._get_response_format(run_context=run_context) if self.parser_model is None else None
        )

        # Create a new run_response for this attempt
        run_response = TeamRunOutput(
            run_id=run_id,
            user_id=user_id,
            session_id=session_id,
            team_id=self.id,
            team_name=self.name,
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
            return self._arun_stream(  # type: ignore
                run_response=run_response,
                run_context=run_context,
                session_id=session_id,
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
        else:
            return self._arun(  # type: ignore
                run_response=run_response,
                run_context=run_context,
                session_id=session_id,
                user_id=user_id,
                add_history_to_context=add_history,
                add_dependencies_to_context=add_dependencies,
                add_session_state_to_context=add_session_state,
                response_format=response_format,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )

    def _handle_event(
        self,
        event: Union[RunOutputEvent, TeamRunOutputEvent],
        run_response: TeamRunOutput,
    ):
        # We only store events that are not run_response_content events
        events_to_skip = [event.value for event in self.events_to_skip] if self.events_to_skip else []
        if self.store_events and event.event not in events_to_skip:
            if run_response.events is None:
                run_response.events = []
            run_response.events.append(event)
        return event
