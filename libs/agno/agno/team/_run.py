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
from agno.tools.function import Function
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

# Strong references to background tasks so they aren't garbage-collected mid-execution.
# See: https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
_background_tasks: set[asyncio.Task[None]] = set()

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
    """Run the Team in autonomous task mode.

    The team leader iteratively plans and delegates tasks to members until
    the goal is complete or max_iterations is reached.
    """
    from agno.team._hooks import _execute_post_hooks, _execute_pre_hooks
    from agno.team._init import _disconnect_connectable_tools
    from agno.team._managers import _start_memory_future
    from agno.team._messages import _get_run_messages
    from agno.team._response import (
        _convert_response_to_structured_format,
        _update_run_response,
        handle_reasoning,
    )
    from agno.team._telemetry import log_team_telemetry
    from agno.team._tools import _determine_tools_for_model
    from agno.team.task import TaskStatus, load_task_list

    log_debug(f"Team Task Run Start: {run_response.run_id}", center=True)
    memory_future = None

    try:
        run_input = cast(TeamRunInput, run_response.input)
        team.model = cast(Model, team.model)

        # 1. Execute pre-hooks
        if team.pre_hooks is not None:
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
            deque(pre_hook_iterator, maxlen=0)

        # 2. Determine tools for model (includes task management tools)
        team_run_context: Dict[str, Any] = {}
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
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            stream=False,
            stream_events=False,
        )

        # 3. Prepare initial run messages
        run_messages = _get_run_messages(
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

        # 4. Start memory creation in background
        memory_future = _start_memory_future(
            team,
            run_messages=run_messages,
            user_id=user_id,
            existing_future=memory_future,
        )

        raise_if_cancelled(run_response.run_id)  # type: ignore

        # 5. Reason about the task if reasoning is enabled
        handle_reasoning(team, run_response=run_response, run_messages=run_messages, run_context=run_context)

        raise_if_cancelled(run_response.run_id)  # type: ignore

        # Use accumulated messages for the iterative loop
        accumulated_messages = run_messages.messages

        model_response: Optional[ModelResponse] = None

        # === Iterative task loop ===
        for iteration in range(team.max_iterations):
            log_debug(f"Task iteration {iteration + 1}/{team.max_iterations}")

            # On subsequent iterations, inject current task state as a user message
            if iteration > 0:
                task_list = load_task_list(run_context.session_state)
                task_summary = task_list.get_summary_string()
                state_message = Message(
                    role="user",
                    content=f"<current_task_state>\n{task_summary}\n</current_task_state>\n\n"
                    "Continue working on the tasks. Create, execute, or update tasks as needed. "
                    "When all tasks are done, call `mark_all_complete` with a summary.",
                )
                accumulated_messages.append(state_message)

            # Get model response
            model_response = team.model.response(
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
            _update_run_response(
                team,
                model_response=model_response,
                run_response=run_response,
                run_messages=run_messages,
                run_context=run_context,
            )

            # Check if delegation propagated member HITL requirements
            if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                from agno.team import _hooks

                return _hooks.handle_team_run_paused(team, run_response=run_response, session=session)

            # Check termination conditions
            task_list = load_task_list(run_context.session_state)
            if task_list.goal_complete:
                log_debug("Task goal marked complete, finishing task loop.")
                break

            if task_list.all_terminal():
                # All tasks done but some may have failed
                has_failures = any(t.status == TaskStatus.failed for t in task_list.tasks)
                if not has_failures:
                    log_debug("All tasks completed successfully, finishing task loop.")
                    break
                # If there are failures, continue to let model handle them
                log_debug("All tasks terminal but some failed, continuing to let model handle.")
        else:
            # Loop exhausted without completing
            task_list = load_task_list(run_context.session_state)
            if not task_list.goal_complete:
                log_warning(f"Reached max_iterations ({team.max_iterations}) without completing all tasks.")

        # === Post-loop ===

        # Store media if enabled
        if team.store_media and model_response is not None:
            store_media_util(run_response, model_response)

        # Convert response to structured format
        _convert_response_to_structured_format(team, run_response=run_response, run_context=run_context)

        # Execute post-hooks
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

        # Wait for background memory creation
        wait_for_open_threads(memory_future=memory_future)  # type: ignore

        raise_if_cancelled(run_response.run_id)  # type: ignore

        # Create session summary
        if team.session_summary_manager is not None:
            session.upsert_run(run_response=run_response)
            try:
                team.session_summary_manager.create_session_summary(session=session)
            except Exception as e:
                log_warning(f"Error in session summary creation: {str(e)}")

        raise_if_cancelled(run_response.run_id)  # type: ignore

        # Set the run status to completed
        run_response.status = RunStatus.completed

        # Cleanup and store
        _cleanup_and_store(team, run_response=run_response, session=session)

        log_team_telemetry(team, session_id=session.session_id, run_id=run_response.run_id)

        log_debug(f"Team Task Run End: {run_response.run_id}", center=True, symbol="*")

        return run_response

    except RunCancelledException as e:
        log_info(f"Team task run {run_response.run_id} was cancelled")
        run_response.status = RunStatus.cancelled
        run_response.content = str(e)
        _cleanup_and_store(team, run_response=run_response, session=session)
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
        _cleanup_and_store(team, run_response=run_response, session=session)
        return run_response

    except KeyboardInterrupt:
        run_response = cast(TeamRunOutput, run_response)
        run_response.status = RunStatus.cancelled
        run_response.content = "Operation cancelled by user"
        return run_response

    except Exception as e:
        run_response.status = RunStatus.error
        run_error = create_team_run_error_event(run_response, error=str(e))
        run_response.events = add_team_error_event(error=run_error, events=run_response.events)
        if run_response.content is None:
            run_response.content = str(e)
        log_error(f"Error in Team task run: {str(e)}")
        _cleanup_and_store(team, run_response=run_response, session=session)
        return run_response

    finally:
        if memory_future is not None and not memory_future.done():
            memory_future.cancel()
        _disconnect_connectable_tools(team)
        cleanup_run(run_response.run_id)  # type: ignore

    return run_response


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
    from agno.team._managers import _start_learning_future, _start_memory_future
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

    # Dispatch to task mode if applicable
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
    learning_future = None
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
                learning_future = _start_learning_future(
                    team,
                    run_messages=run_messages,
                    session=session,
                    user_id=user_id,
                    existing_future=learning_future,
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

                # 7b. Check if delegation propagated member HITL requirements
                if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                    from agno.team import _hooks

                    return _hooks.handle_team_run_paused(team, run_response=run_response, session=session)

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
                wait_for_open_threads(memory_future=memory_future, learning_future=learning_future)  # type: ignore

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
        for future in (memory_future, learning_future):
            if future is not None and not future.done():
                future.cancel()
                try:
                    future.result(timeout=0)
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
    from agno.team._managers import _start_learning_future, _start_memory_future
    from agno.team._messages import _get_run_messages
    from agno.team._response import (
        _handle_model_response_stream,
        generate_response_with_output_model_stream,
        handle_reasoning_stream,
        parse_response_with_parser_model_stream,
    )
    from agno.team._telemetry import log_team_telemetry
    from agno.team._tools import _determine_tools_for_model

    # Fallback for tasks mode (streaming not yet supported)
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
        yield result
        return

    log_debug(f"Team Run Start: {run_response.run_id}", center=True)

    memory_future = None
    learning_future = None
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
                learning_future = _start_learning_future(
                    team,
                    run_messages=run_messages,
                    session=session,
                    user_id=user_id,
                    existing_future=learning_future,
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

                # 6b. Check if delegation propagated member HITL requirements
                if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                    from agno.team import _hooks

                    yield from _hooks.handle_team_run_paused_stream(team, run_response=run_response, session=session)
                    if yield_run_output:
                        yield run_response
                    return

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
                    learning_future=learning_future,  # type: ignore
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
        for future in (memory_future, learning_future):
            if future is not None and not future.done():
                future.cancel()
                try:
                    future.result(timeout=0)
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
    """Run the Team in autonomous task mode (async).

    The team leader iteratively plans and delegates tasks to members until
    the goal is complete or max_iterations is reached.
    """
    from agno.team._hooks import _aexecute_post_hooks, _aexecute_pre_hooks
    from agno.team._init import _disconnect_connectable_tools, _disconnect_mcp_tools
    from agno.team._managers import _astart_memory_task
    from agno.team._messages import _aget_run_messages
    from agno.team._response import (
        _convert_response_to_structured_format,
        _update_run_response,
        ahandle_reasoning,
    )
    from agno.team._telemetry import alog_team_telemetry
    from agno.team._tools import _check_and_refresh_mcp_tools, _determine_tools_for_model
    from agno.team.task import TaskStatus, load_task_list

    log_debug(f"Team Task Run Start: {run_response.run_id}", center=True)
    memory_task = None
    team_session: Optional[TeamSession] = None

    try:
        # Register run for cancellation tracking
        await aregister_run(run_context.run_id)

        # Setup session
        team_session = await _asetup_session(
            team=team,
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            run_id=run_response.run_id,
        )

        run_input = cast(TeamRunInput, run_response.input)
        team.model = cast(Model, team.model)

        # 1. Execute pre-hooks
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
            async for _ in pre_hook_iterator:
                pass

        # 2. Determine tools for model (includes task management tools)
        team_run_context: Dict[str, Any] = {}
        await _check_and_refresh_mcp_tools(team)
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

        # 3. Prepare initial run messages
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

        # 4. Start memory creation in background
        memory_task = await _astart_memory_task(
            team,
            run_messages=run_messages,
            user_id=user_id,
            existing_task=memory_task,
        )

        await araise_if_cancelled(run_response.run_id)  # type: ignore

        # 5. Reason about the task if reasoning is enabled
        await ahandle_reasoning(team, run_response=run_response, run_messages=run_messages, run_context=run_context)

        await araise_if_cancelled(run_response.run_id)  # type: ignore

        # Use accumulated messages for the iterative loop
        accumulated_messages = run_messages.messages

        model_response: Optional[ModelResponse] = None

        # === Iterative task loop ===
        for iteration in range(team.max_iterations):
            log_debug(f"Task iteration {iteration + 1}/{team.max_iterations}")

            # On subsequent iterations, inject current task state as a user message
            if iteration > 0:
                task_list = load_task_list(run_context.session_state)
                task_summary = task_list.get_summary_string()
                state_message = Message(
                    role="user",
                    content=f"<current_task_state>\n{task_summary}\n</current_task_state>\n\n"
                    "Continue working on the tasks. Create, execute, or update tasks as needed. "
                    "When all tasks are done, call `mark_all_complete` with a summary.",
                )
                accumulated_messages.append(state_message)

            # Get model response
            model_response = await team.model.aresponse(
                messages=accumulated_messages,
                response_format=response_format,
                tools=_tools,
                tool_choice=team.tool_choice,
                tool_call_limit=team.tool_call_limit,
                run_response=run_response,
                send_media_to_model=team.send_media_to_model,
                compression_manager=team.compression_manager if team.compress_tool_results else None,
            )  # type: ignore

            await araise_if_cancelled(run_response.run_id)  # type: ignore

            # Update run response
            _update_run_response(
                team,
                model_response=model_response,
                run_response=run_response,
                run_messages=run_messages,
                run_context=run_context,
            )

            # Check if delegation propagated member HITL requirements
            if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                from agno.team import _hooks

                return await _hooks.ahandle_team_run_paused(team, run_response=run_response, session=team_session)

            # Check termination conditions
            task_list = load_task_list(run_context.session_state)
            if task_list.goal_complete:
                log_debug("Task goal marked complete, finishing task loop.")
                break

            if task_list.all_terminal():
                has_failures = any(t.status == TaskStatus.failed for t in task_list.tasks)
                if not has_failures:
                    log_debug("All tasks completed successfully, finishing task loop.")
                    break
                log_debug("All tasks terminal but some failed, continuing to let model handle.")
        else:
            # Loop exhausted without completing
            task_list = load_task_list(run_context.session_state)
            if not task_list.goal_complete:
                log_warning(f"Reached max_iterations ({team.max_iterations}) without completing all tasks.")

        # === Post-loop ===

        # Store media if enabled
        if team.store_media and model_response is not None:
            store_media_util(run_response, model_response)

        # Convert response to structured format
        _convert_response_to_structured_format(team, run_response=run_response, run_context=run_context)

        # Execute post-hooks
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

        # Wait for background memory creation
        await await_for_open_threads(memory_task=memory_task)

        await araise_if_cancelled(run_response.run_id)  # type: ignore

        # Create session summary
        if team.session_summary_manager is not None:
            team_session.upsert_run(run_response=run_response)
            try:
                await team.session_summary_manager.acreate_session_summary(session=team_session)
            except Exception as e:
                log_warning(f"Error in session summary creation: {str(e)}")

        await araise_if_cancelled(run_response.run_id)  # type: ignore

        # Set the run status to completed
        run_response.status = RunStatus.completed

        # Cleanup and store
        await _acleanup_and_store(team, run_response=run_response, session=team_session)

        await alog_team_telemetry(team, session_id=team_session.session_id, run_id=run_response.run_id)

        log_debug(f"Team Task Run End: {run_response.run_id}", center=True, symbol="*")

        return run_response

    except RunCancelledException as e:
        log_info(f"Team task run {run_response.run_id} was cancelled")
        run_response.status = RunStatus.cancelled
        run_response.content = str(e)
        if team_session is not None:
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
        if team_session is not None:
            await _acleanup_and_store(team, run_response=run_response, session=team_session)
        return run_response

    except (KeyboardInterrupt, asyncio.CancelledError):
        run_response = cast(TeamRunOutput, run_response)
        run_response.status = RunStatus.cancelled
        run_response.content = "Operation cancelled by user"
        return run_response

    except Exception as e:
        run_response.status = RunStatus.error
        run_error = create_team_run_error_event(run_response, error=str(e))
        run_response.events = add_team_error_event(error=run_error, events=run_response.events)
        if run_response.content is None:
            run_response.content = str(e)
        log_error(f"Error in Team task run: {str(e)}")
        if team_session is not None:
            await _acleanup_and_store(team, run_response=run_response, session=team_session)
        return run_response

    finally:
        _disconnect_connectable_tools(team)
        await _disconnect_mcp_tools(team)
        if memory_task is not None and not memory_task.done():
            memory_task.cancel()
            try:
                await memory_task
            except asyncio.CancelledError:
                pass
        await acleanup_run(run_response.run_id)  # type: ignore

    return run_response


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
    from agno.team._managers import _astart_learning_task, _astart_memory_task
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

    # Dispatch to task mode if applicable
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

    log_debug(f"Team Run Start: {run_response.run_id}", center=True)
    memory_task = None
    learning_task = None

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

                # 2. Resolve callable factories and determine tools for model
                team_run_context: Dict[str, Any] = {}
                team.model = cast(Model, team.model)

                # Resolve callable factories (tools, knowledge, members) before tool determination
                from agno.team._tools import _aresolve_callable_resources

                await _aresolve_callable_resources(team, run_context=run_context)

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
                learning_task = await _astart_learning_task(
                    team,
                    run_messages=run_messages,
                    session=team_session,
                    user_id=user_id,
                    existing_task=learning_task,
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

                # 7b. Check if delegation propagated member HITL requirements
                if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                    from agno.team import _hooks

                    return await _hooks.ahandle_team_run_paused(team, run_response=run_response, session=team_session)

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
                await await_for_open_threads(memory_task=memory_task, learning_task=learning_task)

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
        if learning_task is not None and not learning_task.done():
            learning_task.cancel()
            try:
                await learning_task
            except asyncio.CancelledError:
                pass

        # Always clean up the run tracking
        await acleanup_run(run_response.run_id)  # type: ignore

    return run_response


async def _arun_background(
    team: "Team",
    run_response: TeamRunOutput,
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
) -> TeamRunOutput:
    """Start a team run in the background and return immediately with PENDING status.

    The run is persisted with PENDING status, then an asyncio task is spawned
    to execute the actual run. The task transitions through RUNNING -> COMPLETED/ERROR.

    Callers can poll for results via team.aget_run_output(run_id, session_id).
    """
    from agno.team._session import asave_session
    from agno.team._storage import _aread_or_create_session, _update_metadata

    # 1. Register the run for cancellation tracking (before spawning the task)
    await aregister_run(run_context.run_id)

    # 2. Set status to PENDING
    run_response.status = RunStatus.pending

    # 3. Persist the PENDING run so polling can find it immediately
    team_session = await _aread_or_create_session(team, session_id=session_id, user_id=user_id)
    _update_metadata(team, session=team_session)
    team_session.upsert_run(run_response=run_response)
    await asave_session(team, session=team_session)

    log_info(f"Background run {run_response.run_id} created with PENDING status")

    # 4. Spawn the background task
    async def _background_task() -> None:
        try:
            # Transition to RUNNING
            run_response.status = RunStatus.running
            team_session.upsert_run(run_response=run_response)
            await asave_session(team, session=team_session)

            # Execute the actual run — _arun handles everything including
            # session persistence and cleanup
            await _arun(
                team,
                run_response=run_response,
                run_context=run_context,
                session_id=session_id,
                user_id=user_id,
                add_history_to_context=add_history_to_context,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                response_format=response_format,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )
        except Exception:
            log_error(f"Background run {run_response.run_id} failed", exc_info=True)
            # Persist ERROR status
            try:
                run_response.status = RunStatus.error
                team_session.upsert_run(run_response=run_response)
                await asave_session(team, session=team_session)
            except Exception:
                log_error(f"Failed to persist error state for background run {run_response.run_id}", exc_info=True)
            # Note: acleanup_run is already called by _arun's finally block

    task = asyncio.create_task(_background_task())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # 5. Return immediately with the PENDING response
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
    from agno.team._managers import _astart_learning_task, _astart_memory_task
    from agno.team._messages import _aget_run_messages
    from agno.team._response import (
        _ahandle_model_response_stream,
        agenerate_response_with_output_model_stream,
        ahandle_reasoning_stream,
        aparse_response_with_parser_model_stream,
    )
    from agno.team._telemetry import alog_team_telemetry
    from agno.team._tools import _check_and_refresh_mcp_tools, _determine_tools_for_model

    # Fallback for tasks mode (streaming not yet supported)
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
        yield result
        return

    log_debug(f"Team Run Start: {run_response.run_id}", center=True)

    memory_task = None
    learning_task = None

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

                # 2. Resolve callable factories and determine tools for model
                team_run_context: Dict[str, Any] = {}
                team.model = cast(Model, team.model)

                # Resolve callable factories (tools, knowledge, members) before tool determination
                from agno.team._tools import _aresolve_callable_resources

                await _aresolve_callable_resources(team, run_context=run_context)

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
                learning_task = await _astart_learning_task(
                    team,
                    run_messages=run_messages,
                    session=team_session,
                    user_id=user_id,
                    existing_task=learning_task,
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
                    learning_task=learning_task,
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
        if learning_task is not None and not learning_task.done():
            learning_task.cancel()
            try:
                await learning_task
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
    background: bool = False,
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

    # Background execution: return immediately with PENDING status
    if background:
        if opts.stream:
            raise ValueError(
                "Background execution cannot be combined with streaming. Set stream=False when using background=True."
            )
        if not team.db:
            raise ValueError(
                "Background execution requires a database to be configured on the team for run persistence."
            )
        return _arun_background(  # type: ignore[return-value]
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


# ---------------------------------------------------------------------------
# continue_run infrastructure
# ---------------------------------------------------------------------------


def _get_continue_run_messages(
    team: "Team",
    input: List[Message],
) -> RunMessages:
    """Build a RunMessages object from the existing conversation messages.

    Similar to agent's get_continue_run_messages - extracts system and user messages
    from the existing message list for the continuation run.
    """
    run_messages = RunMessages()

    # Extract most recent user message
    user_message = None
    for msg in reversed(input):
        if msg.role == "user":
            user_message = msg
            break

    # Extract system message
    system_message = None
    system_role = team.system_message_role or "system"
    for msg in input:
        if msg.role == system_role:
            system_message = msg
            break

    run_messages.system_message = system_message
    run_messages.user_message = user_message
    run_messages.messages = input

    return run_messages


def _handle_team_tool_call_updates(
    team: "Team",
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    tools: List[Union[Function, dict]],
) -> None:
    """Handle tool call updates for team-level tools.

    Mirrors agent's handle_tool_call_updates but operates on team-level tools.
    The agent-level functions (run_tool, reject_tool_call, etc.) accept ``Agent``
    in their type hints but only access duck-typed attributes (``model``, ``name``,
    etc.) that ``Team`` also provides, so passing a ``Team`` is safe at runtime.
    """
    from agno.agent._tools import (
        handle_external_execution_update,
        handle_get_user_input_tool_update,
        handle_user_input_update,
        reject_tool_call,
        run_tool,
    )

    team.model = cast(Model, team.model)
    _functions = {tool.name: tool for tool in tools if isinstance(tool, Function)}

    for _t in run_response.tools or []:
        # Case 1: Handle confirmed tools and execute them
        if _t.requires_confirmation is not None and _t.requires_confirmation is True and _functions:
            if _t.confirmed is not None and _t.confirmed is True and _t.result is None:
                deque(run_tool(team, run_response, run_messages, _t, functions=_functions), maxlen=0)  # type: ignore
            else:
                reject_tool_call(team, run_messages, _t, functions=_functions)  # type: ignore
                _t.confirmed = False
                _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                _t.tool_call_error = True
            _t.requires_confirmation = False

        # Case 2: Handle external execution required tools
        elif _t.external_execution_required is not None and _t.external_execution_required is True:
            handle_external_execution_update(team, run_messages=run_messages, tool=_t)  # type: ignore

        # Case 3: Agentic user input required
        elif _t.tool_name == "get_user_input" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_get_user_input_tool_update(team, run_messages=run_messages, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True

        # Case 4: Handle user input required tools
        elif _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_user_input_update(team, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True
            deque(run_tool(team, run_response, run_messages, _t, functions=_functions), maxlen=0)  # type: ignore


def _handle_team_tool_call_updates_stream(
    team: "Team",
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    tools: List[Union[Function, dict]],
    stream_events: bool = False,
) -> Iterator[Union[TeamRunOutputEvent, RunOutputEvent]]:
    """Handle tool call updates for team-level tools (sync streaming).

    Mirrors agent's handle_tool_call_updates_stream but operates on team-level tools.
    Yields events during tool execution for streaming responses.
    """
    from agno.agent._tools import (
        handle_external_execution_update,
        handle_get_user_input_tool_update,
        handle_user_input_update,
        reject_tool_call,
        run_tool,
    )

    team.model = cast(Model, team.model)
    _functions = {tool.name: tool for tool in tools if isinstance(tool, Function)}

    for _t in run_response.tools or []:
        # Case 1: Handle confirmed tools and execute them
        if _t.requires_confirmation is not None and _t.requires_confirmation is True and _functions:
            if _t.confirmed is not None and _t.confirmed is True and _t.result is None:
                yield from run_tool(
                    team,  # type: ignore[arg-type]
                    run_response,  # type: ignore[arg-type]
                    run_messages,
                    _t,
                    functions=_functions,
                    stream_events=stream_events,  # type: ignore
                )
            else:
                reject_tool_call(team, run_messages, _t, functions=_functions)  # type: ignore
                _t.confirmed = False
                _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                _t.tool_call_error = True
            _t.requires_confirmation = False

        # Case 2: Handle external execution required tools
        elif _t.external_execution_required is not None and _t.external_execution_required is True:
            handle_external_execution_update(team, run_messages=run_messages, tool=_t)  # type: ignore

        # Case 3: Agentic user input required
        elif _t.tool_name == "get_user_input" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_get_user_input_tool_update(team, run_messages=run_messages, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True

        # Case 4: Handle user input required tools
        elif _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_user_input_update(team, tool=_t)  # type: ignore
            yield from run_tool(
                team,  # type: ignore[arg-type]
                run_response,  # type: ignore[arg-type]
                run_messages,
                _t,
                functions=_functions,
                stream_events=stream_events,  # type: ignore
            )
            _t.requires_user_input = False
            _t.answered = True


async def _ahandle_team_tool_call_updates(
    team: "Team",
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    tools: List[Union[Function, dict]],
) -> None:
    """Async version of _handle_team_tool_call_updates.

    See _handle_team_tool_call_updates docstring for the Team/Agent duck-typing note.
    """
    from agno.agent._tools import (
        arun_tool,
        handle_external_execution_update,
        handle_get_user_input_tool_update,
        handle_user_input_update,
        reject_tool_call,
    )

    team.model = cast(Model, team.model)
    _functions = {tool.name: tool for tool in tools if isinstance(tool, Function)}

    for _t in run_response.tools or []:
        if _t.requires_confirmation is not None and _t.requires_confirmation is True and _functions:
            if _t.confirmed is not None and _t.confirmed is True and _t.result is None:
                async for _ in arun_tool(team, run_response, run_messages, _t, functions=_functions):  # type: ignore
                    pass
            else:
                reject_tool_call(team, run_messages, _t, functions=_functions)  # type: ignore
                _t.confirmed = False
                _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                _t.tool_call_error = True
            _t.requires_confirmation = False

        elif _t.external_execution_required is not None and _t.external_execution_required is True:
            handle_external_execution_update(team, run_messages=run_messages, tool=_t)  # type: ignore

        elif _t.tool_name == "get_user_input" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_get_user_input_tool_update(team, run_messages=run_messages, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True

        elif _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_user_input_update(team, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True
            async for _ in arun_tool(team, run_response, run_messages, _t, functions=_functions):  # type: ignore
                pass


async def _ahandle_team_tool_call_updates_stream(
    team: "Team",
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    tools: List[Union[Function, dict]],
    stream_events: bool = False,
) -> AsyncIterator[Union[TeamRunOutputEvent, RunOutputEvent]]:
    """Async streaming version of _handle_team_tool_call_updates.

    Mirrors agent's ahandle_tool_call_updates_stream but operates on team-level tools.
    Yields events during tool execution for async streaming responses.
    """
    from agno.agent._tools import (
        arun_tool,
        handle_external_execution_update,
        handle_get_user_input_tool_update,
        handle_user_input_update,
        reject_tool_call,
    )

    team.model = cast(Model, team.model)
    _functions = {tool.name: tool for tool in tools if isinstance(tool, Function)}

    for _t in run_response.tools or []:
        # Case 1: Handle confirmed tools and execute them
        if _t.requires_confirmation is not None and _t.requires_confirmation is True and _functions:
            if _t.confirmed is not None and _t.confirmed is True and _t.result is None:
                async for event in arun_tool(
                    team,  # type: ignore[arg-type]
                    run_response,  # type: ignore[arg-type]
                    run_messages,
                    _t,
                    functions=_functions,
                    stream_events=stream_events,  # type: ignore
                ):
                    yield event  # type: ignore
            else:
                reject_tool_call(team, run_messages, _t, functions=_functions)  # type: ignore
                _t.confirmed = False
                _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                _t.tool_call_error = True
            _t.requires_confirmation = False

        # Case 2: Handle external execution required tools
        elif _t.external_execution_required is not None and _t.external_execution_required is True:
            handle_external_execution_update(team, run_messages=run_messages, tool=_t)  # type: ignore

        # Case 3: Agentic user input required
        elif _t.tool_name == "get_user_input" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_get_user_input_tool_update(team, run_messages=run_messages, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True

        # Case 4: Handle user input required tools
        elif _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_user_input_update(team, tool=_t)  # type: ignore
            async for event in arun_tool(
                team,  # type: ignore[arg-type]
                run_response,  # type: ignore[arg-type]
                run_messages,
                _t,
                functions=_functions,
                stream_events=stream_events,  # type: ignore
            ):
                yield event  # type: ignore
            _t.requires_user_input = False
            _t.answered = True


def _normalize_requirements_payload(
    requirements: List[Any],
) -> List[Any]:
    """Convert dicts in the requirements list to RunRequirement objects."""
    from agno.run.requirement import RunRequirement

    result = []
    for req in requirements:
        if isinstance(req, dict):
            result.append(RunRequirement.from_dict(req))
        else:
            result.append(req)
    return result


def _has_member_requirements(requirements: List[Any]) -> bool:
    """Check if any requirements are for member agents (have member_agent_id set)."""
    return any(getattr(req, "member_agent_id", None) is not None for req in requirements)


def _has_team_level_requirements(requirements: List[Any]) -> bool:
    """Check if any requirements are for team-level tools (no member_agent_id)."""
    return any(getattr(req, "member_agent_id", None) is None for req in requirements)


def _route_requirements_to_members(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> List[str]:
    """Route member requirements back to the appropriate member agents (sync).

    Groups requirements by member_agent_id, calls member.continue_run() for each,
    and returns a list of result descriptions for building a continuation message.

    Returns:
        List of member result strings.
    """
    from agno.run.requirement import RunRequirement
    from agno.team._tools import _find_member_route_by_id

    # Group requirements by member
    member_reqs: Dict[str, List[RunRequirement]] = {}
    for req in run_response.requirements or []:
        mid = getattr(req, "member_agent_id", None)
        if mid is not None:
            member_reqs.setdefault(mid, []).append(req)

    member_results: List[str] = []

    for member_id, reqs in member_reqs.items():
        route_result = _find_member_route_by_id(team, member_id, run_context=run_context)
        if route_result is None:
            log_warning(f"Could not find member with ID {member_id} for continue_run routing")
            member_results.append(f"[{member_id}]: Could not route requirement — member not found")
            continue

        _, member = route_result

        # Get the member's paused RunOutput from the requirement.
        # This is stored by _propagate_member_pause and avoids needing a
        # session/DB lookup (which fails without a database since
        # initialize_team clears the cached session).
        member_run_output = getattr(reqs[0], "_member_run_response", None)

        if member_run_output is not None:
            # Update requirements and tool executions on the member's run output
            member_run_output.requirements = reqs
            updated_tools = [req.tool_execution for req in reqs if req.tool_execution is not None]
            if updated_tools and member_run_output.tools:
                updated_map = {t.tool_call_id: t for t in updated_tools}
                member_run_output.tools = [updated_map.get(t.tool_call_id, t) for t in member_run_output.tools]

            member_response = member.continue_run(
                run_response=member_run_output,
                session_id=session.session_id,
            )
        else:
            # Fallback: use run_id (requires DB or cached session)
            member_run_id = reqs[0].member_run_id if reqs else None
            member_response = member.continue_run(
                run_id=member_run_id,
                requirements=reqs,
                session_id=session.session_id,
            )

        # Check if member is still paused (chained HITL)
        if getattr(member_response, "is_paused", False):
            from agno.team._tools import _propagate_member_pause

            _propagate_member_pause(run_response, member, member_response)
        else:
            content = getattr(member_response, "content", None) or "Task completed"
            member_results.append(f"[{member.name or member_id}]: {content}")

        # Clear _member_run_response references to allow GC of the member RunOutput
        for req in reqs:
            req._member_run_response = None

    return member_results


async def _aroute_requirements_to_members(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> List[str]:
    """Route member requirements back to the appropriate member agents (async).

    Runs member continue_run() calls concurrently with asyncio.gather.

    Returns:
        List of member result strings.
    """
    from agno.run.requirement import RunRequirement
    from agno.team._tools import _find_member_route_by_id

    # Group requirements by member
    member_reqs: Dict[str, List[RunRequirement]] = {}
    for req in run_response.requirements or []:
        mid = getattr(req, "member_agent_id", None)
        if mid is not None:
            member_reqs.setdefault(mid, []).append(req)

    if not member_reqs:
        return []

    async def _continue_member(member_id: str, reqs: List[RunRequirement]) -> Optional[str]:
        route_result = _find_member_route_by_id(team, member_id, run_context=run_context)
        if route_result is None:
            log_warning(f"Could not find member with ID {member_id} for continue_run routing")
            return f"[{member_id}]: Could not route requirement — member not found"

        _, member = route_result
        # Get the member's paused RunOutput from the requirement
        member_run_output = getattr(reqs[0], "_member_run_response", None)

        if member_run_output is not None:
            member_run_output.requirements = reqs
            updated_tools = [req.tool_execution for req in reqs if req.tool_execution is not None]
            if updated_tools and member_run_output.tools:
                updated_map = {t.tool_call_id: t for t in updated_tools}
                member_run_output.tools = [updated_map.get(t.tool_call_id, t) for t in member_run_output.tools]

            member_response = await member.acontinue_run(  # type: ignore[misc]
                run_response=member_run_output,
                session_id=session.session_id,
            )
        else:
            member_run_id = reqs[0].member_run_id if reqs else None
            member_response = await member.acontinue_run(  # type: ignore[misc]
                run_id=member_run_id,
                requirements=reqs,
                session_id=session.session_id,
            )

        # Clear _member_run_response references to allow GC of the member RunOutput
        for req in reqs:
            req._member_run_response = None

        if getattr(member_response, "is_paused", False):
            from agno.team._tools import _propagate_member_pause

            _propagate_member_pause(run_response, member, member_response)
            return None
        else:
            content = getattr(member_response, "content", None) or "Task completed"
            return f"[{member.name or member_id}]: {content}"

    tasks = [_continue_member(mid, reqs) for mid, reqs in member_reqs.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    member_results: List[str] = []
    for r in results:
        if isinstance(r, BaseException):
            log_warning(f"Member continue_run failed: {r}")
        elif isinstance(r, str):
            member_results.append(r)
    return member_results


def _build_continuation_message(member_results: List[str]) -> str:
    """Build a user message from member results to feed back into the team model."""
    if not member_results:
        return "The delegated task has been completed."
    parts = ["Member results after human-in-the-loop resolution:"]
    parts.extend(member_results)
    return "\n".join(parts)


def continue_run_dispatch(
    team: "Team",
    run_response: Optional[TeamRunOutput] = None,
    *,
    run_id: Optional[str] = None,
    requirements: Optional[List[Any]] = None,
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
    **kwargs: Any,
) -> Union[TeamRunOutput, Iterator[Union[TeamRunOutputEvent, RunOutputEvent, TeamRunOutput]]]:
    """Continue a paused team run (sync).

    Handles both team-level tool pauses and member-agent tool pauses.
    """
    from agno.team._init import _has_async_db, _initialize_session
    from agno.team._response import get_response_format
    from agno.team._run_options import resolve_run_options
    from agno.team._storage import _load_session_state, _read_or_create_session, _update_metadata
    from agno.team._tools import _determine_tools_for_model

    if run_response is None and run_id is None:
        raise ValueError("Either run_response or run_id must be provided.")

    if run_response is None and (run_id is not None and (session_id is None and team.session_id is None)):
        raise ValueError("Session ID is required to continue a run from a run_id.")

    if _has_async_db(team):
        raise Exception("continue_run() is not supported with an async DB. Please use acontinue_run() instead.")

    background_tasks = kwargs.pop("background_tasks", None)
    if background_tasks is not None:
        from fastapi import BackgroundTasks

        background_tasks: BackgroundTasks = background_tasks  # type: ignore

    session_id = run_response.session_id if run_response else session_id
    run_id_resolved: str = run_response.run_id if run_response else run_id  # type: ignore

    session_id, user_id = _initialize_session(team, session_id=session_id, user_id=user_id)

    # Initialize the Team
    team.initialize_team(debug_mode=debug_mode)

    # Read existing session from storage
    team_session = _read_or_create_session(team, session_id=session_id, user_id=user_id)
    _update_metadata(team, session=team_session)

    # Load session state
    session_state = _load_session_state(team, session=team_session, session_state={})

    # Resolve run options
    opts = resolve_run_options(
        team,
        stream=stream,
        stream_events=stream_events,
        yield_run_output=yield_run_output,
        dependencies=dependencies,
        knowledge_filters=knowledge_filters,
        metadata=metadata,
    )

    # Initialize run context
    run_context = run_context or RunContext(
        run_id=run_id_resolved,
        session_id=session_id,
        user_id=user_id,
        session_state=session_state,
        dependencies=opts.dependencies,
        knowledge_filters=opts.knowledge_filters,
        metadata=opts.metadata,
    )
    if dependencies is not None:
        run_context.dependencies = opts.dependencies
    elif run_context.dependencies is None:
        run_context.dependencies = opts.dependencies
    if knowledge_filters is not None:
        run_context.knowledge_filters = opts.knowledge_filters
    elif run_context.knowledge_filters is None:
        run_context.knowledge_filters = opts.knowledge_filters
    if metadata is not None:
        run_context.metadata = opts.metadata
    elif run_context.metadata is None:
        run_context.metadata = opts.metadata

    # Resolve dependencies
    if run_context.dependencies is not None:
        _resolve_run_dependencies(team, run_context=run_context)

    # Resolve run_response from run_id if needed
    if run_response is None and run_id is not None:
        if requirements is None:
            raise ValueError("To continue a run from a given run_id, the requirements parameter must be provided.")

        runs = team_session.runs or []
        run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
        if run_response is None:
            raise RuntimeError(f"No runs found for run ID {run_id}")

    run_response = cast(TeamRunOutput, run_response)

    # Normalize and apply requirements
    if requirements is not None:
        requirements = _normalize_requirements_payload(requirements)
        run_response.requirements = requirements
        # Update tools from requirements
        updated_tools = [req.tool_execution for req in requirements if req.tool_execution is not None]
        if updated_tools and run_response.tools:
            updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
            run_response.tools = [updated_tools_map.get(tool.tool_call_id, tool) for tool in run_response.tools]
        elif updated_tools:
            run_response.tools = updated_tools

    # Determine what kind of pause we're continuing from
    has_member = _has_member_requirements(run_response.requirements or [])
    has_team_level = _has_team_level_requirements(run_response.requirements or [])

    # Route member requirements to member agents
    member_results: List[str] = []
    if has_member:
        member_reqs = [r for r in (run_response.requirements or []) if getattr(r, "member_agent_id", None) is not None]
        team_level_reqs = [r for r in (run_response.requirements or []) if getattr(r, "member_agent_id", None) is None]
        # Set only member reqs for routing; _route_requirements_to_members
        # may append newly propagated reqs via _propagate_member_pause (chained HITL).
        original_member_req_ids = {id(r) for r in member_reqs}
        run_response.requirements = member_reqs
        member_results = _route_requirements_to_members(
            team, run_response=run_response, session=team_session, run_context=run_context
        )
        # Merge: keep team-level reqs + any newly propagated member reqs (chained HITL)
        newly_propagated = [r for r in (run_response.requirements or []) if id(r) not in original_member_req_ids]
        run_response.requirements = team_level_reqs + newly_propagated

        # Check if any members are still paused
        if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
            from agno.team import _hooks

            if opts.stream:
                return _hooks.handle_team_run_paused_stream(team, run_response=run_response, session=team_session)  # type: ignore
            else:
                return _hooks.handle_team_run_paused(team, run_response=run_response, session=team_session)

    # Handle team-level tool resolution
    if has_team_level:
        # Guard: if team-level requirements are unresolved, re-pause instead of auto-rejecting
        unresolved_team = [
            r
            for r in (run_response.requirements or [])
            if getattr(r, "member_agent_id", None) is None and not r.is_resolved()
        ]
        if unresolved_team:
            from agno.team import _hooks

            if opts.stream:
                return _hooks.handle_team_run_paused_stream(team, run_response=run_response, session=team_session)  # type: ignore
            else:
                return _hooks.handle_team_run_paused(team, run_response=run_response, session=team_session)

        response_format = get_response_format(team, run_context=run_context) if team.parser_model is None else None
        team.model = cast(Model, team.model)

        # Prepare tools
        team_run_context: Dict[str, Any] = {}
        _tools = _determine_tools_for_model(
            team,
            model=team.model,
            run_response=run_response,
            run_context=run_context,
            team_run_context=team_run_context,
            session=team_session,
            user_id=user_id,
            async_mode=False,
            stream=opts.stream or False,
            stream_events=opts.stream_events or False,
        )

        # Get continue run messages from existing conversation
        input_messages = run_response.messages or []
        run_messages = _get_continue_run_messages(team, input=input_messages)

        # Handle tool call updates (execute confirmed tools, etc.)
        _handle_team_tool_call_updates(team, run_response=run_response, run_messages=run_messages, tools=_tools)

        # Reset run state for continuation
        run_response.status = RunStatus.running
        # Reset content before re-running the model; _update_run_response appends
        # to existing content, so stale content from the paused run must be cleared.
        run_response.content = None

        log_debug(f"Team Continue Run Start: {run_response.run_id}", center=True)

        if opts.stream:
            return _continue_run_stream(
                team,
                run_response=run_response,
                run_messages=run_messages,
                run_context=run_context,
                tools=_tools,
                session=team_session,
                user_id=user_id,
                response_format=response_format,
                stream_events=opts.stream_events,
                yield_run_output=opts.yield_run_output,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )
        else:
            return _continue_run(
                team,
                run_response=run_response,
                run_messages=run_messages,
                run_context=run_context,
                tools=_tools,
                session=team_session,
                user_id=user_id,
                response_format=response_format,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )

    # Member-only case: re-run team model with member results
    if member_results and not has_team_level:
        continuation_message = _build_continuation_message(member_results)

        # Mark original paused run as completed before starting a fresh run
        run_response.status = RunStatus.completed
        _cleanup_and_store(team, run_response=run_response, session=team_session)

        if opts.stream:
            return team.run(  # type: ignore
                input=continuation_message,
                stream=True,
                stream_events=opts.stream_events,
                session_id=session_id,
                user_id=user_id,
                knowledge_filters=knowledge_filters,
                dependencies=dependencies,
                metadata=metadata,
                debug_mode=debug_mode,
                **kwargs,
            )
        else:
            return team.run(
                input=continuation_message,
                stream=False,
                session_id=session_id,
                user_id=user_id,
                knowledge_filters=knowledge_filters,
                dependencies=dependencies,
                metadata=metadata,
                debug_mode=debug_mode,
                **kwargs,
            )

    # Fallback: nothing to do
    run_response.status = RunStatus.completed
    _cleanup_and_store(team, run_response=run_response, session=team_session)
    return run_response


def _continue_run(
    team: "Team",
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    run_context: RunContext,
    tools: List[Union[Function, dict]],
    session: TeamSession,
    user_id: Optional[str] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> TeamRunOutput:
    """Continue a paused team run (sync, non-streaming).

    Steps:
    1. Generate response from model (includes running tool calls)
    2. Update TeamRunOutput with model response
    3. Check for new pauses
    4. Convert response to structured format
    5. Create session summary
    6. Cleanup and store
    """
    from agno.team._hooks import _execute_post_hooks
    from agno.team._init import _disconnect_connectable_tools
    from agno.team._response import (
        _convert_response_to_structured_format,
        _update_run_response,
        parse_response_with_output_model,
        parse_response_with_parser_model,
    )
    from agno.team._telemetry import log_team_telemetry
    from agno.utils.events import create_team_run_continued_event

    register_run(run_response.run_id)  # type: ignore

    # Emit RunContinued event (matching streaming variant behaviour)
    handle_event(
        create_team_run_continued_event(run_response),
        run_response,
        events_to_skip=team.events_to_skip,
        store_events=team.store_events,
    )

    team.model = cast(Model, team.model)

    try:
        num_attempts = team.retries + 1
        for attempt in range(num_attempts):
            try:
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # Generate model response
                model_response: ModelResponse = team.model.response(
                    messages=run_messages.messages,
                    response_format=response_format,
                    tools=tools,
                    tool_choice=team.tool_choice,
                    tool_call_limit=team.tool_call_limit,
                    run_response=run_response,
                    send_media_to_model=team.send_media_to_model,
                    compression_manager=team.compression_manager if team.compress_tool_results else None,
                )

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # Parse with output/parser models if needed
                parse_response_with_output_model(team, model_response, run_messages)
                parse_response_with_parser_model(team, model_response, run_messages, run_context=run_context)

                # Update run response
                _update_run_response(
                    team,
                    model_response=model_response,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                )

                # Check for new pauses (team-level tools or member propagation)
                if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                    from agno.team import _hooks

                    return _hooks.handle_team_run_paused(team, run_response=run_response, session=session)

                # Convert to structured format
                _convert_response_to_structured_format(team, run_response=run_response, run_context=run_context)

                # Store media
                if team.store_media:
                    store_media_util(run_response, model_response)

                # Execute post-hooks
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

                # Create session summary
                if team.session_summary_manager is not None:
                    session.upsert_run(run_response=run_response)
                    try:
                        team.session_summary_manager.create_session_summary(session=session)
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                # Complete
                run_response.status = RunStatus.completed
                _cleanup_and_store(team, run_response=run_response, session=session)

                log_team_telemetry(team, session_id=session.session_id, run_id=run_response.run_id)
                log_debug(f"Team Continue Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response

            except RunCancelledException as e:
                log_info(f"Team run {run_response.run_id} was cancelled")
                run_response.status = RunStatus.cancelled
                run_response.content = str(e)
                _cleanup_and_store(team, run_response=run_response, session=session)
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
                _cleanup_and_store(team, run_response=run_response, session=session)
                return run_response

            except KeyboardInterrupt:
                run_response.status = RunStatus.cancelled
                run_response.content = "Operation cancelled by user"
                return run_response

            except Exception as e:
                if attempt < num_attempts - 1:
                    import time as _time

                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries
                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                    _time.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                run_error = create_team_run_error_event(run_response, error=str(e))
                run_response.events = add_team_error_event(error=run_error, events=run_response.events)
                if run_response.content is None:
                    run_response.content = str(e)
                log_error(f"Error in Team continue_run: {str(e)}")
                _cleanup_and_store(team, run_response=run_response, session=session)
                return run_response
    finally:
        _disconnect_connectable_tools(team)
        cleanup_run(run_response.run_id)  # type: ignore
    return run_response


def _continue_run_stream(
    team: "Team",
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    run_context: RunContext,
    tools: List[Union[Function, dict]],
    session: TeamSession,
    user_id: Optional[str] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    stream_events: bool = False,
    yield_run_output: bool = False,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> Iterator[Union[TeamRunOutputEvent, RunOutputEvent, TeamRunOutput]]:
    """Continue a paused team run (sync, streaming)."""
    from agno.team._hooks import _execute_post_hooks
    from agno.team._init import _disconnect_connectable_tools
    from agno.team._response import (
        _handle_model_response_stream,
        generate_response_with_output_model_stream,
        parse_response_with_parser_model_stream,
    )
    from agno.team._telemetry import log_team_telemetry
    from agno.utils.events import create_team_run_continued_event

    register_run(run_response.run_id)  # type: ignore

    try:
        num_attempts = team.retries + 1
        for attempt in range(num_attempts):
            try:
                # Yield RunContinued event
                if stream_events:
                    yield handle_event(
                        create_team_run_continued_event(run_response),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # Handle the updated tools (execute confirmed tools, etc.) with streaming
                yield from _handle_team_tool_call_updates_stream(
                    team,
                    run_response=run_response,
                    run_messages=run_messages,
                    tools=tools,
                    stream_events=stream_events,
                )

                # Stream model response
                if team.output_model is None:
                    for event in _handle_model_response_stream(
                        team,
                        session=session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        session_state=run_context.session_state,
                        run_context=run_context,
                    ):
                        raise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event
                else:
                    from agno.run.team import IntermediateRunContentEvent, RunContentEvent

                    for event in _handle_model_response_stream(
                        team,
                        session=session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=tools,
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

                    for event in generate_response_with_output_model_stream(
                        team,
                        session=session,
                        run_response=run_response,
                        run_messages=run_messages,
                        stream_events=stream_events,
                    ):
                        raise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # Check for new pauses
                if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                    from agno.team import _hooks

                    yield from _hooks.handle_team_run_paused_stream(team, run_response=run_response, session=session)
                    if yield_run_output:
                        yield run_response
                    return

                # Parse response with parser model
                yield from parse_response_with_parser_model_stream(
                    team,
                    session=session,
                    run_response=run_response,
                    stream_events=stream_events,
                    run_context=run_context,
                )

                # Content completed event
                if stream_events:
                    yield handle_event(
                        create_team_run_content_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )

                # Post-hooks
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
                    for hook_event in iterator:
                        yield hook_event

                # Session summary
                if team.session_summary_manager is not None:
                    session.upsert_run(run_response=run_response)
                    if stream_events:
                        yield handle_event(
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
                        yield handle_event(
                            create_team_session_summary_completed_event(
                                from_run_response=run_response, session_summary=session.summary
                            ),
                            run_response,
                            events_to_skip=team.events_to_skip,
                            store_events=team.store_events,
                        )

                # Completed event
                completed_event = handle_event(
                    create_team_run_completed_event(run_response),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

                run_response.status = RunStatus.completed
                _cleanup_and_store(team, run_response=run_response, session=session)

                if stream_events:
                    yield completed_event

                if yield_run_output:
                    yield run_response

                log_team_telemetry(team, session_id=session.session_id, run_id=run_response.run_id)
                log_debug(f"Team Continue Run End: {run_response.run_id}", center=True, symbol="*")
                break

            except RunCancelledException as e:
                log_info(f"Team run {run_response.run_id} was cancelled")
                run_response.status = RunStatus.cancelled
                if not run_response.content:
                    run_response.content = str(e)
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
                yield run_error
                break

            except KeyboardInterrupt:
                yield handle_event(
                    create_team_run_cancelled_event(
                        from_run_response=run_response, reason="Operation cancelled by user"
                    ),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )
                break

            except Exception as e:
                if attempt < num_attempts - 1:
                    import time as _time

                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries
                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed: {str(e)}. Retrying in {delay}s...")
                    _time.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                run_error = create_team_run_error_event(run_response, error=str(e))
                run_response.events = add_team_error_event(error=run_error, events=run_response.events)
                if run_response.content is None:
                    run_response.content = str(e)
                log_error(f"Error in Team continue_run stream: {str(e)}")
                _cleanup_and_store(team, run_response=run_response, session=session)
                yield run_error
    finally:
        _disconnect_connectable_tools(team)
        cleanup_run(run_response.run_id)  # type: ignore


def acontinue_run_dispatch(  # type: ignore
    team: "Team",
    run_response: Optional[TeamRunOutput] = None,
    *,
    run_id: Optional[str] = None,
    requirements: Optional[List[Any]] = None,
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
    **kwargs: Any,
) -> Union[TeamRunOutput, AsyncIterator[Union[TeamRunOutputEvent, RunOutputEvent, TeamRunOutput]]]:
    """Continue a paused team run (async entry point).

    Routes to _acontinue_run or _acontinue_run_stream based on stream option.
    """
    from agno.team._init import _initialize_session
    from agno.team._response import get_response_format
    from agno.team._run_options import resolve_run_options

    if run_response is None and run_id is None:
        raise ValueError("Either run_response or run_id must be provided.")

    if run_response is None and (run_id is not None and (session_id is None and team.session_id is None)):
        raise ValueError("Session ID is required to continue a run from a run_id.")

    background_tasks = kwargs.pop("background_tasks", None)
    if background_tasks is not None:
        from fastapi import BackgroundTasks

        background_tasks: BackgroundTasks = background_tasks  # type: ignore

    session_id_resolved = run_response.session_id if run_response else session_id
    run_id_resolved: str = run_response.run_id if run_response else run_id  # type: ignore

    session_id_resolved, user_id = _initialize_session(team, session_id=session_id_resolved, user_id=user_id)

    # Initialize the Team
    team.initialize_team(debug_mode=debug_mode)

    # Resolve run options
    opts = resolve_run_options(
        team,
        stream=stream,
        stream_events=stream_events,
        yield_run_output=yield_run_output,
        dependencies=dependencies,
        knowledge_filters=knowledge_filters,
        metadata=metadata,
    )

    # Initialize run context
    run_context = run_context or RunContext(
        run_id=run_id_resolved,
        session_id=session_id_resolved,
        user_id=user_id,
        session_state={},
        dependencies=opts.dependencies,
        knowledge_filters=opts.knowledge_filters,
        metadata=opts.metadata,
    )
    if dependencies is not None:
        run_context.dependencies = opts.dependencies
    elif run_context.dependencies is None:
        run_context.dependencies = opts.dependencies
    if knowledge_filters is not None:
        run_context.knowledge_filters = opts.knowledge_filters
    elif run_context.knowledge_filters is None:
        run_context.knowledge_filters = opts.knowledge_filters
    if metadata is not None:
        run_context.metadata = opts.metadata
    elif run_context.metadata is None:
        run_context.metadata = opts.metadata

    response_format = get_response_format(team, run_context=run_context) if team.parser_model is None else None

    if opts.stream:
        return _acontinue_run_stream(
            team,
            run_response=run_response,
            run_context=run_context,
            requirements=requirements,
            run_id=run_id_resolved,
            user_id=user_id,
            session_id=session_id_resolved,
            response_format=response_format,
            stream_events=opts.stream_events,
            yield_run_output=opts.yield_run_output,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )
    else:
        return _acontinue_run(  # type: ignore
            team,
            run_response=run_response,
            run_context=run_context,
            requirements=requirements,
            run_id=run_id_resolved,
            user_id=user_id,
            session_id=session_id_resolved,
            response_format=response_format,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )


async def _acontinue_run(
    team: "Team",
    session_id: str,
    run_context: RunContext,
    run_response: Optional[TeamRunOutput] = None,
    requirements: Optional[List[Any]] = None,
    run_id: Optional[str] = None,
    user_id: Optional[str] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> TeamRunOutput:
    """Continue a paused team run (async, non-streaming)."""
    from agno.team._hooks import _aexecute_post_hooks
    from agno.team._init import _disconnect_connectable_tools, _disconnect_mcp_tools
    from agno.team._response import (
        _convert_response_to_structured_format,
        _update_run_response,
        agenerate_response_with_output_model,
        aparse_response_with_parser_model,
    )
    from agno.team._telemetry import alog_team_telemetry
    from agno.team._tools import _check_and_refresh_mcp_tools, _determine_tools_for_model

    log_debug(f"Team Continue Run: {run_response.run_id if run_response else run_id}", center=True)

    team_session: Optional[TeamSession] = None

    try:
        num_attempts = team.retries + 1
        for attempt in range(num_attempts):
            try:
                # Setup session
                team_session = await _asetup_session(
                    team=team,
                    run_context=run_context,
                    session_id=session_id,
                    user_id=user_id,
                    run_id=run_id,
                )

                # Resolve run_response from run_id if needed
                if run_response is None and run_id is not None:
                    if requirements is None:
                        raise ValueError("Requirements are required to continue a run from a run_id.")

                    runs = team_session.runs or []
                    run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
                    if run_response is None:
                        raise RuntimeError(f"No runs found for run ID {run_id}")

                run_response = cast(TeamRunOutput, run_response)

                # Normalize and apply requirements
                if requirements is not None:
                    requirements = _normalize_requirements_payload(requirements)
                    run_response.requirements = requirements
                    updated_tools = [req.tool_execution for req in requirements if req.tool_execution is not None]
                    if updated_tools and run_response.tools:
                        updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
                        run_response.tools = [
                            updated_tools_map.get(tool.tool_call_id, tool) for tool in run_response.tools
                        ]
                    elif updated_tools:
                        run_response.tools = updated_tools

                await aregister_run(run_response.run_id)  # type: ignore

                # Emit RunContinued event (matching streaming variant behaviour)
                from agno.utils.events import create_team_run_continued_event

                handle_event(
                    create_team_run_continued_event(run_response),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

                has_member = _has_member_requirements(run_response.requirements or [])
                has_team_level = _has_team_level_requirements(run_response.requirements or [])

                # Route member requirements
                member_results: List[str] = []
                if has_member:
                    member_reqs = [
                        r for r in (run_response.requirements or []) if getattr(r, "member_agent_id", None) is not None
                    ]
                    team_level_reqs = [
                        r for r in (run_response.requirements or []) if getattr(r, "member_agent_id", None) is None
                    ]
                    original_member_req_ids = {id(r) for r in member_reqs}
                    run_response.requirements = member_reqs
                    member_results = await _aroute_requirements_to_members(
                        team, run_response=run_response, session=team_session, run_context=run_context
                    )
                    # Merge: keep team-level reqs + any newly propagated member reqs (chained HITL)
                    newly_propagated = [
                        r for r in (run_response.requirements or []) if id(r) not in original_member_req_ids
                    ]
                    run_response.requirements = team_level_reqs + newly_propagated

                    # Check if still paused
                    if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                        from agno.team import _hooks

                        return await _hooks.ahandle_team_run_paused(
                            team, run_response=run_response, session=team_session
                        )

                # Handle team-level tool resolution
                if has_team_level:
                    # Guard: if team-level requirements are unresolved, re-pause instead of auto-rejecting
                    unresolved_team = [
                        r
                        for r in (run_response.requirements or [])
                        if getattr(r, "member_agent_id", None) is None and not r.is_resolved()
                    ]
                    if unresolved_team:
                        from agno.team import _hooks

                        return await _hooks.ahandle_team_run_paused(
                            team, run_response=run_response, session=team_session
                        )

                    team.model = cast(Model, team.model)
                    await _check_and_refresh_mcp_tools(team)

                    team_run_context: Dict[str, Any] = {}
                    _tools = _determine_tools_for_model(
                        team,
                        model=team.model,
                        run_response=run_response,
                        run_context=run_context,
                        team_run_context=team_run_context,
                        session=team_session,
                        user_id=user_id,
                        async_mode=True,
                    )

                    input_messages = run_response.messages or []
                    run_messages = _get_continue_run_messages(team, input=input_messages)

                    await _ahandle_team_tool_call_updates(
                        team, run_response=run_response, run_messages=run_messages, tools=_tools
                    )

                    run_response.status = RunStatus.running
                    run_response.content = None

                    # Get model response
                    model_response: ModelResponse = await team.model.aresponse(
                        messages=run_messages.messages,
                        response_format=response_format,
                        tools=_tools,
                        tool_choice=team.tool_choice,
                        tool_call_limit=team.tool_call_limit,
                        run_response=run_response,
                        send_media_to_model=team.send_media_to_model,
                        compression_manager=team.compression_manager if team.compress_tool_results else None,
                    )

                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    await agenerate_response_with_output_model(team, model_response, run_messages)
                    await aparse_response_with_parser_model(team, model_response, run_messages, run_context=run_context)

                    _update_run_response(
                        team,
                        model_response=model_response,
                        run_response=run_response,
                        run_messages=run_messages,
                        run_context=run_context,
                    )

                    # Check for new pauses
                    if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                        from agno.team import _hooks

                        return await _hooks.ahandle_team_run_paused(
                            team, run_response=run_response, session=team_session
                        )

                    _convert_response_to_structured_format(team, run_response=run_response, run_context=run_context)

                    if team.store_media:
                        store_media_util(run_response, model_response)

                elif member_results:
                    # Member-only: re-run team with results
                    continuation_message = _build_continuation_message(member_results)

                    # Mark original paused run as completed before starting a fresh run
                    run_response.status = RunStatus.completed
                    if team_session is not None:
                        await _acleanup_and_store(team, run_response=run_response, session=team_session)

                    result = await team.arun(  # type: ignore[misc]
                        input=continuation_message,
                        stream=False,
                        session_id=session_id,
                        user_id=user_id,
                        knowledge_filters=run_context.knowledge_filters,
                        dependencies=run_context.dependencies,
                        metadata=run_context.metadata,
                        debug_mode=debug_mode,
                        **kwargs,
                    )
                    return result  # type: ignore

                # Post-hooks
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

                # Session summary
                if team.session_summary_manager is not None:
                    team_session.upsert_run(run_response=run_response)
                    try:
                        await team.session_summary_manager.acreate_session_summary(session=team_session)
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                run_response.status = RunStatus.completed
                await _acleanup_and_store(team, run_response=run_response, session=team_session)
                await alog_team_telemetry(team, session_id=team_session.session_id, run_id=run_response.run_id)
                log_debug(f"Team Continue Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response

            except RunCancelledException as e:
                if run_response is None:
                    run_response = TeamRunOutput(run_id=run_id)
                run_response = cast(TeamRunOutput, run_response)
                log_info(f"Team run {run_response.run_id} was cancelled")
                run_response.status = RunStatus.cancelled
                run_response.content = str(e)
                if team_session is not None:
                    await _acleanup_and_store(team, run_response=run_response, session=team_session)
                return run_response

            except (InputCheckError, OutputCheckError) as e:
                run_response = cast(TeamRunOutput, run_response)
                run_response.status = RunStatus.error
                if run_response.content is None:
                    run_response.content = str(e)
                log_error(f"Validation failed: {str(e)} | Check: {e.check_trigger}")
                if team_session is not None:
                    await _acleanup_and_store(team, run_response=run_response, session=team_session)
                return run_response

            except KeyboardInterrupt:
                run_response = cast(TeamRunOutput, run_response)
                run_response.status = RunStatus.cancelled
                run_response.content = "Operation cancelled by user"
                return run_response

            except Exception as e:
                run_response = cast(TeamRunOutput, run_response)
                if attempt < num_attempts - 1:
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
                log_error(f"Error in Team acontinue_run: {str(e)}")
                if team_session is not None:
                    await _acleanup_and_store(team, run_response=run_response, session=team_session)
                return run_response

    finally:
        _disconnect_connectable_tools(team)
        await _disconnect_mcp_tools(team)  # type: ignore
        if run_response and run_response.run_id:
            await acleanup_run(run_response.run_id)
    return run_response  # type: ignore


async def _acontinue_run_stream(
    team: "Team",
    session_id: str,
    run_context: RunContext,
    run_response: Optional[TeamRunOutput] = None,
    requirements: Optional[List[Any]] = None,
    run_id: Optional[str] = None,
    user_id: Optional[str] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    stream_events: bool = False,
    yield_run_output: bool = False,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> AsyncIterator[Union[TeamRunOutputEvent, RunOutputEvent, TeamRunOutput]]:
    """Continue a paused team run (async, streaming)."""
    from agno.team._hooks import _aexecute_post_hooks
    from agno.team._init import _disconnect_connectable_tools, _disconnect_mcp_tools
    from agno.team._response import (
        _ahandle_model_response_stream,
        agenerate_response_with_output_model_stream,
        aparse_response_with_parser_model_stream,
    )
    from agno.team._telemetry import alog_team_telemetry
    from agno.team._tools import _check_and_refresh_mcp_tools, _determine_tools_for_model
    from agno.utils.events import create_team_run_continued_event

    log_debug(f"Team Continue Run Stream: {run_response.run_id if run_response else run_id}", center=True)

    team_session: Optional[TeamSession] = None

    try:
        num_attempts = team.retries + 1
        for attempt in range(num_attempts):
            try:
                # Setup session
                team_session = await _asetup_session(
                    team=team,
                    run_context=run_context,
                    session_id=session_id,
                    user_id=user_id,
                    run_id=run_id,
                )

                # Resolve run_response from run_id if needed
                if run_response is None and run_id is not None:
                    if requirements is None:
                        raise ValueError("Requirements are required to continue a run from a run_id.")
                    runs = team_session.runs or []
                    run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
                    if run_response is None:
                        raise RuntimeError(f"No runs found for run ID {run_id}")

                run_response = cast(TeamRunOutput, run_response)

                # Normalize and apply requirements
                if requirements is not None:
                    requirements = _normalize_requirements_payload(requirements)
                    run_response.requirements = requirements
                    updated_tools = [req.tool_execution for req in requirements if req.tool_execution is not None]
                    if updated_tools and run_response.tools:
                        updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
                        run_response.tools = [
                            updated_tools_map.get(tool.tool_call_id, tool) for tool in run_response.tools
                        ]
                    elif updated_tools:
                        run_response.tools = updated_tools

                await aregister_run(run_response.run_id)  # type: ignore

                has_member = _has_member_requirements(run_response.requirements or [])
                has_team_level = _has_team_level_requirements(run_response.requirements or [])

                # Route member requirements
                member_results: List[str] = []
                if has_member:
                    member_reqs = [
                        r for r in (run_response.requirements or []) if getattr(r, "member_agent_id", None) is not None
                    ]
                    team_level_reqs = [
                        r for r in (run_response.requirements or []) if getattr(r, "member_agent_id", None) is None
                    ]
                    original_member_req_ids = {id(r) for r in member_reqs}
                    run_response.requirements = member_reqs
                    member_results = await _aroute_requirements_to_members(
                        team, run_response=run_response, session=team_session, run_context=run_context
                    )
                    # Merge: keep team-level reqs + any newly propagated member reqs (chained HITL)
                    newly_propagated = [
                        r for r in (run_response.requirements or []) if id(r) not in original_member_req_ids
                    ]
                    run_response.requirements = team_level_reqs + newly_propagated

                    if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                        from agno.team import _hooks

                        async for item in _hooks.ahandle_team_run_paused_stream(
                            team, run_response=run_response, session=team_session
                        ):
                            yield item
                        if yield_run_output:
                            yield run_response
                        return

                if has_team_level:
                    # Guard: if team-level requirements are unresolved, re-pause instead of auto-rejecting
                    unresolved_team = [
                        r
                        for r in (run_response.requirements or [])
                        if getattr(r, "member_agent_id", None) is None and not r.is_resolved()
                    ]
                    if unresolved_team:
                        from agno.team import _hooks

                        async for item in _hooks.ahandle_team_run_paused_stream(
                            team, run_response=run_response, session=team_session
                        ):
                            yield item
                        if yield_run_output:
                            yield run_response
                        return

                    team.model = cast(Model, team.model)
                    await _check_and_refresh_mcp_tools(team)

                    team_run_context: Dict[str, Any] = {}
                    _tools = _determine_tools_for_model(
                        team,
                        model=team.model,
                        run_response=run_response,
                        run_context=run_context,
                        team_run_context=team_run_context,
                        session=team_session,
                        user_id=user_id,
                        async_mode=True,
                        stream=True,
                        stream_events=stream_events,
                    )

                    input_messages = run_response.messages or []
                    run_messages = _get_continue_run_messages(team, input=input_messages)

                    run_response.status = RunStatus.running
                    run_response.content = None

                    # Yield RunContinued event
                    if stream_events:
                        yield handle_event(
                            create_team_run_continued_event(run_response),
                            run_response,
                            events_to_skip=team.events_to_skip,
                            store_events=team.store_events,
                        )

                    # Handle the updated tools (execute confirmed tools, etc.) with streaming
                    async for event in _ahandle_team_tool_call_updates_stream(
                        team,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        stream_events=stream_events,
                    ):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event

                    # Stream model response
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
                        from agno.run.team import IntermediateRunContentEvent, RunContentEvent

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

                    await araise_if_cancelled(run_response.run_id)  # type: ignore

                    # Check for new pauses
                    if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                        from agno.team import _hooks

                        async for item in _hooks.ahandle_team_run_paused_stream(
                            team, run_response=run_response, session=team_session
                        ):
                            yield item
                        if yield_run_output:
                            yield run_response
                        return

                    # Parse response with parser model
                    async for event in aparse_response_with_parser_model_stream(
                        team,
                        session=team_session,
                        run_response=run_response,
                        stream_events=stream_events,
                        run_context=run_context,
                    ):
                        yield event

                elif member_results:
                    # Member-only: mark original run as completed, then re-run team
                    continuation_message = _build_continuation_message(member_results)
                    run_response.status = RunStatus.completed
                    if team_session is not None:
                        await _acleanup_and_store(team, run_response=run_response, session=team_session)
                    async for item in team.arun(  # type: ignore
                        input=continuation_message,
                        stream=True,
                        stream_events=stream_events,
                        session_id=session_id,
                        user_id=user_id,
                        knowledge_filters=run_context.knowledge_filters,
                        dependencies=run_context.dependencies,
                        metadata=run_context.metadata,
                        debug_mode=debug_mode,
                        **kwargs,
                    ):
                        yield item
                    return

                # Content completed
                if stream_events:
                    yield handle_event(
                        create_team_run_content_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )

                # Post-hooks
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

                # Session summary
                if team.session_summary_manager is not None:
                    team_session.upsert_run(run_response=run_response)
                    if stream_events:
                        yield handle_event(
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
                        yield handle_event(
                            create_team_session_summary_completed_event(
                                from_run_response=run_response, session_summary=team_session.summary
                            ),
                            run_response,
                            events_to_skip=team.events_to_skip,
                            store_events=team.store_events,
                        )

                # Completed
                completed_event = handle_event(
                    create_team_run_completed_event(run_response),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

                run_response.status = RunStatus.completed
                await _acleanup_and_store(team, run_response=run_response, session=team_session)

                if stream_events:
                    yield completed_event

                if yield_run_output:
                    yield run_response

                await alog_team_telemetry(team, session_id=team_session.session_id, run_id=run_response.run_id)
                log_debug(f"Team Continue Run End: {run_response.run_id}", center=True, symbol="*")
                break

            except RunCancelledException as e:
                if run_response is None:
                    run_response = TeamRunOutput(run_id=run_id)
                run_response = cast(TeamRunOutput, run_response)
                log_info(f"Team run {run_response.run_id} was cancelled")
                run_response.status = RunStatus.cancelled
                if not run_response.content:
                    run_response.content = str(e)
                yield handle_event(
                    create_team_run_cancelled_event(from_run_response=run_response, reason=str(e)),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )
                if team_session is not None:
                    await _acleanup_and_store(team, run_response=run_response, session=team_session)
                break

            except (InputCheckError, OutputCheckError) as e:
                run_response = cast(TeamRunOutput, run_response)
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
                if team_session is not None:
                    await _acleanup_and_store(team, run_response=run_response, session=team_session)
                yield run_error
                break

            except KeyboardInterrupt:
                if run_response is None:
                    run_response = TeamRunOutput(run_id=run_id)
                run_response = cast(TeamRunOutput, run_response)
                yield handle_event(
                    create_team_run_cancelled_event(
                        from_run_response=run_response, reason="Operation cancelled by user"
                    ),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )
                break

            except Exception as e:
                if run_response is None:
                    run_response = TeamRunOutput(run_id=run_id)
                run_response = cast(TeamRunOutput, run_response)
                if attempt < num_attempts - 1:
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
                log_error(f"Error in Team acontinue_run stream: {str(e)}")
                if team_session is not None:
                    await _acleanup_and_store(team, run_response=run_response, session=team_session)
                yield run_error

    finally:
        _disconnect_connectable_tools(team)
        await _disconnect_mcp_tools(team)  # type: ignore
        if run_response and run_response.run_id:
            await acleanup_run(run_response.run_id)
