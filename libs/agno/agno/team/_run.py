"""Run lifecycle and sync/async execution trait for Team."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Type,
    Union,
    cast,
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
from agno.run.agent import RunOutput, RunOutputEvent
from agno.run.cancel import (
    acancel_run as acancel_run_global,
)
from agno.run.cancel import (
    acleanup_run,
    araise_if_cancelled,
    aregister_run,
    cleanup_run,
    raise_if_cancelled,
    register_run,
)
from agno.run.cancel import (
    cancel_run as cancel_run_global,
)
from agno.run.messages import RunMessages
from agno.run.team import (
    TeamRunInput,
    TeamRunOutput,
    TeamRunOutputEvent,
)
from agno.session import TeamSession
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

if TYPE_CHECKING:
    from agno.team.team import Team


def cancel_run(run_id: str) -> bool:
    """Cancel a running team execution.

    Args:
        run_id (str): The run_id to cancel.

    Returns:
        bool: True if the run was found and marked for cancellation, False otherwise.
    """
    return cancel_run_global(run_id)


async def acancel_run(run_id: str) -> bool:
    """Cancel a running team execution.

    Args:
        run_id (str): The run_id to cancel.

    Returns:
        bool: True if the run was found and marked for cancellation, False otherwise.
    """
    return await acancel_run_global(run_id)


async def _asetup_session(
    team: "Team",
    run_context: RunContext,
    session_id: str,
    user_id: Optional[str],
    run_id: Optional[str],
) -> TeamSession:
    """Read/create session, load state from DB, and resolve callable dependencies.

    Shared setup for _arun() and _arun_stream(). Mirrors what the sync
    run_dispatch() does inline before calling _run()/_run_stream().
    """
    # Read or create session
    from agno.team._init import _has_async_db, _initialize_session_state
    from agno.team._storage import (
        _aread_or_create_session,
        _load_session_state,
        _read_or_create_session,
        _update_metadata,
    )

    if _has_async_db(team):
        team_session = await _aread_or_create_session(team, session_id=session_id, user_id=user_id)
    else:
        team_session = _read_or_create_session(team, session_id=session_id, user_id=user_id)

    # Update metadata
    _update_metadata(team, session=team_session)

    # Initialize and load session state from DB
    run_context.session_state = _initialize_session_state(
        team,
        session_state=run_context.session_state if run_context.session_state is not None else {},
        user_id=user_id,
        session_id=session_id,
        run_id=run_id,
    )
    if run_context.session_state is not None:
        run_context.session_state = _load_session_state(
            team, session=team_session, session_state=run_context.session_state
        )

    # Resolve callable dependencies AFTER state is loaded
    if run_context.dependencies is not None:
        await _aresolve_run_dependencies(team, run_context=run_context)

    return team_session


def _run(
    team: "Team",
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
    from agno.team._hooks import _execute_post_hooks, _execute_pre_hooks
    from agno.team._init import _disconnect_connectable_tools
    from agno.team._managers import _start_memory_future
    from agno.team._messages import _get_run_messages
    from agno.team._response import (
        _convert_response_to_structured_format,
        _update_run_response,
        handle_reasoning,
        parse_response_with_output_model,
        parse_response_with_parser_model,
    )
    from agno.team._telemetry import log_team_telemetry
    from agno.team._tools import _determine_tools_for_model

    log_debug(f"Team Run Start: {run_response.run_id}", center=True)

    memory_future = None
    try:
        # Set up retry logic
        num_attempts = team.retries + 1
        for attempt in range(num_attempts):
            if attempt > 0:
                log_debug(f"Retrying Team run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            try:
                # 1. Execute pre-hooks
                run_input = cast(TeamRunInput, run_response.input)
                team.model = cast(Model, team.model)
                if team.pre_hooks is not None:
                    # Can modify the run input
                    pre_hook_iterator = _execute_pre_hooks(
                        team,
                        hooks=team.pre_hooks,  # type: ignore
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

                _tools = _determine_tools_for_model(
                    team,
                    model=team.model,
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
                run_messages: RunMessages = _get_run_messages(
                    team,
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
                memory_future = _start_memory_future(
                    team,
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_future=memory_future,
                )

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 5. Reason about the task if reasoning is enabled
                handle_reasoning(team, run_response=run_response, run_messages=run_messages, run_context=run_context)

                # Check for cancellation before model call
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 6. Get the model response for the team leader
                team.model = cast(Model, team.model)
                model_response: ModelResponse = team.model.response(
                    messages=run_messages.messages,
                    response_format=response_format,
                    tools=_tools,
                    tool_choice=team.tool_choice,
                    tool_call_limit=team.tool_call_limit,
                    run_response=run_response,
                    send_media_to_model=team.send_media_to_model,
                    compression_manager=team.compression_manager if team.compress_tool_results else None,
                )

                # Check for cancellation after model call
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # If an output model is provided, generate output using the output model
                parse_response_with_output_model(team, model_response, run_messages)

                # If a parser model is provided, structure the response separately
                parse_response_with_parser_model(team, model_response, run_messages, run_context=run_context)

                # 7. Update TeamRunOutput with the model response
                _update_run_response(
                    team,
                    model_response=model_response,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                )

                # 8. Store media if enabled
                if team.store_media:
                    store_media_util(run_response, model_response)

                # 9. Convert response to structured format
                _convert_response_to_structured_format(team, run_response=run_response, run_context=run_context)

                # 10. Execute post-hooks after output is generated but before response is returned
                if team.post_hooks is not None:
                    iterator = _execute_post_hooks(
                        team,
                        hooks=team.post_hooks,  # type: ignore
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
                if team.session_summary_manager is not None:
                    # Upsert the RunOutput to Team Session before creating the session summary
                    session.upsert_run(run_response=run_response)
                    try:
                        team.session_summary_manager.create_session_summary(session=session)
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 13. Cleanup and store the run response
                _cleanup_and_store(team, run_response=run_response, session=session)

                # Log Team Telemetry
                log_team_telemetry(team, session_id=session.session_id, run_id=run_response.run_id)

                log_debug(f"Team Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response
            except RunCancelledException as e:
                # Handle run cancellation during streaming
                log_info(f"Team run {run_response.run_id} was cancelled during streaming")
                run_response.status = RunStatus.cancelled
                run_response.content = str(e)

                # Cleanup and store the run response and session
                _cleanup_and_store(team, run_response=run_response, session=session)

                return run_response
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

                log_error(f"Validation failed: {str(e)} | Check: {e.check_trigger}")

                _cleanup_and_store(team, run_response=run_response, session=session)

                return run_response
            except KeyboardInterrupt:
                run_response = cast(TeamRunOutput, run_response)
                run_response.status = RunStatus.cancelled
                run_response.content = "Operation cancelled by user"
                try:
                    _cleanup_and_store(team, run_response=run_response, session=session)
                except Exception:
                    pass
                return run_response
            except Exception as e:
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                run_error = create_team_run_error_event(run_response, error=str(e))
                run_response.events = add_team_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Team run: {str(e)}")

                # Cleanup and store the run response and session
                _cleanup_and_store(team, run_response=run_response, session=session)

                return run_response
    finally:
        # Cancel background futures on error (wait_for_open_threads handles waiting on success)
        if memory_future is not None and not memory_future.done():
            memory_future.cancel()
            try:
                memory_future.result(timeout=0)
            except Exception:
                pass

        # Always disconnect connectable tools
        _disconnect_connectable_tools(team)
        # Always clean up the run tracking
        cleanup_run(run_response.run_id)  # type: ignore
    return run_response  # Defensive fallback for type-checker; all paths return inside the loop


def _run_stream(
    team: "Team",
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
    from agno.team._hooks import _execute_post_hooks, _execute_pre_hooks
    from agno.team._init import _disconnect_connectable_tools
    from agno.team._managers import _start_memory_future
    from agno.team._messages import _get_run_messages
    from agno.team._response import (
        _handle_model_response_stream,
        generate_response_with_output_model_stream,
        handle_reasoning_stream,
        parse_response_with_parser_model_stream,
    )
    from agno.team._telemetry import log_team_telemetry
    from agno.team._tools import _determine_tools_for_model

    log_debug(f"Team Run Start: {run_response.run_id}", center=True)

    memory_future = None
    try:
        # Set up retry logic
        num_attempts = team.retries + 1
        for attempt in range(num_attempts):
            if attempt > 0:
                log_debug(f"Retrying Team run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            try:
                # 1. Execute pre-hooks
                run_input = cast(TeamRunInput, run_response.input)
                team.model = cast(Model, team.model)
                if team.pre_hooks is not None:
                    # Can modify the run input
                    pre_hook_iterator = _execute_pre_hooks(
                        team,
                        hooks=team.pre_hooks,  # type: ignore
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

                _tools = _determine_tools_for_model(
                    team,
                    model=team.model,
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
                run_messages: RunMessages = _get_run_messages(
                    team,
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
                memory_future = _start_memory_future(
                    team,
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_future=memory_future,
                )

                # Start the Run by yielding a RunStarted event
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_team_run_started_event(run_response),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 5. Reason about the task if reasoning is enabled
                yield from handle_reasoning_stream(
                    team,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                    stream_events=stream_events,
                )

                # Check for cancellation before model processing
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 6. Get a response from the model
                if team.output_model is None:
                    for event in _handle_model_response_stream(
                        team,
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
                    for event in _handle_model_response_stream(
                        team,
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

                    for event in generate_response_with_output_model_stream(
                        team,
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
                yield from parse_response_with_parser_model_stream(
                    team,
                    session=session,
                    run_response=run_response,
                    stream_events=stream_events,
                    run_context=run_context,
                )

                # Yield RunContentCompletedEvent
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_team_run_content_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )
                # Execute post-hooks after output is generated but before response is returned
                if team.post_hooks is not None:
                    yield from _execute_post_hooks(
                        team,
                        hooks=team.post_hooks,  # type: ignore
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
                    events_to_skip=team.events_to_skip,  # type: ignore
                    store_events=team.store_events,
                    get_memories_callback=lambda: team.get_user_memories(user_id=user_id),
                )

                raise_if_cancelled(run_response.run_id)  # type: ignore
                # 9. Create session summary
                if team.session_summary_manager is not None:
                    # Upsert the RunOutput to Team Session before creating the session summary
                    session.upsert_run(run_response=run_response)

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_team_session_summary_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=team.events_to_skip,
                            store_events=team.store_events,
                        )
                    try:
                        team.session_summary_manager.create_session_summary(session=session)
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_team_session_summary_completed_event(
                                from_run_response=run_response, session_summary=session.summary
                            ),
                            run_response,
                            events_to_skip=team.events_to_skip,
                            store_events=team.store_events,
                        )

                raise_if_cancelled(run_response.run_id)  # type: ignore
                # Create the run completed event
                completed_event = handle_event(
                    create_team_run_completed_event(
                        from_run_response=run_response,
                    ),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 10. Cleanup and store the run response
                _cleanup_and_store(team, run_response=run_response, session=session)

                if stream_events:
                    yield completed_event

                if yield_run_output:
                    yield run_response

                # Log Team Telemetry
                log_team_telemetry(team, session_id=session.session_id, run_id=run_response.run_id)

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
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )
                _cleanup_and_store(team, run_response=run_response, session=session)
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
                _cleanup_and_store(team, run_response=run_response, session=session)
                yield run_error
                break

            except KeyboardInterrupt:
                run_response = cast(TeamRunOutput, run_response)
                try:
                    _cleanup_and_store(team, run_response=run_response, session=session)
                except Exception:
                    pass
                yield handle_event(  # type: ignore
                    create_team_run_cancelled_event(
                        from_run_response=run_response, reason="Operation cancelled by user"
                    ),
                    run_response,
                    events_to_skip=team.events_to_skip,  # type: ignore
                    store_events=team.store_events,
                )
                break
            except Exception as e:
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                    time.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                run_error = create_team_run_error_event(run_response, error=str(e))
                run_response.events = add_team_error_event(error=run_error, events=run_response.events)
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Team run: {str(e)}")

                _cleanup_and_store(team, run_response=run_response, session=session)
                yield run_error
    finally:
        # Cancel background futures on error (wait_for_thread_tasks_stream handles waiting on success)
        if memory_future is not None and not memory_future.done():
            memory_future.cancel()
            try:
                memory_future.result(timeout=0)
            except Exception:
                pass

        # Always disconnect connectable tools
        _disconnect_connectable_tools(team)
        # Always clean up the run tracking
        cleanup_run(run_response.run_id)  # type: ignore


def run_dispatch(
    team: "Team",
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
    from agno.team._init import _has_async_db, _initialize_session, _initialize_session_state
    from agno.team._response import get_response_format
    from agno.team._run_options import resolve_run_options
    from agno.team._storage import _load_session_state, _read_or_create_session, _update_metadata

    if _has_async_db(team):
        raise Exception("run() is not supported with an async DB. Please use arun() instead.")

    # Set the id for the run
    run_id = run_id or str(uuid4())

    # Initialize Team
    team.initialize_team(debug_mode=debug_mode)

    if (add_history_to_context or team.add_history_to_context) and not team.db and not team.parent_team_id:
        log_warning(
            "add_history_to_context is True, but no database has been assigned to the team. History will not be added to the context."
        )

    background_tasks = kwargs.pop("background_tasks", None)
    if background_tasks is not None:
        from fastapi import BackgroundTasks

        background_tasks: BackgroundTasks = background_tasks  # type: ignore

    # Validate input against input_schema if provided
    validated_input = validate_input(input, team.input_schema)

    try:
        # Register run for cancellation tracking (after validation succeeds)
        register_run(run_id)  # type: ignore

        # Normalise hook & guardails
        if not team._hooks_normalised:
            if team.pre_hooks:
                team.pre_hooks = normalize_pre_hooks(team.pre_hooks)  # type: ignore
            if team.post_hooks:
                team.post_hooks = normalize_post_hooks(team.post_hooks)  # type: ignore
            team._hooks_normalised = True

        session_id, user_id = _initialize_session(team, session_id=session_id, user_id=user_id)

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
        team_session = _read_or_create_session(team, session_id=session_id, user_id=user_id)
        _update_metadata(team, session=team_session)

        # Resolve run options AFTER _update_metadata so session-stored metadata is visible
        opts = resolve_run_options(
            team,
            stream=stream,
            stream_events=stream_events,
            yield_run_output=yield_run_output,
            add_history_to_context=add_history_to_context,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            dependencies=dependencies,
            knowledge_filters=knowledge_filters,
            metadata=metadata,
            output_schema=output_schema,
        )

        # Initialize session state
        session_state = _initialize_session_state(
            team,
            session_state=session_state if session_state is not None else {},
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
        )
        # Update session state from DB
        session_state = _load_session_state(team, session=team_session, session_state=session_state)

        # Track which options were explicitly provided for run_context precedence
        dependencies_provided = dependencies is not None
        knowledge_filters_provided = knowledge_filters is not None
        metadata_provided = metadata is not None

        team.model = cast(Model, team.model)

        # Initialize run context
        run_context = run_context or RunContext(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            session_state=session_state,
            dependencies=opts.dependencies,
            knowledge_filters=opts.knowledge_filters,
            metadata=opts.metadata,
            output_schema=opts.output_schema,
        )
        # Apply options with precedence: explicit args > existing run_context > resolved defaults.
        opts.apply_to_context(
            run_context,
            dependencies_provided=dependencies_provided,
            knowledge_filters_provided=knowledge_filters_provided,
            metadata_provided=metadata_provided,
        )

        # Resolve callable dependencies once before retry loop
        if run_context.dependencies is not None:
            _resolve_run_dependencies(team, run_context=run_context)

        # Configure the model for runs
        response_format: Optional[Union[Dict, Type[BaseModel]]] = (
            get_response_format(team, run_context=run_context) if team.parser_model is None else None
        )

        # Create a new run_response for this attempt
        run_response = TeamRunOutput(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            team_id=team.id,
            team_name=team.name,
            metadata=run_context.metadata,
            session_state=run_context.session_state,
            input=run_input,
        )

        run_response.model = team.model.id if team.model is not None else None
        run_response.model_provider = team.model.provider if team.model is not None else None

        # Start the run metrics timer, to calculate the run duration
        run_response.metrics = Metrics()
        run_response.metrics.start_timer()
    except Exception:
        cleanup_run(run_id)
        raise

    if opts.stream:
        return _run_stream(
            team,
            run_response=run_response,
            run_context=run_context,
            session=team_session,
            user_id=user_id,
            add_history_to_context=opts.add_history_to_context,
            add_dependencies_to_context=opts.add_dependencies_to_context,
            add_session_state_to_context=opts.add_session_state_to_context,
            response_format=response_format,
            stream_events=opts.stream_events,
            yield_run_output=opts.yield_run_output,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )  # type: ignore

    else:
        return _run(
            team,
            run_response=run_response,
            run_context=run_context,
            session=team_session,
            user_id=user_id,
            add_history_to_context=opts.add_history_to_context,
            add_dependencies_to_context=opts.add_dependencies_to_context,
            add_session_state_to_context=opts.add_session_state_to_context,
            response_format=response_format,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )


async def _arun(
    team: "Team",
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

    Pre-loop setup:
    1. Setup session via _asetup_session (read/create, load state, resolve dependencies)

    Steps (inside retry loop):
    1. Execute pre-hooks
    2. Determine tools for model
    3. Prepare run messages
    4. Start memory creation in background task
    5. Reason about the task if reasoning is enabled
    6. Get a response from the Model
    7. Update TeamRunOutput with the model response
    8. Store media if enabled
    9. Convert response to structured format
    10. Execute post-hooks
    11. Wait for background memory creation
    12. Create session summary
    13. Cleanup and store (scrub, add to session, calculate metrics, save session)
    """
    from agno.team._hooks import _aexecute_post_hooks, _aexecute_pre_hooks
    from agno.team._init import _disconnect_connectable_tools, _disconnect_mcp_tools
    from agno.team._managers import _astart_memory_task
    from agno.team._messages import _aget_run_messages
    from agno.team._response import (
        _convert_response_to_structured_format,
        _update_run_response,
        agenerate_response_with_output_model,
        ahandle_reasoning,
        aparse_response_with_parser_model,
    )
    from agno.team._telemetry import alog_team_telemetry
    from agno.team._tools import _check_and_refresh_mcp_tools, _determine_tools_for_model

    log_debug(f"Team Run Start: {run_response.run_id}", center=True)
    memory_task = None

    try:
        # Register run for cancellation tracking
        await aregister_run(run_context.run_id)

        # Setup session: read/create, load state, resolve dependencies
        team_session = await _asetup_session(
            team=team,
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            run_id=run_response.run_id,
        )

        # Set up retry logic
        num_attempts = team.retries + 1
        for attempt in range(num_attempts):
            if attempt > 0:
                log_debug(f"Retrying Team run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            try:
                run_input = cast(TeamRunInput, run_response.input)

                # 1. Execute pre-hooks after session is loaded but before processing starts
                if team.pre_hooks is not None:
                    pre_hook_iterator = _aexecute_pre_hooks(
                        team,
                        hooks=team.pre_hooks,  # type: ignore
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

                # 2. Determine tools for model
                team_run_context: Dict[str, Any] = {}
                team.model = cast(Model, team.model)
                await _check_and_refresh_mcp_tools(
                    team,
                )
                _tools = _determine_tools_for_model(
                    team,
                    model=team.model,
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

                # 3. Prepare run messages
                run_messages = await _aget_run_messages(
                    team,
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

                team.model = cast(Model, team.model)

                # 4. Start memory creation in background task
                memory_task = await _astart_memory_task(
                    team,
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_task=memory_task,
                )

                await araise_if_cancelled(run_response.run_id)  # type: ignore
                # 5. Reason about the task if reasoning is enabled
                await ahandle_reasoning(
                    team, run_response=run_response, run_messages=run_messages, run_context=run_context
                )

                # Check for cancellation before model call
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 6. Get the model response for the team leader
                model_response = await team.model.aresponse(
                    messages=run_messages.messages,
                    tools=_tools,
                    tool_choice=team.tool_choice,
                    tool_call_limit=team.tool_call_limit,
                    response_format=response_format,
                    send_media_to_model=team.send_media_to_model,
                    run_response=run_response,
                    compression_manager=team.compression_manager if team.compress_tool_results else None,
                )  # type: ignore

                # Check for cancellation after model call
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # If an output model is provided, generate output using the output model
                await agenerate_response_with_output_model(
                    team, model_response=model_response, run_messages=run_messages
                )

                # If a parser model is provided, structure the response separately
                await aparse_response_with_parser_model(
                    team, model_response=model_response, run_messages=run_messages, run_context=run_context
                )

                # 7. Update TeamRunOutput with the model response
                _update_run_response(
                    team,
                    model_response=model_response,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                )

                # 8. Store media if enabled
                if team.store_media:
                    store_media_util(run_response, model_response)

                # 9. Convert response to structured format
                _convert_response_to_structured_format(team, run_response=run_response, run_context=run_context)

                # 10. Execute post-hooks after output is generated but before response is returned
                if team.post_hooks is not None:
                    async for _ in _aexecute_post_hooks(
                        team,
                        hooks=team.post_hooks,  # type: ignore
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

                # 11. Wait for background memory creation
                await await_for_open_threads(memory_task=memory_task)

                await araise_if_cancelled(run_response.run_id)  # type: ignore
                # 12. Create session summary
                if team.session_summary_manager is not None:
                    # Upsert the RunOutput to Team Session before creating the session summary
                    team_session.upsert_run(run_response=run_response)
                    try:
                        await team.session_summary_manager.acreate_session_summary(session=team_session)
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                await araise_if_cancelled(run_response.run_id)  # type: ignore
                run_response.status = RunStatus.completed

                # 13. Cleanup and store the run response and session
                await _acleanup_and_store(team, run_response=run_response, session=team_session)

                # Log Team Telemetry
                await alog_team_telemetry(team, session_id=team_session.session_id, run_id=run_response.run_id)

                log_debug(f"Team Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response

            except RunCancelledException as e:
                # Handle run cancellation
                log_info(f"Run {run_response.run_id} was cancelled")
                run_response.content = str(e)
                run_response.status = RunStatus.cancelled

                # Cleanup and store the run response and session
                await _acleanup_and_store(team, run_response=run_response, session=team_session)

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

                await _acleanup_and_store(team, run_response=run_response, session=team_session)

                return run_response

            except (KeyboardInterrupt, asyncio.CancelledError):
                run_response = cast(TeamRunOutput, run_response)
                run_response.status = RunStatus.cancelled
                run_response.content = "Operation cancelled by user"
                try:
                    await _acleanup_and_store(team, run_response=run_response, session=team_session)
                except Exception:
                    pass
                return run_response

            except Exception as e:
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries

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
                await _acleanup_and_store(team, run_response=run_response, session=team_session)

                return run_response
    finally:
        # Always disconnect connectable tools
        _disconnect_connectable_tools(team)
        await _disconnect_mcp_tools(team)

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
    team: "Team",
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
    """Run the Team and return the response as a stream.

    Pre-loop setup:
    1. Setup session via _asetup_session (read/create, load state, resolve dependencies)

    Steps (inside retry loop):
    1. Execute pre-hooks
    2. Determine tools for model
    3. Prepare run messages
    4. Start memory creation in background task
    5. Reason about the task if reasoning is enabled
    6. Get a response from the model
    7. Parse response with parser model if provided
    8. Wait for background memory creation
    9. Create session summary
    10. Cleanup and store (scrub, add to session, calculate metrics, save session)
    """
    from agno.team._hooks import _aexecute_post_hooks, _aexecute_pre_hooks
    from agno.team._init import _disconnect_connectable_tools, _disconnect_mcp_tools
    from agno.team._managers import _astart_memory_task
    from agno.team._messages import _aget_run_messages
    from agno.team._response import (
        _ahandle_model_response_stream,
        agenerate_response_with_output_model_stream,
        ahandle_reasoning_stream,
        aparse_response_with_parser_model_stream,
    )
    from agno.team._telemetry import alog_team_telemetry
    from agno.team._tools import _check_and_refresh_mcp_tools, _determine_tools_for_model

    log_debug(f"Team Run Start: {run_response.run_id}", center=True)

    memory_task = None

    try:
        # Register run for cancellation tracking
        await aregister_run(run_context.run_id)

        # Setup session: read/create, load state, resolve dependencies
        team_session = await _asetup_session(
            team=team,
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            run_id=run_response.run_id,
        )

        # Set up retry logic
        num_attempts = team.retries + 1
        for attempt in range(num_attempts):
            if attempt > 0:
                log_debug(f"Retrying Team run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            try:
                # 1. Execute pre-hooks
                run_input = cast(TeamRunInput, run_response.input)
                team.model = cast(Model, team.model)
                if team.pre_hooks is not None:
                    pre_hook_iterator = _aexecute_pre_hooks(
                        team,
                        hooks=team.pre_hooks,  # type: ignore
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

                # 2. Determine tools for model
                team_run_context: Dict[str, Any] = {}
                team.model = cast(Model, team.model)
                await _check_and_refresh_mcp_tools(
                    team,
                )
                _tools = _determine_tools_for_model(
                    team,
                    model=team.model,
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

                # 3. Prepare run messages
                run_messages = await _aget_run_messages(
                    team,
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

                # 4. Start memory creation in background task
                memory_task = await _astart_memory_task(
                    team,
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_task=memory_task,
                )

                # Yield the run started event
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_team_run_started_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )

                # 5. Reason about the task if reasoning is enabled
                async for item in ahandle_reasoning_stream(
                    team,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                    stream_events=stream_events,
                ):
                    await araise_if_cancelled(run_response.run_id)  # type: ignore
                    yield item

                # Check for cancellation before model processing
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 6. Get a response from the model
                if team.output_model is None:
                    async for event in _ahandle_model_response_stream(
                        team,
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
                    async for event in _ahandle_model_response_stream(
                        team,
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

                    async for event in agenerate_response_with_output_model_stream(
                        team,
                        session=team_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        stream_events=stream_events,
                    ):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event

                # Check for cancellation after model processing
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 7. Parse response with parser model if provided
                async for event in aparse_response_with_parser_model_stream(
                    team,
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
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )

                # Execute post-hooks after output is generated but before response is returned
                if team.post_hooks is not None:
                    async for event in _aexecute_post_hooks(
                        team,
                        hooks=team.post_hooks,  # type: ignore
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
                # 8. Wait for background memory creation
                async for event in await_for_thread_tasks_stream(
                    run_response=run_response,
                    memory_task=memory_task,
                    stream_events=stream_events,
                    events_to_skip=team.events_to_skip,  # type: ignore
                    store_events=team.store_events,
                    get_memories_callback=lambda: team.aget_user_memories(user_id=user_id),
                ):
                    yield event

                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 9. Create session summary
                if team.session_summary_manager is not None:
                    # Upsert the RunOutput to Team Session before creating the session summary
                    team_session.upsert_run(run_response=run_response)

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_team_session_summary_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=team.events_to_skip,
                            store_events=team.store_events,
                        )
                    try:
                        await team.session_summary_manager.acreate_session_summary(session=team_session)
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_team_session_summary_completed_event(
                                from_run_response=run_response, session_summary=team_session.summary
                            ),
                            run_response,
                            events_to_skip=team.events_to_skip,
                            store_events=team.store_events,
                        )

                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # Create the run completed event
                completed_event = handle_event(
                    create_team_run_completed_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 10. Cleanup and store the run response and session
                await _acleanup_and_store(team, run_response=run_response, session=team_session)

                if stream_events:
                    yield completed_event

                if yield_run_output:
                    yield run_response

                # Log Team Telemetry
                await alog_team_telemetry(team, session_id=team_session.session_id, run_id=run_response.run_id)

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
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

                # Cleanup and store the run response and session
                await _acleanup_and_store(team, run_response=run_response, session=team_session)
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

                await _acleanup_and_store(team, run_response=run_response, session=team_session)

                yield run_error

                break

            except (KeyboardInterrupt, asyncio.CancelledError):
                run_response = cast(TeamRunOutput, run_response)
                try:
                    await _acleanup_and_store(team, run_response=run_response, session=team_session)
                except Exception:
                    pass
                yield handle_event(  # type: ignore
                    create_team_run_cancelled_event(
                        from_run_response=run_response, reason="Operation cancelled by user"
                    ),
                    run_response,
                    events_to_skip=team.events_to_skip,  # type: ignore
                    store_events=team.store_events,
                )
                break

            except Exception as e:
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries

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
                await _acleanup_and_store(team, run_response=run_response, session=team_session)

                yield run_error

    finally:
        # Always disconnect connectable tools
        _disconnect_connectable_tools(team)
        await _disconnect_mcp_tools(team)

        # Cancel background task on error (await_for_thread_tasks_stream handles waiting on success)
        if memory_task is not None and not memory_task.done():
            memory_task.cancel()
            try:
                await memory_task
            except asyncio.CancelledError:
                pass

        # Always clean up the run tracking
        await acleanup_run(run_response.run_id)  # type: ignore


def arun_dispatch(  # type: ignore
    team: "Team",
    input: Union[str, List, Dict, Message, BaseModel, List[Message]],
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
    from agno.team._init import _initialize_session
    from agno.team._response import get_response_format
    from agno.team._run_options import resolve_run_options

    run_id = run_id or str(uuid4())

    # Initialize Team
    team.initialize_team(debug_mode=debug_mode)

    # Resolve run options centrally
    opts = resolve_run_options(
        team,
        stream=stream,
        stream_events=stream_events,
        yield_run_output=yield_run_output,
        add_history_to_context=add_history_to_context,
        add_dependencies_to_context=add_dependencies_to_context,
        add_session_state_to_context=add_session_state_to_context,
        dependencies=dependencies,
        knowledge_filters=knowledge_filters,
        metadata=metadata,
        output_schema=output_schema,
    )

    if (opts.add_history_to_context) and not team.db and not team.parent_team_id:
        log_warning(
            "add_history_to_context is True, but no database has been assigned to the team. History will not be added to the context."
        )

    background_tasks = kwargs.pop("background_tasks", None)
    if background_tasks is not None:
        from fastapi import BackgroundTasks

        background_tasks: BackgroundTasks = background_tasks  # type: ignore

    # Validate input against input_schema if provided
    validated_input = validate_input(input, team.input_schema)

    # Normalise hook & guardails
    if not team._hooks_normalised:
        if team.pre_hooks:
            team.pre_hooks = normalize_pre_hooks(team.pre_hooks, async_mode=True)  # type: ignore
        if team.post_hooks:
            team.post_hooks = normalize_post_hooks(team.post_hooks, async_mode=True)  # type: ignore
        team._hooks_normalised = True

    session_id, user_id = _initialize_session(team, session_id=session_id, user_id=user_id)

    image_artifacts, video_artifacts, audio_artifacts, file_artifacts = validate_media_object_id(
        images=images, videos=videos, audios=audio, files=files
    )

    # Track which options were explicitly provided for run_context precedence
    dependencies_provided = dependencies is not None
    knowledge_filters_provided = knowledge_filters is not None
    metadata_provided = metadata is not None

    # Create RunInput to capture the original user input
    run_input = TeamRunInput(
        input_content=validated_input,
        images=image_artifacts,
        videos=video_artifacts,
        audios=audio_artifacts,
        files=file_artifacts,
    )

    team.model = cast(Model, team.model)

    # Initialize run context
    run_context = run_context or RunContext(
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        session_state=session_state,
        dependencies=opts.dependencies,
        knowledge_filters=opts.knowledge_filters,
        metadata=opts.metadata,
        output_schema=opts.output_schema,
    )
    # Apply options with precedence: explicit args > existing run_context > resolved defaults.
    opts.apply_to_context(
        run_context,
        dependencies_provided=dependencies_provided,
        knowledge_filters_provided=knowledge_filters_provided,
        metadata_provided=metadata_provided,
    )

    # Configure the model for runs
    response_format: Optional[Union[Dict, Type[BaseModel]]] = (
        get_response_format(team, run_context=run_context) if team.parser_model is None else None
    )

    # Create a new run_response for this attempt
    run_response = TeamRunOutput(
        run_id=run_id,
        user_id=user_id,
        session_id=session_id,
        team_id=team.id,
        team_name=team.name,
        metadata=run_context.metadata,
        session_state=run_context.session_state,
        input=run_input,
    )

    run_response.model = team.model.id if team.model is not None else None
    run_response.model_provider = team.model.provider if team.model is not None else None

    # Start the run metrics timer, to calculate the run duration
    run_response.metrics = Metrics()
    run_response.metrics.start_timer()

    if opts.stream:
        return _arun_stream(
            team,  # type: ignore
            run_response=run_response,
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            add_history_to_context=opts.add_history_to_context,
            add_dependencies_to_context=opts.add_dependencies_to_context,
            add_session_state_to_context=opts.add_session_state_to_context,
            response_format=response_format,
            stream_events=opts.stream_events,
            yield_run_output=opts.yield_run_output,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )
    else:
        return _arun(
            team,  # type: ignore
            run_response=run_response,
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            add_history_to_context=opts.add_history_to_context,
            add_dependencies_to_context=opts.add_dependencies_to_context,
            add_session_state_to_context=opts.add_session_state_to_context,
            response_format=response_format,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )


def _update_team_media(team: "Team", run_response: Union[TeamRunOutput, RunOutput]) -> None:
    """Update the team state with the run response."""
    if run_response.images is not None:
        if team.images is None:
            team.images = []
        team.images.extend(run_response.images)
    if run_response.videos is not None:
        if team.videos is None:
            team.videos = []
        team.videos.extend(run_response.videos)
    if run_response.audio is not None:
        if team.audio is None:
            team.audio = []
        team.audio.extend(run_response.audio)


# ---------------------------------------------------------------------------
# Post-run cleanup (moved from _storage.py)
# ---------------------------------------------------------------------------


def _cleanup_and_store(team: "Team", run_response: TeamRunOutput, session: TeamSession) -> None:
    #  Scrub the stored run based on storage flags
    from agno.team._session import update_session_metrics

    scrub_run_output_for_storage(team, run_response)

    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Add RunOutput to Team Session
    session.upsert_run(run_response=run_response)

    # Calculate session metrics
    update_session_metrics(team, session=session, run_response=run_response)

    # Save session to memory
    team.save_session(session=session)


async def _acleanup_and_store(team: "Team", run_response: TeamRunOutput, session: TeamSession) -> None:
    #  Scrub the stored run based on storage flags
    from agno.team._session import update_session_metrics

    scrub_run_output_for_storage(team, run_response)

    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Add RunOutput to Team Session
    session.upsert_run(run_response=run_response)

    # Calculate session metrics
    update_session_metrics(team, session=session, run_response=run_response)

    # Save session to memory
    await team.asave_session(session=session)


def scrub_run_output_for_storage(team: "Team", run_response: TeamRunOutput) -> bool:
    """
    Scrub run output based on storage flags before persisting to database.
    Returns True if any scrubbing was done, False otherwise.
    """
    from agno.utils.agent import (
        scrub_history_messages_from_run_output,
        scrub_media_from_run_output,
        scrub_tool_results_from_run_output,
    )

    scrubbed = False

    if not team.store_media:
        scrub_media_from_run_output(run_response)
        scrubbed = True

    if not team.store_tool_messages:
        scrub_tool_results_from_run_output(run_response)
        scrubbed = True

    if not team.store_history_messages:
        scrub_history_messages_from_run_output(run_response)
        scrubbed = True

    return scrubbed


def _scrub_member_responses(team: "Team", member_responses: List[Union[TeamRunOutput, RunOutput]]) -> None:
    """
    Scrub member responses based on each member's storage flags.
    This is called when saving the team session to ensure member data is scrubbed per member settings.
    Recursively handles nested team's member responses.
    """
    from agno.team._tools import _find_member_by_id
    from agno.team.team import Team

    for member_response in member_responses:
        member_id = None
        if isinstance(member_response, RunOutput):
            member_id = member_response.agent_id
        elif isinstance(member_response, TeamRunOutput):
            member_id = member_response.team_id

        if not member_id:
            log_info("Skipping member response with no ID")
            continue

        member_result = _find_member_by_id(team, member_id)
        if not member_result:
            log_debug(f"Could not find member with ID: {member_id}")
            continue

        _, member = member_result

        if not member.store_media or not member.store_tool_messages or not member.store_history_messages:
            from agno.agent._run import scrub_run_output_for_storage

            scrub_run_output_for_storage(member, run_response=member_response)  # type: ignore[arg-type]

        # If this is a nested team, recursively scrub its member responses
        if isinstance(member, Team) and isinstance(member_response, TeamRunOutput) and member_response.member_responses:
            member._scrub_member_responses(member_response.member_responses)  # type: ignore


# ---------------------------------------------------------------------------
# Run dependency resolution (moved from _tools.py)
# ---------------------------------------------------------------------------


def _resolve_run_dependencies(team: "Team", run_context: RunContext) -> None:
    from inspect import signature

    log_debug("Resolving dependencies")
    if not isinstance(run_context.dependencies, dict):
        log_warning("Dependencies is not a dict")
        return

    for key, value in run_context.dependencies.items():
        if not callable(value):
            run_context.dependencies[key] = value
            continue

        try:
            sig = signature(value)

            # Build kwargs for the function
            kwargs: Dict[str, Any] = {}
            if "agent" in sig.parameters:
                kwargs["agent"] = team
            if "team" in sig.parameters:
                kwargs["team"] = team
            if "run_context" in sig.parameters:
                kwargs["run_context"] = run_context

            resolved_value = value(**kwargs) if kwargs else value()

            run_context.dependencies[key] = resolved_value
        except Exception as e:
            log_warning(f"Failed to resolve dependencies for {key}: {e}")


async def _aresolve_run_dependencies(team: "Team", run_context: RunContext) -> None:
    from inspect import iscoroutine, signature

    log_debug("Resolving context (async)")
    if not isinstance(run_context.dependencies, dict):
        log_warning("Dependencies is not a dict")
        return

    for key, value in run_context.dependencies.items():
        if not callable(value):
            run_context.dependencies[key] = value
            continue

        try:
            sig = signature(value)

            # Build kwargs for the function
            kwargs: Dict[str, Any] = {}
            if "agent" in sig.parameters:
                kwargs["agent"] = team
            if "team" in sig.parameters:
                kwargs["team"] = team
            if "run_context" in sig.parameters:
                kwargs["run_context"] = run_context

            resolved_value = value(**kwargs) if kwargs else value()

            if iscoroutine(resolved_value):
                resolved_value = await resolved_value

            run_context.dependencies[key] = resolved_value
        except Exception as e:
            log_warning(f"Failed to resolve context for '{key}': {e}")
