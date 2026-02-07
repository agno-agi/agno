"""Run lifecycle and sync/async execution trait for Team."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from copy import deepcopy
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

if TYPE_CHECKING:
    from agno.team.team import Team


async def _asetup_session(
    team: "Team",
    run_context: RunContext,
    session_id: str,
    user_id: Optional[str],
    run_id: Optional[str],
) -> TeamSession:
    """Read/create session, load state from DB, and resolve callable dependencies.

    Shared setup for _arun() and _arun_stream(). Mirrors what the sync run()
    does inline before calling _run()/_run_stream().
    """
    # Read or create session
    if team._has_async_db():
        team_session = await team._aread_or_create_session(session_id=session_id, user_id=user_id)
    else:
        team_session = team._read_or_create_session(session_id=session_id, user_id=user_id)

    # Update metadata
    team._update_metadata(session=team_session)

    # Initialize and load session state from DB
    run_context.session_state = team._initialize_session_state(
        session_state=run_context.session_state if run_context.session_state is not None else {},
        user_id=user_id,
        session_id=session_id,
        run_id=run_id,
    )
    if run_context.session_state is not None:
        run_context.session_state = team._load_session_state(
            session=team_session, session_state=run_context.session_state
        )

    # Resolve callable dependencies AFTER state is loaded
    if run_context.dependencies is not None:
        await team._aresolve_run_dependencies(run_context=run_context)

    return team_session


def _run_tasks(
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
    """Autonomous task loop for mode=tasks. Iterates model calls until all tasks are done."""
    from agno.team.task import load_task_list, save_task_list

    log_debug(f"Team Tasks Run Start: {run_response.run_id}", center=True)

    max_iterations = team.max_iterations
    memory_future = None
    accumulated_messages: List[Message] = []

    try:
        run_input = cast(TeamRunInput, run_response.input)
        team.model = cast(Model, team.model)

        # Execute pre-hooks once at the start
        if team.pre_hooks is not None:
            pre_hook_iterator = team._execute_pre_hooks(
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
            deque(pre_hook_iterator, maxlen=0)

        for iteration in range(1, max_iterations + 1):
            log_debug(f"Tasks iteration {iteration}/{max_iterations}")

            # Initialize team run context
            team_run_context: Dict[str, Any] = {}

            # Determine tools (task management tools)
            _tools = team._determine_tools_for_model(
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

            if iteration == 1:
                # First iteration: build full messages
                run_messages: RunMessages = team._get_run_messages(
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
                accumulated_messages = list(run_messages.messages)

                # Start memory creation on first iteration
                memory_future = team._start_memory_future(
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_future=None,
                )

                # Reasoning on first iteration
                team._handle_reasoning(run_response=run_response, run_messages=run_messages, run_context=run_context)
            else:
                # Subsequent iterations: inject task state context
                task_list = load_task_list(run_context.session_state)
                task_context = task_list.get_summary_string()
                continuation_msg = Message(
                    role="user",
                    content=(
                        f"<current_task_state>\n{task_context}\n</current_task_state>\n\n"
                        "Review the current task state above. Continue working toward the goal. "
                        "Execute pending tasks, create new tasks if needed, or call mark_all_complete if done."
                    ),
                )
                accumulated_messages.append(continuation_msg)

            raise_if_cancelled(run_response.run_id)  # type: ignore

            # Call the model
            model_response: ModelResponse = team.model.response(
                messages=accumulated_messages,
                response_format=response_format,
                tools=_tools,
                tool_choice=team.tool_choice,
                tool_call_limit=team.tool_call_limit,
                run_response=run_response,
                send_media_to_model=team.send_media_to_model,
                compression_manager=team.compression_manager if team.compress_tool_results else None,
            )

            raise_if_cancelled(run_response.run_id)  # type: ignore

            # Update run response
            team._update_run_response(
                model_response=model_response,
                run_response=run_response,
                run_messages=RunMessages(messages=accumulated_messages),
                run_context=run_context,
            )

            # Persist task list to session state after model call (tools may have updated it)
            task_list = load_task_list(run_context.session_state)
            save_task_list(run_context.session_state, task_list)

            # Check HITL pause
            if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                from agno.team import _hooks

                return _hooks.handle_team_run_paused(team, run_response=run_response, session=session)

            # Accumulate model response messages for next iteration
            accumulated_messages = list(model_response.messages) if model_response.messages else accumulated_messages  # type: ignore

            # Check termination: goal marked complete or all tasks in terminal state
            if task_list.goal_complete:
                log_debug("Tasks mode: goal marked complete by leader")
                break

            if task_list.tasks and task_list.all_terminal():
                log_debug("Tasks mode: all tasks in terminal state")
                break

            raise_if_cancelled(run_response.run_id)  # type: ignore

        else:
            log_warning(f"Tasks mode reached max_iterations ({max_iterations}) without completion")

        # Post-loop: structured output, post-hooks, memory, session summary, cleanup
        team._convert_response_to_structured_format(run_response=run_response, run_context=run_context)

        if team.post_hooks is not None:
            iterator = team._execute_post_hooks(
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

        wait_for_open_threads(memory_future=memory_future)  # type: ignore

        raise_if_cancelled(run_response.run_id)  # type: ignore

        if team.session_summary_manager is not None:
            session.upsert_run(run_response=run_response)
            try:
                team.session_summary_manager.create_session_summary(session=session)
            except Exception as e:
                log_warning(f"Error in session summary creation: {str(e)}")

        raise_if_cancelled(run_response.run_id)  # type: ignore

        run_response.status = RunStatus.completed
        team._cleanup_and_store(run_response=run_response, session=session)
        team._log_team_telemetry(session_id=session.session_id, run_id=run_response.run_id)

        log_debug(f"Team Tasks Run End: {run_response.run_id}", center=True, symbol="*")

        return run_response
    except RunCancelledException as e:
        log_info(f"Team task run {run_response.run_id} was cancelled")
        run_response.status = RunStatus.cancelled
        run_response.content = str(e)
        team._cleanup_and_store(run_response=run_response, session=session)
        return run_response
    except (InputCheckError, OutputCheckError) as e:
        run_response.status = RunStatus.error
        if run_response.content is None:
            run_response.content = str(e)
        log_error(f"Validation failed: {str(e)} | Check: {e.check_trigger}")
        team._cleanup_and_store(run_response=run_response, session=session)
        return run_response
    except KeyboardInterrupt:
        run_response = cast(TeamRunOutput, run_response)
        run_response.status = RunStatus.cancelled
        run_response.content = "Operation cancelled by user"
        return run_response
    except Exception as e:
        run_response.status = RunStatus.error
        if run_response.content is None:
            run_response.content = str(e)
        log_error(f"Error in Team task run: {str(e)}")
        team._cleanup_and_store(run_response=run_response, session=session)
        return run_response
    finally:
        if memory_future is not None and not memory_future.done():
            memory_future.cancel()
        team._disconnect_connectable_tools()
        cleanup_run(run_response.run_id)  # type: ignore


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
    # Dispatch to tasks mode if enabled
    from agno.team.mode import TeamMode

    if team.mode == TeamMode.tasks:
        return _run_tasks(
            team,
            run_response=run_response,
            session=session,
            run_context=run_context,
            user_id=user_id,
            add_history_to_context=add_history_to_context,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            response_format=response_format,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )

    log_debug(f"Team Run Start: {run_response.run_id}", center=True)

    memory_future = None
    try:
        # Set up retry logic
        num_attempts = team.retries + 1
        for attempt in range(num_attempts):
            if num_attempts > 1:
                log_debug(f"Retrying Team run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            try:
                # 1. Execute pre-hooks
                run_input = cast(TeamRunInput, run_response.input)
                team.model = cast(Model, team.model)
                if team.pre_hooks is not None:
                    # Can modify the run input
                    pre_hook_iterator = team._execute_pre_hooks(
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

                _tools = team._determine_tools_for_model(
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
                run_messages: RunMessages = team._get_run_messages(
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
                memory_future = team._start_memory_future(
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_future=memory_future,
                )

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 5. Reason about the task if reasoning is enabled
                team._handle_reasoning(run_response=run_response, run_messages=run_messages, run_context=run_context)

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
                team._parse_response_with_output_model(model_response, run_messages)

                # If a parser model is provided, structure the response separately
                team._parse_response_with_parser_model(model_response, run_messages, run_context=run_context)

                # 7. Update TeamRunOutput with the model response
                team._update_run_response(
                    model_response=model_response,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                )

                # 7b. Check if delegation propagated member HITL requirements
                if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                    from agno.team import _hooks

                    return _hooks.handle_team_run_paused(team, run_response=run_response, session=session)

                # 8. Store media if enabled
                if team.store_media:
                    store_media_util(run_response, model_response)

                # 9. Convert response to structured format
                team._convert_response_to_structured_format(run_response=run_response, run_context=run_context)

                # 10. Execute post-hooks after output is generated but before response is returned
                if team.post_hooks is not None:
                    iterator = team._execute_post_hooks(
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
                team._cleanup_and_store(run_response=run_response, session=session)

                # Log Team Telemetry
                team._log_team_telemetry(session_id=session.session_id, run_id=run_response.run_id)

                log_debug(f"Team Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response
            except RunCancelledException as e:
                # Handle run cancellation during streaming
                log_info(f"Team run {run_response.run_id} was cancelled during streaming")
                run_response.status = RunStatus.cancelled
                run_response.content = str(e)

                # Cleanup and store the run response and session
                team._cleanup_and_store(run_response=run_response, session=session)

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

                team._cleanup_and_store(run_response=run_response, session=session)

                return run_response
            except KeyboardInterrupt:
                run_response = cast(TeamRunOutput, run_response)
                run_response.status = RunStatus.cancelled
                run_response.content = "Operation cancelled by user"
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
                team._cleanup_and_store(run_response=run_response, session=session)

                return run_response
    finally:
        # Cancel background futures on error (wait_for_open_threads handles waiting on success)
        if memory_future is not None and not memory_future.done():
            memory_future.cancel()

        # Always disconnect connectable tools
        team._disconnect_connectable_tools()
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
    # Tasks mode: fall back to non-streaming _run_tasks for now
    from agno.team.mode import TeamMode

    if team.mode == TeamMode.tasks:
        log_warning("Streaming is not yet supported in tasks mode; falling back to non-streaming.")
        result = _run_tasks(
            team,
            run_response=run_response,
            session=session,
            run_context=run_context,
            user_id=user_id,
            add_history_to_context=add_history_to_context,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            response_format=response_format,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )
        yield result  # type: ignore
        return

    log_debug(f"Team Run Start: {run_response.run_id}", center=True)

    memory_future = None
    try:
        # Set up retry logic
        num_attempts = team.retries + 1
        for attempt in range(num_attempts):
            if num_attempts > 1:
                log_debug(f"Retrying Team run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            try:
                # 1. Execute pre-hooks
                run_input = cast(TeamRunInput, run_response.input)
                team.model = cast(Model, team.model)
                if team.pre_hooks is not None:
                    # Can modify the run input
                    pre_hook_iterator = team._execute_pre_hooks(
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

                _tools = team._determine_tools_for_model(
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
                run_messages: RunMessages = team._get_run_messages(
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
                memory_future = team._start_memory_future(
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
                yield from team._handle_reasoning_stream(
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                    stream_events=stream_events,
                )

                # Check for cancellation before model processing
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 6. Get a response from the model
                if team.output_model is None:
                    for event in team._handle_model_response_stream(
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
                    for event in team._handle_model_response_stream(
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

                    for event in team._generate_response_with_output_model_stream(
                        session=session,
                        run_response=run_response,
                        run_messages=run_messages,
                        stream_events=stream_events,
                    ):
                        raise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event

                # Check for cancellation after model processing
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 6b. Check if delegation propagated member HITL requirements
                if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                    from agno.team import _hooks

                    yield from _hooks.handle_team_run_paused_stream(team, run_response=run_response, session=session)
                    if yield_run_output:
                        yield run_response
                    return

                # 7. Parse response with parser model if provided
                yield from team._parse_response_with_parser_model_stream(
                    session=session, run_response=run_response, stream_events=stream_events, run_context=run_context
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
                    yield from team._execute_post_hooks(
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
                team._cleanup_and_store(run_response=run_response, session=session)

                if stream_events:
                    yield completed_event

                if yield_run_output:
                    yield run_response

                # Log Team Telemetry
                team._log_team_telemetry(session_id=session.session_id, run_id=run_response.run_id)

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
                team._cleanup_and_store(run_response=run_response, session=session)
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
                team._cleanup_and_store(run_response=run_response, session=session)
                yield run_error
                break

            except KeyboardInterrupt:
                run_response = cast(TeamRunOutput, run_response)
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

                team._cleanup_and_store(run_response=run_response, session=session)
                yield run_error
    finally:
        # Cancel background futures on error (wait_for_thread_tasks_stream handles waiting on success)
        if memory_future is not None and not memory_future.done():
            memory_future.cancel()

        # Always disconnect connectable tools
        team._disconnect_connectable_tools()
        # Always clean up the run tracking
        cleanup_run(run_response.run_id)  # type: ignore


def run(
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
    if team._has_async_db():
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

        session_id, user_id = team._initialize_session(session_id=session_id, user_id=user_id)

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
        team_session = team._read_or_create_session(session_id=session_id, user_id=user_id)
        team._update_metadata(session=team_session)

        # Initialize session state
        session_state = team._initialize_session_state(
            session_state=session_state if session_state is not None else {},
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
        )
        # Update session state from DB
        session_state = team._load_session_state(session=team_session, session_state=session_state)

        dependencies_provided = dependencies is not None
        knowledge_filters_provided = knowledge_filters is not None
        metadata_provided = metadata is not None
        output_schema_provided = output_schema is not None

        # Determine runtime dependencies
        dependencies = dependencies if dependencies is not None else team.dependencies

        # Determine runtime context parameters
        add_dependencies = (
            add_dependencies_to_context if add_dependencies_to_context is not None else team.add_dependencies_to_context
        )
        add_session_state = (
            add_session_state_to_context
            if add_session_state_to_context is not None
            else team.add_session_state_to_context
        )
        add_history = add_history_to_context if add_history_to_context is not None else team.add_history_to_context

        # Use stream override value when necessary
        if stream is None:
            stream = False if team.stream is None else team.stream

        # Can't stream events if streaming is disabled
        if stream is False:
            stream_events = False

        if stream_events is None:
            stream_events = False if team.stream_events is None else team.stream_events

        team.model = cast(Model, team.model)

        if team.metadata is not None:
            if metadata is None:
                metadata = team.metadata
            else:
                merge_dictionaries(metadata, team.metadata)

        #  Get knowledge filters
        effective_filters = knowledge_filters
        if team.knowledge_filters or knowledge_filters:
            effective_filters = team._get_effective_filters(knowledge_filters)

        # Resolve output_schema parameter takes precedence, then fall back to team.output_schema
        if output_schema is None:
            output_schema = team.output_schema

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
        # Apply options with precedence: explicit args > existing run_context > resolved defaults.
        if dependencies_provided:
            run_context.dependencies = dependencies
        elif run_context.dependencies is None:
            run_context.dependencies = dependencies
        if knowledge_filters_provided:
            run_context.knowledge_filters = effective_filters
        elif run_context.knowledge_filters is None:
            run_context.knowledge_filters = effective_filters
        if metadata_provided:
            run_context.metadata = metadata
        elif run_context.metadata is None:
            run_context.metadata = metadata
        if output_schema_provided:
            run_context.output_schema = output_schema
        elif run_context.output_schema is None:
            run_context.output_schema = output_schema

        # Resolve callable dependencies once before retry loop
        if run_context.dependencies is not None:
            team._resolve_run_dependencies(run_context=run_context)

        # Configure the model for runs
        response_format: Optional[Union[Dict, Type[BaseModel]]] = (
            team._get_response_format(run_context=run_context) if team.parser_model is None else None
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

    if stream:
        return team._run_stream(
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
        return team._run(
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


async def _arun_tasks(
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
    """Async autonomous task loop for mode=tasks."""
    from agno.team.task import load_task_list, save_task_list

    await aregister_run(run_context.run_id)
    log_debug(f"Team Async Tasks Run Start: {run_response.run_id}", center=True)

    max_iterations = team.max_iterations
    memory_task = None
    accumulated_messages: List[Message] = []
    team_session = None

    try:
        # Setup session
        team_session = await _asetup_session(
            team=team,
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            run_id=run_context.run_id,
        )

        run_input = cast(TeamRunInput, run_response.input)
        team.model = cast(Model, team.model)

        # Pre-hooks
        if team.pre_hooks is not None:
            async for _ in team._aexecute_pre_hooks(
                hooks=team.pre_hooks,  # type: ignore
                run_response=run_response,
                run_input=run_input,
                run_context=run_context,
                session=team_session,
                user_id=user_id,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            ):
                pass

        # Check and refresh MCP tools
        await team._check_and_refresh_mcp_tools()

        for iteration in range(1, max_iterations + 1):
            log_debug(f"Async tasks iteration {iteration}/{max_iterations}")

            team_run_context: Dict[str, Any] = {}

            _tools = team._determine_tools_for_model(
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
                add_session_state_to_context=add_session_state_to_context,
                add_dependencies_to_context=add_dependencies_to_context,
                stream=False,
                stream_events=False,
                check_mcp_tools=False,
            )

            if iteration == 1:
                run_messages: RunMessages = await team._aget_run_messages(
                    run_response=run_response,
                    session=team_session,
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
                accumulated_messages = list(run_messages.messages)

                memory_task = await team._astart_memory_task(
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_task=None,
                )

                await team._ahandle_reasoning(
                    run_response=run_response, run_messages=run_messages, run_context=run_context
                )
            else:
                task_list = load_task_list(run_context.session_state)
                task_context = task_list.get_summary_string()
                continuation_msg = Message(
                    role="user",
                    content=(
                        f"<current_task_state>\n{task_context}\n</current_task_state>\n\n"
                        "Review the current task state above. Continue working toward the goal. "
                        "Execute pending tasks, create new tasks if needed, or call mark_all_complete if done."
                    ),
                )
                accumulated_messages.append(continuation_msg)

            await araise_if_cancelled(run_response.run_id)  # type: ignore

            model_response: ModelResponse = await team.model.aresponse(
                messages=accumulated_messages,
                response_format=response_format,
                tools=_tools,
                tool_choice=team.tool_choice,
                tool_call_limit=team.tool_call_limit,
                run_response=run_response,
                send_media_to_model=team.send_media_to_model,
                compression_manager=team.compression_manager if team.compress_tool_results else None,
            )

            await araise_if_cancelled(run_response.run_id)  # type: ignore

            team._update_run_response(
                model_response=model_response,
                run_response=run_response,
                run_messages=RunMessages(messages=accumulated_messages),
                run_context=run_context,
            )

            task_list = load_task_list(run_context.session_state)
            save_task_list(run_context.session_state, task_list)

            # Check HITL pause
            if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                from agno.team import _hooks

                return await _hooks.ahandle_team_run_paused(team, run_response=run_response, session=team_session)

            accumulated_messages = list(model_response.messages) if model_response.messages else accumulated_messages  # type: ignore

            if task_list.goal_complete:
                log_debug("Async tasks mode: goal marked complete by leader")
                break

            if task_list.tasks and task_list.all_terminal():
                log_debug("Async tasks mode: all tasks in terminal state")
                break

            await araise_if_cancelled(run_response.run_id)  # type: ignore
        else:
            log_warning(f"Async tasks mode reached max_iterations ({max_iterations}) without completion")

        # Post-loop cleanup
        team._convert_response_to_structured_format(run_response=run_response, run_context=run_context)

        if team.post_hooks is not None:
            async for _ in team._aexecute_post_hooks(
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
        await await_for_open_threads(memory_task=memory_task)  # type: ignore
        await araise_if_cancelled(run_response.run_id)  # type: ignore

        if team.session_summary_manager is not None:
            team_session.upsert_run(run_response=run_response)
            try:
                await team.session_summary_manager.acreate_session_summary(session=team_session)
            except Exception as e:
                log_warning(f"Error in session summary creation: {str(e)}")

        await araise_if_cancelled(run_response.run_id)  # type: ignore

        run_response.status = RunStatus.completed

        if team._has_async_db():
            await team._acleanup_and_store(run_response=run_response, session=team_session)
        else:
            team._cleanup_and_store(run_response=run_response, session=team_session)

        await team._alog_team_telemetry(session_id=team_session.session_id, run_id=run_response.run_id)
        log_debug(f"Team Async Tasks Run End: {run_response.run_id}", center=True, symbol="*")

        return run_response
    except RunCancelledException as e:
        log_info(f"Team async task run {run_response.run_id} was cancelled")
        run_response.status = RunStatus.cancelled
        run_response.content = str(e)
        if team._has_async_db():
            await team._acleanup_and_store(run_response=run_response, session=team_session)  # type: ignore
        else:
            team._cleanup_and_store(run_response=run_response, session=team_session)  # type: ignore
        return run_response
    except (InputCheckError, OutputCheckError) as e:
        run_response.status = RunStatus.error
        if run_response.content is None:
            run_response.content = str(e)
        log_error(f"Validation failed: {str(e)} | Check: {e.check_trigger}")
        if team._has_async_db():
            await team._acleanup_and_store(run_response=run_response, session=team_session)  # type: ignore
        else:
            team._cleanup_and_store(run_response=run_response, session=team_session)  # type: ignore
        return run_response
    except KeyboardInterrupt:
        run_response = cast(TeamRunOutput, run_response)
        run_response.status = RunStatus.cancelled
        run_response.content = "Operation cancelled by user"
        return run_response
    except Exception as e:
        run_response.status = RunStatus.error
        if run_response.content is None:
            run_response.content = str(e)
        log_error(f"Error in Team async task run: {str(e)}")
        try:
            if team._has_async_db():
                await team._acleanup_and_store(run_response=run_response, session=team_session)  # type: ignore
            else:
                team._cleanup_and_store(run_response=run_response, session=team_session)  # type: ignore
        except Exception:
            pass
        return run_response
    finally:
        # Always disconnect connectable tools
        team._disconnect_connectable_tools()
        await team._disconnect_mcp_tools()

        # Cancel background task on error (await_for_open_threads handles waiting on success)
        if memory_task is not None and not memory_task.done():  # type: ignore
            memory_task.cancel()  # type: ignore
            try:
                await memory_task  # type: ignore
            except asyncio.CancelledError:
                pass

        # Always clean up the run tracking
        await acleanup_run(run_response.run_id)  # type: ignore


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
    # Dispatch to async tasks mode if enabled
    from agno.team.mode import TeamMode

    if team.mode == TeamMode.tasks:
        return await _arun_tasks(
            team,
            run_response=run_response,
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            response_format=response_format,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            add_history_to_context=add_history_to_context,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )

    await aregister_run(run_context.run_id)
    log_debug(f"Team Run Start: {run_response.run_id}", center=True)
    memory_task = None

    try:
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
            if num_attempts > 1:
                log_debug(f"Retrying Team run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            try:
                run_input = cast(TeamRunInput, run_response.input)

                # 1. Execute pre-hooks after session is loaded but before processing starts
                if team.pre_hooks is not None:
                    pre_hook_iterator = team._aexecute_pre_hooks(
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
                await team._check_and_refresh_mcp_tools()
                _tools = team._determine_tools_for_model(
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
                run_messages = await team._aget_run_messages(
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
                memory_task = await team._astart_memory_task(
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_task=memory_task,
                )

                await araise_if_cancelled(run_response.run_id)  # type: ignore
                # 5. Reason about the task if reasoning is enabled
                await team._ahandle_reasoning(
                    run_response=run_response, run_messages=run_messages, run_context=run_context
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
                await team._agenerate_response_with_output_model(
                    model_response=model_response, run_messages=run_messages
                )

                # If a parser model is provided, structure the response separately
                await team._aparse_response_with_parser_model(
                    model_response=model_response, run_messages=run_messages, run_context=run_context
                )

                # 7. Update TeamRunOutput with the model response
                team._update_run_response(
                    model_response=model_response,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                )

                # 7b. Check if delegation propagated member HITL requirements
                if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                    from agno.team import _hooks

                    return await _hooks.ahandle_team_run_paused(team, run_response=run_response, session=team_session)

                # 8. Store media if enabled
                if team.store_media:
                    store_media_util(run_response, model_response)

                # 9. Convert response to structured format
                team._convert_response_to_structured_format(run_response=run_response, run_context=run_context)

                # 10. Execute post-hooks after output is generated but before response is returned
                if team.post_hooks is not None:
                    async for _ in team._aexecute_post_hooks(
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
                await team._acleanup_and_store(run_response=run_response, session=team_session)

                # Log Team Telemetry
                await team._alog_team_telemetry(session_id=team_session.session_id, run_id=run_response.run_id)

                log_debug(f"Team Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response

            except RunCancelledException as e:
                # Handle run cancellation
                log_info(f"Run {run_response.run_id} was cancelled")
                run_response.content = str(e)
                run_response.status = RunStatus.cancelled

                # Cleanup and store the run response and session
                await team._acleanup_and_store(run_response=run_response, session=team_session)

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

                await team._acleanup_and_store(run_response=run_response, session=team_session)

                return run_response

            except (KeyboardInterrupt, asyncio.CancelledError):
                run_response = cast(TeamRunOutput, run_response)
                run_response.status = RunStatus.cancelled
                run_response.content = "Operation cancelled by user"
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
                await team._acleanup_and_store(run_response=run_response, session=team_session)

                return run_response
    finally:
        # Always disconnect connectable tools
        team._disconnect_connectable_tools()
        await team._disconnect_mcp_tools()

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
    # Tasks mode: fall back to non-streaming async for now
    from agno.team.mode import TeamMode

    if team.mode == TeamMode.tasks:
        log_warning("Streaming is not yet supported in tasks mode; falling back to non-streaming.")
        result = await _arun_tasks(
            team,
            run_response=run_response,
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            response_format=response_format,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            add_history_to_context=add_history_to_context,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )
        yield result  # type: ignore
        return

    log_debug(f"Team Run Start: {run_response.run_id}", center=True)

    await aregister_run(run_context.run_id)

    memory_task = None

    try:
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
            if num_attempts > 1:
                log_debug(f"Retrying Team run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            try:
                # 1. Execute pre-hooks
                run_input = cast(TeamRunInput, run_response.input)
                team.model = cast(Model, team.model)
                if team.pre_hooks is not None:
                    pre_hook_iterator = team._aexecute_pre_hooks(
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
                await team._check_and_refresh_mcp_tools()
                _tools = team._determine_tools_for_model(
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
                run_messages = await team._aget_run_messages(
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
                memory_task = await team._astart_memory_task(
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
                async for item in team._ahandle_reasoning_stream(
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
                    async for event in team._ahandle_model_response_stream(
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
                    async for event in team._ahandle_model_response_stream(
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

                    async for event in team._agenerate_response_with_output_model_stream(
                        session=team_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        stream_events=stream_events,
                    ):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event

                # Check for cancellation after model processing
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 6b. Check if delegation propagated member HITL requirements
                if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                    from agno.team import _hooks

                    async for item in _hooks.ahandle_team_run_paused_stream(  # type: ignore[assignment]
                        team, run_response=run_response, session=team_session
                    ):
                        yield item
                    if yield_run_output:
                        yield run_response
                    return

                # 7. Parse response with parser model if provided
                async for event in team._aparse_response_with_parser_model_stream(
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
                    async for event in team._aexecute_post_hooks(
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
                await team._acleanup_and_store(run_response=run_response, session=team_session)

                if stream_events:
                    yield completed_event

                if yield_run_output:
                    yield run_response

                # Log Team Telemetry
                await team._alog_team_telemetry(session_id=team_session.session_id, run_id=run_response.run_id)

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
                await team._acleanup_and_store(run_response=run_response, session=team_session)
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

                await team._acleanup_and_store(run_response=run_response, session=team_session)

                yield run_error

                break

            except (KeyboardInterrupt, asyncio.CancelledError):
                run_response = cast(TeamRunOutput, run_response)
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
                await team._acleanup_and_store(run_response=run_response, session=team_session)

                yield run_error

    finally:
        # Always disconnect connectable tools
        team._disconnect_connectable_tools()
        await team._disconnect_mcp_tools()

        # Cancel background task on error (await_for_thread_tasks_stream handles waiting on success)
        if memory_task is not None and not memory_task.done():
            memory_task.cancel()
            try:
                await memory_task
            except asyncio.CancelledError:
                pass

        # Always clean up the run tracking
        await acleanup_run(run_response.run_id)  # type: ignore


def arun(  # type: ignore
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
    run_id = run_id or str(uuid4())

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

    # Initialize Team
    team.initialize_team(debug_mode=debug_mode)

    # Normalise hook & guardails
    if not team._hooks_normalised:
        if team.pre_hooks:
            team.pre_hooks = normalize_pre_hooks(team.pre_hooks, async_mode=True)  # type: ignore
        if team.post_hooks:
            team.post_hooks = normalize_post_hooks(team.post_hooks, async_mode=True)  # type: ignore
        team._hooks_normalised = True

    session_id, user_id = team._initialize_session(session_id=session_id, user_id=user_id)

    image_artifacts, video_artifacts, audio_artifacts, file_artifacts = validate_media_object_id(
        images=images, videos=videos, audios=audio, files=files
    )

    dependencies_provided = dependencies is not None
    knowledge_filters_provided = knowledge_filters is not None
    metadata_provided = metadata is not None
    output_schema_provided = output_schema is not None

    # Resolve variables
    dependencies = dependencies if dependencies is not None else team.dependencies
    add_dependencies = (
        add_dependencies_to_context if add_dependencies_to_context is not None else team.add_dependencies_to_context
    )
    add_session_state = (
        add_session_state_to_context if add_session_state_to_context is not None else team.add_session_state_to_context
    )
    add_history = add_history_to_context if add_history_to_context is not None else team.add_history_to_context

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
        stream = False if team.stream is None else team.stream

    # Can't stream events if streaming is disabled
    if stream is False:
        stream_events = False

    if stream_events is None:
        stream_events = False if team.stream_events is None else team.stream_events

    team.model = cast(Model, team.model)

    if team.metadata is not None:
        if metadata is None:
            metadata = team.metadata
        else:
            merge_dictionaries(metadata, team.metadata)

    #  Get knowledge filters
    effective_filters = knowledge_filters
    if team.knowledge_filters or knowledge_filters:
        effective_filters = team._get_effective_filters(knowledge_filters)

    # Resolve output_schema parameter takes precedence, then fall back to team.output_schema
    if output_schema is None:
        output_schema = team.output_schema

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
    # Apply options with precedence: explicit args > existing run_context > resolved defaults.
    if dependencies_provided:
        run_context.dependencies = dependencies
    elif run_context.dependencies is None:
        run_context.dependencies = dependencies
    if knowledge_filters_provided:
        run_context.knowledge_filters = effective_filters
    elif run_context.knowledge_filters is None:
        run_context.knowledge_filters = effective_filters
    if metadata_provided:
        run_context.metadata = metadata
    elif run_context.metadata is None:
        run_context.metadata = metadata
    if output_schema_provided:
        run_context.output_schema = output_schema
    elif run_context.output_schema is None:
        run_context.output_schema = output_schema

    # Configure the model for runs
    response_format: Optional[Union[Dict, Type[BaseModel]]] = (
        team._get_response_format(run_context=run_context) if team.parser_model is None else None
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

    if stream:
        return team._arun_stream(  # type: ignore
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
        return team._arun(  # type: ignore
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
    team: "Team",
    event: Union[RunOutputEvent, TeamRunOutputEvent],
    run_response: TeamRunOutput,
):
    # We only store events that are not run_response_content events
    events_to_skip = [e.value for e in team.events_to_skip] if team.events_to_skip else []
    if team.store_events and event.event not in events_to_skip:
        if run_response.events is None:
            run_response.events = []
        run_response.events.append(event)
    return event


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
# continue_run helpers
# ---------------------------------------------------------------------------


def _normalize_requirements_payload(requirements: Optional[list]) -> Optional[list]:
    """Normalize requirement payloads to RunRequirement objects."""
    from agno.run.requirement import RunRequirement

    if requirements is None:
        return None

    normalized_requirements = []
    for req in requirements:
        if isinstance(req, RunRequirement):
            normalized_requirements.append(req)
        elif isinstance(req, dict):
            normalized_requirements.append(RunRequirement.from_dict(req))
        else:
            raise TypeError(
                "Invalid requirement type in continue_run(..., requirements=...). "
                f"Expected RunRequirement or dict, got {type(req).__name__}."
            )

    return normalized_requirements


def _route_requirements_to_members(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
) -> Dict[str, Union["RunOutput", TeamRunOutput]]:
    """Route requirements from a paused team run to their respective member agents (sync).

    Groups requirements by member_run_id and calls member.continue_run() for each group.

    Raises:
        RuntimeError: If any requirement cannot be routed (missing context, missing member,
            or member continuation failure). The run should remain paused in this case.

    Returns:
        Dict mapping member name/id to their RunOutput/TeamRunOutput.
    """
    from collections import defaultdict

    from agno.run.requirement import RunRequirement

    if not run_response.requirements:
        return {}

    # Group requirements by (member_agent_id, member_run_id)
    member_requirements: Dict[tuple, List[RunRequirement]] = defaultdict(list)
    for req in run_response.requirements:
        if req.member_agent_id and req.member_run_id:
            key = (req.member_agent_id, req.member_agent_name or req.member_agent_id, req.member_run_id)
            member_requirements[key].append(req)
        else:
            raise RuntimeError(
                f"Cannot route requirement {req.id}: missing member context "
                f"(member_agent_id={req.member_agent_id}, member_run_id={req.member_run_id})"
            )

    results: Dict[str, Union[RunOutput, TeamRunOutput]] = {}
    for (member_id, member_name, member_run_id), reqs in member_requirements.items():
        # Find the routable member (parent sub-team for nested matches)
        found = team._find_member_route_by_id(member_id)
        if found is None:
            raise RuntimeError(f"Cannot route requirements to member: no agent found with ID {member_id}")
        _, member = found

        # Continue the member's run — let exceptions propagate to keep run paused
        member_result = member.continue_run(
            run_id=member_run_id,
            requirements=reqs,
            session_id=session.session_id,
        )
        results[member_name] = member_result

    return results


async def _aroute_requirements_to_members(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
) -> Dict[str, Union["RunOutput", TeamRunOutput]]:
    """Route requirements from a paused team run to their respective member agents (async).

    Groups requirements by member_run_id and calls member.acontinue_run() for each group.

    Raises:
        RuntimeError: If any requirement cannot be routed (missing context, missing member,
            or member continuation failure). The run should remain paused in this case.

    Returns:
        Dict mapping member name/id to their RunOutput/TeamRunOutput.
    """
    from collections import defaultdict

    from agno.run.requirement import RunRequirement

    if not run_response.requirements:
        return {}

    # Group requirements by (member_agent_id, member_run_id)
    member_requirements: Dict[tuple, List[RunRequirement]] = defaultdict(list)
    for req in run_response.requirements:
        if req.member_agent_id and req.member_run_id:
            key = (req.member_agent_id, req.member_agent_name or req.member_agent_id, req.member_run_id)
            member_requirements[key].append(req)
        else:
            raise RuntimeError(
                f"Cannot route requirement {req.id}: missing member context "
                f"(member_agent_id={req.member_agent_id}, member_run_id={req.member_run_id})"
            )

    # Validate all members exist before starting any continuations
    member_map: Dict[tuple, Any] = {}
    for (member_id, member_name, member_run_id), reqs in member_requirements.items():
        found = team._find_member_route_by_id(member_id)
        if found is None:
            raise RuntimeError(f"Cannot route requirements to member: no agent found with ID {member_id}")
        member_map[(member_id, member_name, member_run_id)] = found[1]

    results: Dict[str, Union[RunOutput, TeamRunOutput]] = {}

    # Run all member continue_runs concurrently — let exceptions propagate
    async def _continue_member(member_name: str, member: Any, member_run_id: str, reqs: list) -> tuple:
        result = await member.acontinue_run(
            run_id=member_run_id,
            requirements=reqs,
            session_id=session.session_id,
        )
        return (member_name, result)

    tasks = [
        _continue_member(member_name, member_map[key], member_run_id, reqs)
        for key, reqs in member_requirements.items()
        for (_, member_name, member_run_id) in [key]
    ]
    completed = await asyncio.gather(*tasks)
    for member_name, result in completed:
        results[member_name] = result

    return results


def _build_continuation_message(member_results: Dict[str, Union["RunOutput", TeamRunOutput]]) -> str:
    """Build a user message summarizing member agent results for the team model."""
    from pydantic import BaseModel

    parts = []
    for member_name, result in member_results.items():
        content = result.content
        if content is None:
            content = "(no content)"
        elif isinstance(content, BaseModel):
            content = content.model_dump_json(indent=2)
        elif not isinstance(content, str):
            import json

            content = json.dumps(content, indent=2, default=str)
        parts.append(f"Results from '{member_name}':\n{content}")
    return "Previously delegated tasks have been completed.\n\n" + "\n\n".join(parts)


def _propagate_still_paused_member_requirements(
    run_response: TeamRunOutput,
    still_paused: Dict[str, Union["RunOutput", TeamRunOutput]],
) -> None:
    """Rebuild team requirements from paused member results for chained HITL flows."""
    run_response.requirements = []
    for fallback_name, result in still_paused.items():
        if not result.requirements:
            log_debug(f"Member '{fallback_name}' is still paused but has no requirements")
            continue

        # Derive routing context from existing requirements first (which already carry
        # the routable name-based ID from the initial _propagate_member_pause call),
        # before falling back to result.agent_id/team_id which may be a UUID.
        member_id = (
            next((r.member_agent_id for r in result.requirements if r.member_agent_id), None)
            or getattr(result, "agent_id", None)
            or getattr(result, "team_id", None)
        )
        member_name = (
            next((r.member_agent_name for r in result.requirements if r.member_agent_name), None)
            or getattr(result, "agent_name", None)
            or getattr(result, "team_name", None)
            or fallback_name
        )

        log_debug(f"Re-propagating requirement(s) from still-paused member '{member_name}'")
        for req in result.requirements:
            if req.is_resolved():
                continue
            req_copy = deepcopy(req)
            if req_copy.member_agent_id is None:
                req_copy.member_agent_id = member_id
            if req_copy.member_agent_name is None:
                req_copy.member_agent_name = member_name
            if req_copy.member_run_id is None:
                req_copy.member_run_id = result.run_id
            run_response.requirements.append(req_copy)


# ---------------------------------------------------------------------------
# continue_run dispatch
# ---------------------------------------------------------------------------


def continue_run_dispatch(
    team: "Team",
    run_response: Optional[TeamRunOutput] = None,
    *,
    run_id: Optional[str] = None,
    requirements: Optional[list] = None,
    stream: Optional[bool] = None,
    stream_events: Optional[bool] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    yield_run_output: bool = False,
    **kwargs: Any,
) -> Union[TeamRunOutput, Iterator[Union[RunOutputEvent, TeamRunOutputEvent]]]:
    """Continue a paused team run by routing requirements to members and re-invoking the team.

    Args:
        run_response: The paused run response to continue.
        run_id: The run id to continue. Alternative to passing run_response.
        requirements: The resolved requirements. Required when using run_id.
        stream: Whether to stream the response.
        stream_events: Whether to stream all events.
        user_id: The user id.
        session_id: The session id. Required when using run_id.
        debug_mode: Whether to enable debug mode.
        yield_run_output: Whether to yield the final run output (streaming only).
    """
    if run_response is None and run_id is None:
        raise ValueError("Either run_response or run_id must be provided.")

    if run_response is None and (run_id is not None and (session_id is None and team.session_id is None)):
        raise ValueError("Session ID is required to continue a run from a run_id.")

    if team._has_async_db():
        raise Exception("continue_run() is not supported with an async DB. Please use acontinue_run() instead.")

    # Initialize Team
    team.initialize_team(debug_mode=debug_mode)

    session_id = run_response.session_id if run_response else session_id
    user_id = run_response.user_id if run_response and run_response.user_id else user_id

    session_id, user_id = team._initialize_session(session_id=session_id, user_id=user_id)

    # Read existing session
    team_session = team._read_or_create_session(session_id=session_id, user_id=user_id)

    # Find run_response from session if only run_id provided
    if run_response is None and run_id is not None:
        if requirements is None:
            raise ValueError("To continue a run from a given run_id, the requirements parameter must be provided.")

        runs = team_session.runs or []
        run_response = cast(Optional[TeamRunOutput], next((r for r in runs if r.run_id == run_id), None))
        if run_response is None:
            raise RuntimeError(f"No runs found for run ID {run_id}")

        run_response.requirements = requirements  # type: ignore[assignment]

    run_response = cast(TeamRunOutput, run_response)
    run_response.requirements = _normalize_requirements_payload(run_response.requirements)

    if run_response.status != RunStatus.paused:
        raise ValueError(f"Cannot continue run {run_response.run_id}: run is not paused (status={run_response.status})")

    # Use stream override value when necessary
    if stream is None:
        stream = False if team.stream is None else team.stream

    # Can't stream events if streaming is disabled
    if stream is False:
        stream_events = False

    if stream_events is None:
        stream_events = False if team.stream_events is None else team.stream_events
    log_debug(f"Team Run Continue: {run_response.run_id}", center=True, symbol="*")

    # Route requirements to member agents
    try:
        member_results = _route_requirements_to_members(team, run_response, team_session)
    except Exception:
        # If routing fails, keep the run paused so the user can retry
        run_response.status = RunStatus.paused
        team._cleanup_and_store(run_response=run_response, session=team_session)
        raise

    # Check if any member is still paused (chained HITL)
    still_paused = {name: result for name, result in member_results.items() if getattr(result, "is_paused", False)}
    if still_paused:
        from agno.team import _hooks

        # Re-propagate requirements with member context for chained pauses.
        _propagate_still_paused_member_requirements(run_response, still_paused)
        if stream:
            pause_stream = _hooks.handle_team_run_paused_stream(team, run_response=run_response, session=team_session)
            if yield_run_output:

                def _wrap_paused_stream() -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent, TeamRunOutput]]:
                    yield from pause_stream
                    yield run_response

                return _wrap_paused_stream()  # type: ignore[return-value]
            return pause_stream
        return _hooks.handle_team_run_paused(team, run_response=run_response, session=team_session)

    # Build continuation message and re-invoke the team
    continuation_message = _build_continuation_message(member_results)

    if stream:
        # For streaming, defer completion marking until the stream is fully consumed
        inner = run(
            team,
            input=continuation_message,
            stream=True,
            stream_events=stream_events,
            session_id=session_id,
            user_id=user_id,
            debug_mode=debug_mode,
            yield_run_output=yield_run_output,
            add_history_to_context=True,
            **kwargs,
        )

        def _wrap_continuation_stream() -> Iterator[Union[RunOutputEvent, TeamRunOutputEvent, TeamRunOutput]]:
            try:
                yield from inner  # type: ignore[misc]
            except Exception:
                run_response.status = RunStatus.paused
                team._cleanup_and_store(run_response=run_response, session=team_session)
                raise
            run_response.status = RunStatus.completed
            team._cleanup_and_store(run_response=run_response, session=team_session)

        return _wrap_continuation_stream()  # type: ignore[return-value]

    try:
        result = run(
            team,
            input=continuation_message,
            stream=False,
            session_id=session_id,
            user_id=user_id,
            debug_mode=debug_mode,
            add_history_to_context=True,
            **kwargs,
        )
    except Exception:
        # If continuation fails, keep the original run as paused so user can retry
        run_response.status = RunStatus.paused
        team._cleanup_and_store(run_response=run_response, session=team_session)
        raise

    # Mark the paused run as completed only after the continuation succeeds
    run_response.status = RunStatus.completed
    team._cleanup_and_store(run_response=run_response, session=team_session)

    return result


def acontinue_run_dispatch(  # type: ignore
    team: "Team",
    run_response: Optional[TeamRunOutput] = None,
    *,
    run_id: Optional[str] = None,
    requirements: Optional[list] = None,
    stream: Optional[bool] = None,
    stream_events: Optional[bool] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    yield_run_output: bool = False,
    **kwargs: Any,
) -> Union[TeamRunOutput, AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent]]]:
    """Continue a paused team run asynchronously.

    Args:
        run_response: The paused run response to continue.
        run_id: The run id to continue. Alternative to passing run_response.
        requirements: The resolved requirements. Required when using run_id.
        stream: Whether to stream the response.
        stream_events: Whether to stream all events.
        user_id: The user id.
        session_id: The session id. Required when using run_id.
        debug_mode: Whether to enable debug mode.
        yield_run_output: Whether to yield the final run output (streaming only).
    """
    if run_response is None and run_id is None:
        raise ValueError("Either run_response or run_id must be provided.")

    if run_response is None and (run_id is not None and (session_id is None and team.session_id is None)):
        raise ValueError("Session ID is required to continue a run from a run_id.")

    # Initialize Team
    team.initialize_team(debug_mode=debug_mode)

    session_id = run_response.session_id if run_response else session_id
    user_id = run_response.user_id if run_response and run_response.user_id else user_id

    session_id, user_id = team._initialize_session(session_id=session_id, user_id=user_id)

    if run_response is not None:
        run_response = cast(TeamRunOutput, run_response)

    # Use stream override value when necessary
    if stream is None:
        stream = False if team.stream is None else team.stream

    # Can't stream events if streaming is disabled
    if stream is False:
        stream_events = False

    if stream_events is None:
        stream_events = False if team.stream_events is None else team.stream_events

    if stream:
        return _acontinue_run_stream_impl(  # type: ignore[return-value]
            team,
            run_response=run_response,
            run_id=run_id,
            requirements=requirements,
            session_id=session_id,
            user_id=user_id,
            stream_events=stream_events,
            yield_run_output=yield_run_output,
            debug_mode=debug_mode,
            **kwargs,
        )
    else:
        return _acontinue_run_impl(  # type: ignore
            team,
            run_response=run_response,
            run_id=run_id,
            requirements=requirements,
            session_id=session_id,
            user_id=user_id,
            debug_mode=debug_mode,
            **kwargs,
        )


async def _acontinue_run_impl(
    team: "Team",
    session_id: str,
    run_response: Optional[TeamRunOutput] = None,
    run_id: Optional[str] = None,
    requirements: Optional[list] = None,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    **kwargs: Any,
) -> TeamRunOutput:
    """Async non-streaming implementation of continue_run for teams."""

    # Read existing session
    team_session = await team._aread_or_create_session(session_id=session_id, user_id=user_id)

    # Find run_response from session if only run_id provided
    if run_response is None and run_id is not None:
        if requirements is None:
            raise ValueError("To continue a run from a given run_id, the requirements parameter must be provided.")

        runs = team_session.runs or []
        run_response = cast(Optional[TeamRunOutput], next((r for r in runs if r.run_id == run_id), None))
        if run_response is None:
            raise RuntimeError(f"No runs found for run ID {run_id}")

        run_response.requirements = requirements  # type: ignore[assignment]

    run_response = cast(TeamRunOutput, run_response)
    run_response.requirements = _normalize_requirements_payload(run_response.requirements)

    if run_response.status != RunStatus.paused:
        raise ValueError(f"Cannot continue run {run_response.run_id}: run is not paused (status={run_response.status})")

    log_debug(f"Team Run Continue: {run_response.run_id}", center=True, symbol="*")

    # Route requirements to member agents
    try:
        member_results = await _aroute_requirements_to_members(team, run_response, team_session)
    except Exception:
        # If routing fails, keep the run paused so the user can retry
        run_response.status = RunStatus.paused
        await team._acleanup_and_store(run_response=run_response, session=team_session)
        raise

    # Check if any member is still paused (chained HITL)
    still_paused = {name: result for name, result in member_results.items() if getattr(result, "is_paused", False)}
    if still_paused:
        from agno.team import _hooks

        _propagate_still_paused_member_requirements(run_response, still_paused)
        return await _hooks.ahandle_team_run_paused(team, run_response=run_response, session=team_session)

    # Build continuation message and re-invoke the team
    continuation_message = _build_continuation_message(member_results)

    try:
        result = await arun(  # type: ignore[misc]
            team,
            input=continuation_message,
            stream=False,
            session_id=session_id,
            user_id=user_id,
            debug_mode=debug_mode,
            add_history_to_context=True,
            **kwargs,
        )
    except Exception:
        # If continuation fails, keep the original run as paused so user can retry
        run_response.status = RunStatus.paused
        await team._acleanup_and_store(run_response=run_response, session=team_session)
        raise

    # Mark the paused run as completed only after the continuation succeeds
    run_response.status = RunStatus.completed
    await team._acleanup_and_store(run_response=run_response, session=team_session)

    return result


async def _acontinue_run_stream_impl(
    team: "Team",
    session_id: str,
    run_response: Optional[TeamRunOutput] = None,
    run_id: Optional[str] = None,
    requirements: Optional[list] = None,
    user_id: Optional[str] = None,
    stream_events: bool = False,
    yield_run_output: bool = False,
    debug_mode: Optional[bool] = None,
    **kwargs: Any,
) -> AsyncIterator[Union[TeamRunOutputEvent, RunOutputEvent, TeamRunOutput]]:
    """Async streaming implementation of continue_run for teams."""

    # Read existing session
    team_session = await team._aread_or_create_session(session_id=session_id, user_id=user_id)

    # Find run_response from session if only run_id provided
    if run_response is None and run_id is not None:
        if requirements is None:
            raise ValueError("To continue a run from a given run_id, the requirements parameter must be provided.")

        runs = team_session.runs or []
        run_response = cast(Optional[TeamRunOutput], next((r for r in runs if r.run_id == run_id), None))
        if run_response is None:
            raise RuntimeError(f"No runs found for run ID {run_id}")

        run_response.requirements = requirements  # type: ignore[assignment]

    run_response = cast(TeamRunOutput, run_response)
    run_response.requirements = _normalize_requirements_payload(run_response.requirements)

    if run_response.status != RunStatus.paused:
        raise ValueError(f"Cannot continue run {run_response.run_id}: run is not paused (status={run_response.status})")

    log_debug(f"Team Run Continue: {run_response.run_id}", center=True, symbol="*")

    # Route requirements to member agents
    try:
        member_results = await _aroute_requirements_to_members(team, run_response, team_session)
    except Exception:
        # If routing fails, keep the run paused so the user can retry
        run_response.status = RunStatus.paused
        await team._acleanup_and_store(run_response=run_response, session=team_session)
        raise

    # Check if any member is still paused (chained HITL)
    still_paused = {name: result for name, result in member_results.items() if getattr(result, "is_paused", False)}
    if still_paused:
        from agno.team import _hooks

        _propagate_still_paused_member_requirements(run_response, still_paused)
        async for item in _hooks.ahandle_team_run_paused_stream(team, run_response=run_response, session=team_session):
            yield item
        if yield_run_output:
            yield run_response
        return

    # Build continuation message and re-invoke the team
    continuation_message = _build_continuation_message(member_results)

    new_run_response_stream = arun(
        team,
        input=continuation_message,
        stream=True,
        stream_events=stream_events,
        session_id=session_id,
        user_id=user_id,
        debug_mode=debug_mode,
        yield_run_output=yield_run_output,
        add_history_to_context=True,
        **kwargs,
    )

    try:
        async for item in new_run_response_stream:  # type: ignore[union-attr]
            yield item
    except Exception:
        # If continuation fails, keep the original run as paused so user can retry
        run_response.status = RunStatus.paused
        await team._acleanup_and_store(run_response=run_response, session=team_session)
        raise

    # Mark the paused run as completed only after streaming finishes
    run_response.status = RunStatus.completed
    await team._acleanup_and_store(run_response=run_response, session=team_session)
