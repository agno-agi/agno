"""Run lifecycle and sync/async execution trait for Team."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from time import time as unix_time
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
from agno.models.fallback import acall_model_with_fallback, call_model_with_fallback
from agno.models.message import Message
from agno.models.metrics import RunMetrics, merge_background_metrics
from agno.models.response import ModelResponse, ToolExecution
from agno.run import RunContext, RunStatus
from agno.run.agent import (
    RunCancelledEvent as AgentRunCancelledEvent,
)
from agno.run.agent import (
    RunCompletedEvent as AgentRunCompletedEvent,
)
from agno.run.agent import (
    RunOutput,
    RunOutputEvent,
)
from agno.run.cancel import (
    acancel_run as acancel_run_global,
)
from agno.run.cancel import (
    acleanup_member_runs,
    acleanup_run,
    adrain_member_tasks,
    aget_member_run_ids,
    araise_if_cancelled,
    aregister_member_run,
    aregister_run,
    cleanup_member_runs,
    cleanup_run,
    get_member_run_ids,
    raise_if_cancelled,
    register_member_run,
    register_run,
)
from agno.run.cancel import (
    cancel_run as cancel_run_global,
)
from agno.run.messages import RunMessages
from agno.run.team import (
    RunCancelledEvent as TeamRunCancelledEvent,
)
from agno.run.team import (
    RunCompletedEvent as TeamRunCompletedEvent,
)
from agno.run.team import (
    TaskData,
    TeamRunInput,
    TeamRunOutput,
    TeamRunOutputEvent,
)
from agno.session import TeamSession
from agno.tools.function import Function
from agno.utils.agent import (
    await_for_open_threads,
    await_for_thread_tasks_stream,
    collect_background_metrics,
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

# Cancel raises immediately on every event. Only terminal events bypass so the
# member's own cancel handler can yield them to the stream. RunError is excluded —
# in a cancel race the team's cancel wins.
_MEMBER_CANCEL_BYPASS_EVENT_TYPES = (
    AgentRunCancelledEvent,
    AgentRunCompletedEvent,
    TeamRunCancelledEvent,
    TeamRunCompletedEvent,
)

if TYPE_CHECKING:
    from agno.team._run_options import ResolvedRunOptions
    from agno.team.team import Team


def cancel_run(run_id: str) -> bool:
    """Cancel a running team execution.

    Also cancels any in-flight member runs spawned by this team run.

    Args:
        run_id (str): The run_id to cancel.

    Returns:
        bool: True if the run was found and marked for cancellation, False otherwise.
    """
    result = cancel_run_global(run_id)
    for member_run_id in get_member_run_ids(run_id):
        cancel_run(member_run_id)
    return result


async def acancel_run(run_id: str) -> bool:
    """Cancel a running team execution (async version).

    Also cancels any in-flight member runs spawned by this team run.

    Args:
        run_id (str): The run_id to cancel.

    Returns:
        bool: True if the run was found and marked for cancellation, False otherwise.
    """
    result = await acancel_run_global(run_id)
    for member_run_id in await aget_member_run_ids(run_id):
        await acancel_run(member_run_id)
    return result


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
    from agno.team._managers import _start_learning_future, _start_memory_future
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
    learning_future = None

    # Bind run_messages early so the cancellation handler can read it
    # if cancel fires before the message list is built.
    run_messages: Optional[RunMessages] = None
    try:
        run_input = cast(TeamRunInput, run_response.input)
        team.model = cast(Model, team.model)
        raise_if_cancelled(run_response.run_id)  # type: ignore

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

        # 4. Start memory and learning creation in background
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
            model_response = call_model_with_fallback(
                team.model,
                team.fallback_config,
                messages=accumulated_messages,
                response_format=response_format,
                tools=_tools,
                tool_choice=team.tool_choice,
                tool_call_limit=team.tool_call_limit,
                run_response=run_response,
                send_media_to_model=team.send_media_to_model,
                compression_manager=team.compression_manager if team.compress_tool_results else None,
                after_tool_results=build_team_after_tool_results_callback(
                    team, run_response, session, run_messages, run_context
                ),
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

                return _hooks.handle_team_run_paused(
                    team, run_response=run_response, session=session, run_context=run_context
                )

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

        # Always add media to run_response for caller availability
        if model_response is not None:
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

        # Wait for background memory and learning creation
        wait_for_open_threads(memory_future=memory_future, learning_future=learning_future)  # type: ignore
        merge_background_metrics(run_response.metrics, collect_background_metrics(memory_future, learning_future))

        raise_if_cancelled(run_response.run_id)  # type: ignore

        # Create session summary
        if team.session_summary_manager is not None:
            session.upsert_run(run_response=run_response)
            try:
                team.session_summary_manager.create_session_summary(session=session, run_metrics=run_response.metrics)
            except Exception as e:
                log_warning(f"Error in session summary creation: {str(e)}")

        raise_if_cancelled(run_response.run_id)  # type: ignore

        # Generate followups if enabled
        from agno.team._response import generate_team_followups

        generate_team_followups(team, run_response=run_response)

        # Set the run status to completed
        run_response.status = RunStatus.completed

        # Cleanup and store
        _cleanup_and_store(team, run_response=run_response, session=session)

        log_team_telemetry(team, session_id=session.session_id, run_id=run_response.run_id)

        log_debug(f"Team Task Run End: {run_response.run_id}", center=True, symbol="*")

        return run_response

    except RunCancelledException as e:
        run_response = _handle_team_run_cancellation(run_response, e, run_messages, session=session)
        try:
            _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
        except Exception as store_err:
            log_warning(f"Failed to persist cancelled run: {store_err}")
        return run_response

    except (InputCheckError, OutputCheckError) as e:
        run_response.status = RunStatus.error
        flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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
        run_response = _handle_team_run_cancellation(run_response, KeyboardInterrupt(), run_messages, session=session)
        try:
            _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
        except Exception as store_err:
            log_warning(f"Failed to persist cancelled run: {store_err}")
        return run_response

    except Exception as e:
        run_response.status = RunStatus.error
        flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
        run_error = create_team_run_error_event(run_response, error=str(e))
        run_response.events = add_team_error_event(error=run_error, events=run_response.events)
        if run_response.content is None:
            run_response.content = str(e)
        log_error(f"Error in Team task run: {str(e)}")
        _cleanup_and_store(team, run_response=run_response, session=session)
        return run_response

    finally:
        # Cancel background futures on error
        for future in (memory_future, learning_future):
            if future is not None and not future.done():
                future.cancel()
                try:
                    future.result(timeout=0)
                except Exception:
                    pass
        _disconnect_connectable_tools(team)
        cleanup_run(run_response.run_id)  # type: ignore

    return run_response


def _run_tasks_stream(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: RunContext,
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
    """Run the Team in autonomous task mode with streaming support.

    The team leader iteratively plans and delegates tasks to members until
    the goal is complete or max_iterations is reached. Events are yielded
    for each iteration.
    """
    from agno.team._hooks import _execute_post_hooks, _execute_pre_hooks
    from agno.team._init import _disconnect_connectable_tools
    from agno.team._managers import _start_learning_future, _start_memory_future
    from agno.team._messages import _get_run_messages
    from agno.team._response import (
        _convert_response_to_structured_format,
        _handle_model_response_stream,
        generate_response_with_output_model_stream,
        handle_reasoning_stream,
    )
    from agno.team._telemetry import log_team_telemetry
    from agno.team._tools import _determine_tools_for_model
    from agno.team.task import TaskStatus, load_task_list
    from agno.utils.events import (
        create_team_task_iteration_completed_event,
        create_team_task_iteration_started_event,
        create_team_task_state_updated_event,
    )

    log_debug(f"Team Task Run (Stream) Start: {run_response.run_id}", center=True)
    memory_future = None
    learning_future = None

    # Bind run_messages early so the cancellation handler can read it
    # if cancel fires before the message list is built.
    run_messages: Optional[RunMessages] = None
    try:
        run_input = cast(TeamRunInput, run_response.input)
        team.model = cast(Model, team.model)
        raise_if_cancelled(run_response.run_id)  # type: ignore

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
                stream_events=stream_events,
                background_tasks=background_tasks,
                **kwargs,
            )
            for pre_hook_event in pre_hook_iterator:
                yield pre_hook_event

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
            stream=True,
            stream_events=stream_events,
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
        learning_future = _start_learning_future(
            team,
            run_messages=run_messages,
            session=session,
            user_id=user_id,
            existing_future=learning_future,
        )

        # Yield run started event
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

        raise_if_cancelled(run_response.run_id)  # type: ignore

        # Use accumulated messages for the iterative loop
        accumulated_messages = run_messages.messages

        # === Iterative task loop ===
        for iteration in range(team.max_iterations):
            log_debug(f"Task iteration {iteration + 1}/{team.max_iterations}")

            # Yield task iteration started event
            if stream_events:
                yield handle_event(  # type: ignore
                    create_team_task_iteration_started_event(
                        from_run_response=run_response,
                        iteration=iteration + 1,
                        max_iterations=team.max_iterations,
                    ),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

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

            # Get model response with streaming
            # Update run_messages with accumulated messages for streaming
            run_messages.messages = accumulated_messages

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
                    if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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
                    if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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

            raise_if_cancelled(run_response.run_id)  # type: ignore

            # Check if delegation propagated member HITL requirements
            if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                from agno.team import _hooks

                yield from _hooks.handle_team_run_paused_stream(
                    team, run_response=run_response, session=session, run_context=run_context
                )
                if yield_run_output:
                    yield run_response
                return

            # Check termination conditions
            task_list = load_task_list(run_context.session_state)

            # Yield task state updated event
            if stream_events:
                # Convert task list to TaskData for frontend
                task_data_list = [
                    TaskData(
                        id=t.id,
                        title=t.title,
                        description=t.description,
                        status=t.status.value,
                        assignee=t.assignee,
                        dependencies=t.dependencies,
                        result=t.result,
                    )
                    for t in task_list.tasks
                ]
                yield handle_event(  # type: ignore
                    create_team_task_state_updated_event(
                        from_run_response=run_response,
                        task_summary=task_list.get_summary_string(),
                        goal_complete=task_list.goal_complete,
                        tasks=task_data_list,
                        completion_summary=task_list.completion_summary,
                    ),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

            # Yield task iteration completed event
            if stream_events:
                yield handle_event(  # type: ignore
                    create_team_task_iteration_completed_event(
                        from_run_response=run_response,
                        iteration=iteration + 1,
                        max_iterations=team.max_iterations,
                        task_summary=task_list.get_summary_string(),
                    ),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

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

        # Convert response to structured format
        _convert_response_to_structured_format(team, run_response=run_response, run_context=run_context)

        # Yield RunContentCompletedEvent
        if stream_events:
            yield handle_event(  # type: ignore
                create_team_run_content_completed_event(from_run_response=run_response),
                run_response,
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )

        # Execute post-hooks
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

        # Wait for background memory creation
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

        # Create session summary
        if team.session_summary_manager is not None:
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
            create_team_run_completed_event(from_run_response=run_response),
            run_response,
            events_to_skip=team.events_to_skip,
            store_events=team.store_events,
        )

        # Generate followups if enabled
        from agno.team._response import generate_team_followups_stream

        yield from generate_team_followups_stream(team, run_response=run_response, stream_events=stream_events)

        # Set the run status to completed
        run_response.status = RunStatus.completed

        # Cleanup and store
        _cleanup_and_store(team, run_response=run_response, session=session)

        if stream_events:
            yield completed_event

        if yield_run_output:
            yield run_response

        log_team_telemetry(team, session_id=session.session_id, run_id=run_response.run_id)

        log_debug(f"Team Task Run (Stream) End: {run_response.run_id}", center=True, symbol="*")

    except RunCancelledException as e:
        run_response = _handle_team_run_cancellation(run_response, e, run_messages, session=session)
        cancelled_event, completed_event = _build_team_cancel_terminal_events(
            team,
            run_response,
            error=e,
            run_context=run_context,
        )
        try:
            _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
        except Exception as store_err:
            log_warning(f"Failed to persist cancelled run: {store_err}")
        yield cancelled_event  # type: ignore
        yield completed_event  # type: ignore
        if yield_run_output:
            yield run_response

    except (InputCheckError, OutputCheckError) as e:
        run_response.status = RunStatus.error
        flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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

    except KeyboardInterrupt:
        run_response = _handle_team_run_cancellation(run_response, KeyboardInterrupt(), run_messages, session=session)
        cancelled_event, completed_event = _build_team_cancel_terminal_events(
            team,
            run_response,
            error=KeyboardInterrupt(),
            run_context=run_context,
        )
        try:
            _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
        except Exception as store_err:
            log_warning(f"Failed to persist cancelled run: {store_err}")
        yield cancelled_event  # type: ignore
        yield completed_event  # type: ignore
        if yield_run_output:
            yield run_response

    except Exception as e:
        run_response.status = RunStatus.error
        flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
        run_error = create_team_run_error_event(run_response, error=str(e))
        run_response.events = add_team_error_event(error=run_error, events=run_response.events)
        if run_response.content is None:
            run_response.content = str(e)
        log_error(f"Error in Team task run (stream): {str(e)}")
        _cleanup_and_store(team, run_response=run_response, session=session)
        yield run_error

    finally:
        # Cancel background futures on error
        for future in (memory_future, learning_future):
            if future is not None and not future.done():
                future.cancel()
                try:
                    future.result(timeout=0)
                except Exception:
                    pass

        _disconnect_connectable_tools(team)
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

            # Bind run_messages early — pre-hook iteration checks cancellation
            # before run_messages is built, and the cancellation handler reads it.
            run_messages: Optional[RunMessages] = None
            try:
                raise_if_cancelled(run_response.run_id)  # type: ignore
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
                model_response: ModelResponse = call_model_with_fallback(
                    team.model,
                    team.fallback_config,
                    messages=run_messages.messages,
                    response_format=response_format,
                    tools=_tools,
                    tool_choice=team.tool_choice,
                    tool_call_limit=team.tool_call_limit,
                    run_response=run_response,
                    send_media_to_model=team.send_media_to_model,
                    compression_manager=team.compression_manager if team.compress_tool_results else None,
                    after_tool_results=build_team_after_tool_results_callback(
                        team, run_response, session, run_messages, run_context
                    ),
                )

                # Check for cancellation after model call
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # If an output model is provided, generate output using the output model
                parse_response_with_output_model(team, model_response, run_messages, run_response=run_response)

                # If a parser model is provided, structure the response separately
                parse_response_with_parser_model(
                    team, model_response, run_messages, run_context=run_context, run_response=run_response
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

                    return _hooks.handle_team_run_paused(
                        team, run_response=run_response, session=session, run_context=run_context
                    )

                # 8. Always add media to run_response for caller availability
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
                merge_background_metrics(
                    run_response.metrics, collect_background_metrics(memory_future, learning_future)
                )

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 12. Create session summary
                if team.session_summary_manager is not None:
                    # Upsert the RunOutput to Team Session before creating the session summary
                    session.upsert_run(run_response=run_response)
                    try:
                        team.session_summary_manager.create_session_summary(
                            session=session, run_metrics=run_response.metrics
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # Generate followups if enabled
                from agno.team._response import generate_team_followups

                generate_team_followups(team, run_response=run_response)

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 13. Cleanup and store the run response
                _cleanup_and_store(team, run_response=run_response, session=session)

                # Log Team Telemetry
                log_team_telemetry(team, session_id=session.session_id, run_id=run_response.run_id)

                log_debug(f"Team Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response
            except RunCancelledException as e:
                run_response = _handle_team_run_cancellation(run_response, e, run_messages, session=session)
                try:
                    _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                return run_response
            except (InputCheckError, OutputCheckError) as e:
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))

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
                run_response = _handle_team_run_cancellation(
                    run_response, KeyboardInterrupt(), run_messages, session=session
                )
                try:
                    _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                return run_response
            except Exception as e:
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    time.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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
    # Dispatch to task mode streaming if applicable
    from agno.team.mode import TeamMode

    if team.mode == TeamMode.tasks:
        yield from _run_tasks_stream(
            team,
            run_response=run_response,
            session=session,
            run_context=run_context,
            user_id=user_id,
            add_history_to_context=add_history_to_context,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            response_format=response_format,
            stream_events=stream_events,
            yield_run_output=yield_run_output,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )
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

            # Bind run_messages early — pre-hook iteration checks cancellation
            # before run_messages is built, and the cancellation handler reads it.
            run_messages: Optional[RunMessages] = None
            try:
                raise_if_cancelled(run_response.run_id)  # type: ignore
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
                run_messages = _get_run_messages(
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
                        if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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
                        if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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

                    yield from _hooks.handle_team_run_paused_stream(
                        team, run_response=run_response, session=session, run_context=run_context
                    )
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
                merge_background_metrics(
                    run_response.metrics, collect_background_metrics(memory_future, learning_future)
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
                        team.session_summary_manager.create_session_summary(
                            session=session, run_metrics=run_response.metrics
                        )
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

                # Generate followups if enabled
                from agno.team._response import generate_team_followups_stream

                yield from generate_team_followups_stream(team, run_response=run_response, stream_events=stream_events)

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
                run_response = _handle_team_run_cancellation(run_response, e, run_messages, session=session)
                cancelled_event, completed_event = _build_team_cancel_terminal_events(
                    team,
                    run_response,
                    error=e,
                    run_context=run_context,
                )
                try:
                    _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break
            except (InputCheckError, OutputCheckError) as e:
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))

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
                run_response = _handle_team_run_cancellation(
                    run_response, KeyboardInterrupt(), run_messages, session=session
                )
                cancelled_event, completed_event = _build_team_cancel_terminal_events(
                    team,
                    run_response,
                    error=KeyboardInterrupt(),
                    run_context=run_context,
                )
                try:
                    _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break
            except Exception as e:
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    time.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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
        run_response.metrics = RunMetrics()
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
    from agno.team._managers import _astart_learning_task, _astart_memory_task
    from agno.team._messages import _aget_run_messages
    from agno.team._response import (
        _convert_response_to_structured_format,
        _update_run_response,
        ahandle_reasoning,
    )
    from agno.team._telemetry import alog_team_telemetry
    from agno.team._tools import _aget_learning_tools, _check_and_refresh_mcp_tools, _determine_tools_for_model
    from agno.team.task import TaskStatus, load_task_list

    log_debug(f"Team Task Run Start: {run_response.run_id}", center=True)
    memory_task = None
    learning_task = None
    team_session: Optional[TeamSession] = None

    # Bind run_messages early so the cancellation handler can read it
    # if cancel fires before the message list is built.
    run_messages: Optional[RunMessages] = None

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
        await araise_if_cancelled(run_response.run_id)  # type: ignore

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
        learning_tools = await _aget_learning_tools(team, user_id, team_session)
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
            learning_tools=learning_tools,
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

        # 4. Start memory and learning creation in background
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
            model_response = await acall_model_with_fallback(
                team.model,
                team.fallback_config,
                messages=accumulated_messages,
                response_format=response_format,
                tools=_tools,
                tool_choice=team.tool_choice,
                tool_call_limit=team.tool_call_limit,
                run_response=run_response,
                send_media_to_model=team.send_media_to_model,
                compression_manager=team.compression_manager if team.compress_tool_results else None,
                after_tool_results=abuild_team_after_tool_results_callback(
                    team, run_response, team_session, run_messages, run_context
                ),
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

                return await _hooks.ahandle_team_run_paused(
                    team, run_response=run_response, session=team_session, run_context=run_context
                )

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

        # Always add media to run_response for caller availability
        if model_response is not None:
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

        # Wait for background memory and learning creation
        await await_for_open_threads(memory_task=memory_task, learning_task=learning_task)  # type: ignore
        merge_background_metrics(run_response.metrics, collect_background_metrics(memory_task, learning_task))

        await araise_if_cancelled(run_response.run_id)  # type: ignore

        # Create session summary
        if team.session_summary_manager is not None:
            team_session.upsert_run(run_response=run_response)
            try:
                await team.session_summary_manager.acreate_session_summary(
                    session=team_session, run_metrics=run_response.metrics
                )
            except Exception as e:
                log_warning(f"Error in session summary creation: {str(e)}")

        await araise_if_cancelled(run_response.run_id)  # type: ignore

        # Generate followups if enabled
        from agno.team._response import agenerate_team_followups

        await agenerate_team_followups(team, run_response=run_response)

        # Set the run status to completed
        run_response.status = RunStatus.completed

        # Cleanup and store
        await _acleanup_and_store(team, run_response=run_response, session=team_session)

        await alog_team_telemetry(team, session_id=team_session.session_id, run_id=run_response.run_id)

        log_debug(f"Team Task Run End: {run_response.run_id}", center=True, symbol="*")

        return run_response

    except RunCancelledException as e:
        run_response = _handle_team_run_cancellation(run_response, e, run_messages, session=team_session)
        if run_response.run_id:
            await adrain_member_tasks(run_response.run_id)
        try:
            if team_session is not None:
                await _acleanup_and_store(team, run_response=run_response, session=team_session)
        except Exception as store_err:
            log_warning(f"Failed to persist cancelled run: {store_err}")
        return run_response

    except (InputCheckError, OutputCheckError) as e:
        run_response.status = RunStatus.error
        flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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

    except (KeyboardInterrupt, asyncio.CancelledError) as cancel_exc:
        run_response = _handle_team_run_cancellation(
            run_response, KeyboardInterrupt(), run_messages, session=team_session
        )
        if team_session is not None:
            if isinstance(cancel_exc, asyncio.CancelledError):
                # Client disconnect: persist on a detached task so the cancel scope can't abort the write
                _persist_cancelled_team_run_in_background(
                    team, run_response=run_response, session=team_session, run_context=run_context
                )
            else:
                # Ctrl-C under asyncio.run: persist inline; a detached task would not run before the loop exits
                await _acleanup_and_store(
                    team, run_response=run_response, session=team_session, run_context=run_context
                )
        # Re-raise on disconnect to propagate it; return the partial on Ctrl-C
        if isinstance(cancel_exc, asyncio.CancelledError):
            raise
        return run_response

    except Exception as e:
        run_response.status = RunStatus.error
        flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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
        # Cancel background tasks on error
        for task in (memory_task, learning_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        await acleanup_run(run_response.run_id)  # type: ignore

    return run_response


async def _arun_tasks_stream(
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
    """Run the Team in autonomous task mode with async streaming support.

    The team leader iteratively plans and delegates tasks to members until
    the goal is complete or max_iterations is reached. Events are yielded
    for each iteration.
    """
    from agno.team._hooks import _aexecute_post_hooks, _aexecute_pre_hooks
    from agno.team._init import _disconnect_connectable_tools, _disconnect_mcp_tools
    from agno.team._managers import _astart_learning_task, _astart_memory_task
    from agno.team._messages import _aget_run_messages
    from agno.team._response import (
        _ahandle_model_response_stream,
        _convert_response_to_structured_format,
        agenerate_response_with_output_model_stream,
        ahandle_reasoning_stream,
    )
    from agno.team._telemetry import alog_team_telemetry
    from agno.team._tools import _aget_learning_tools, _check_and_refresh_mcp_tools, _determine_tools_for_model
    from agno.team.task import TaskStatus, load_task_list
    from agno.utils.events import (
        create_team_task_iteration_completed_event,
        create_team_task_iteration_started_event,
        create_team_task_state_updated_event,
    )

    log_debug(f"Team Task Run (Async Stream) Start: {run_response.run_id}", center=True)
    memory_task = None
    learning_task = None
    team_session: Optional[TeamSession] = None

    # Bind run_messages early so the cancellation handler can read it
    # if cancel fires before the message list is built.
    run_messages: Optional[RunMessages] = None

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
        await araise_if_cancelled(run_response.run_id)  # type: ignore

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
                stream_events=stream_events,
                background_tasks=background_tasks,
                **kwargs,
            )
            async for pre_hook_event in pre_hook_iterator:
                yield pre_hook_event

        # 2. Determine tools for model (includes task management tools)
        team_run_context: Dict[str, Any] = {}
        await _check_and_refresh_mcp_tools(team)
        learning_tools = await _aget_learning_tools(team, user_id, team_session)
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
            stream=True,
            stream_events=stream_events,
            learning_tools=learning_tools,
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
        learning_task = await _astart_learning_task(
            team,
            run_messages=run_messages,
            session=team_session,
            user_id=user_id,
            existing_task=learning_task,
        )

        # Yield run started event
        if stream_events:
            yield handle_event(  # type: ignore
                create_team_run_started_event(run_response),
                run_response,
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )

        await araise_if_cancelled(run_response.run_id)  # type: ignore

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

        await araise_if_cancelled(run_response.run_id)  # type: ignore

        # Use accumulated messages for the iterative loop
        accumulated_messages = run_messages.messages

        # === Iterative task loop ===
        for iteration in range(team.max_iterations):
            log_debug(f"Task iteration {iteration + 1}/{team.max_iterations}")

            # Yield task iteration started event
            if stream_events:
                yield handle_event(  # type: ignore
                    create_team_task_iteration_started_event(
                        from_run_response=run_response,
                        iteration=iteration + 1,
                        max_iterations=team.max_iterations,
                    ),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

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

            # Get model response with streaming
            # Update run_messages with accumulated messages for streaming
            run_messages.messages = accumulated_messages

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
                    if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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
                    if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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

            await araise_if_cancelled(run_response.run_id)  # type: ignore

            # Check if delegation propagated member HITL requirements
            if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                from agno.team import _hooks

                async for item in _hooks.ahandle_team_run_paused_stream(  # type: ignore[assignment]
                    team, run_response=run_response, session=team_session, run_context=run_context
                ):
                    yield item
                if yield_run_output:
                    yield run_response
                return

            # Check termination conditions
            task_list = load_task_list(run_context.session_state)

            # Yield task state updated event
            if stream_events:
                # Convert task list to TaskData for creating detailed events
                task_data_list = [
                    TaskData(
                        id=t.id,
                        title=t.title,
                        description=t.description,
                        status=t.status.value,
                        assignee=t.assignee,
                        dependencies=t.dependencies,
                        result=t.result,
                    )
                    for t in task_list.tasks
                ]
                yield handle_event(  # type: ignore
                    create_team_task_state_updated_event(
                        from_run_response=run_response,
                        task_summary=task_list.get_summary_string(),
                        goal_complete=task_list.goal_complete,
                        tasks=task_data_list,
                        completion_summary=task_list.completion_summary,
                    ),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

            # Yield task iteration completed event
            if stream_events:
                yield handle_event(  # type: ignore
                    create_team_task_iteration_completed_event(
                        from_run_response=run_response,
                        iteration=iteration + 1,
                        max_iterations=team.max_iterations,
                        task_summary=task_list.get_summary_string(),
                    ),
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

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

        # Convert response to structured format
        _convert_response_to_structured_format(team, run_response=run_response, run_context=run_context)

        # Yield RunContentCompletedEvent
        if stream_events:
            yield handle_event(  # type: ignore
                create_team_run_content_completed_event(from_run_response=run_response),
                run_response,
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )

        # Execute post-hooks
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

        # Wait for background memory creation
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

        # Create session summary
        if team.session_summary_manager is not None:
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

        # Generate followups if enabled
        from agno.team._response import agenerate_team_followups_stream

        async for event in agenerate_team_followups_stream(
            team, run_response=run_response, stream_events=stream_events
        ):
            yield event

        # Set the run status to completed
        run_response.status = RunStatus.completed

        # Cleanup and store
        await _acleanup_and_store(team, run_response=run_response, session=team_session)

        if stream_events:
            yield completed_event

        if yield_run_output:
            yield run_response

        await alog_team_telemetry(team, session_id=team_session.session_id, run_id=run_response.run_id)

        log_debug(f"Team Task Run (Async Stream) End: {run_response.run_id}", center=True, symbol="*")

    except RunCancelledException as e:
        run_response = _handle_team_run_cancellation(run_response, e, run_messages, session=team_session)
        cancelled_event, completed_event = _build_team_cancel_terminal_events(
            team,
            run_response,
            error=e,
            run_context=run_context,
        )
        if run_response.run_id:
            await adrain_member_tasks(run_response.run_id)
        try:
            if team_session is not None:
                await _acleanup_and_store(team, run_response=run_response, session=team_session)
        except Exception as store_err:
            log_warning(f"Failed to persist cancelled run: {store_err}")
        yield cancelled_event  # type: ignore
        yield completed_event  # type: ignore
        if yield_run_output:
            yield run_response

    except (InputCheckError, OutputCheckError) as e:
        run_response.status = RunStatus.error
        flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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

    except (KeyboardInterrupt, asyncio.CancelledError, GeneratorExit) as cancel_exc:
        run_response = _handle_team_run_cancellation(
            run_response, KeyboardInterrupt(), run_messages, session=team_session
        )
        # Build terminal events first so they are stored on the run
        cancelled_event, completed_event = _build_team_cancel_terminal_events(
            team,
            run_response,
            error=KeyboardInterrupt(),
            run_context=run_context,
        )
        if team_session is not None:
            if isinstance(cancel_exc, (asyncio.CancelledError, GeneratorExit)):
                # Client disconnect: persist on a detached task so the cancel scope can't abort the write.
                # GeneratorExit is raised when the SSE StreamingResponse closes the generator on disconnect.
                _persist_cancelled_team_run_in_background(
                    team, run_response=run_response, session=team_session, run_context=run_context
                )
            else:
                # Ctrl-C under asyncio.run: persist inline; a detached task would not run before the loop exits
                await _acleanup_and_store(
                    team, run_response=run_response, session=team_session, run_context=run_context
                )
        # Re-raise on disconnect (client gone); yield the terminal events on Ctrl-C
        if isinstance(cancel_exc, (asyncio.CancelledError, GeneratorExit)):
            raise
        yield cancelled_event  # type: ignore
        yield completed_event  # type: ignore
        if yield_run_output:
            yield run_response

    except Exception as e:
        run_response.status = RunStatus.error
        flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
        run_error = create_team_run_error_event(run_response, error=str(e))
        run_response.events = add_team_error_event(error=run_error, events=run_response.events)
        if run_response.content is None:
            run_response.content = str(e)
        log_error(f"Error in Team task run (async stream): {str(e)}")
        if team_session is not None:
            await _acleanup_and_store(team, run_response=run_response, session=team_session)
        yield run_error

    finally:
        _disconnect_connectable_tools(team)
        await _disconnect_mcp_tools(team)

        # Cancel background tasks on error
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
    from agno.team._tools import _aget_learning_tools, _check_and_refresh_mcp_tools, _determine_tools_for_model

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

            # Bind run_messages early — pre-hook iteration checks cancellation
            # before run_messages is built, and the cancellation handler reads it.
            run_messages: Optional[RunMessages] = None
            try:
                await araise_if_cancelled(run_response.run_id)  # type: ignore
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
                learning_tools = await _aget_learning_tools(team, user_id, team_session)
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
                    learning_tools=learning_tools,
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
                model_response = await acall_model_with_fallback(
                    team.model,
                    team.fallback_config,
                    messages=run_messages.messages,
                    tools=_tools,
                    tool_choice=team.tool_choice,
                    tool_call_limit=team.tool_call_limit,
                    response_format=response_format,
                    send_media_to_model=team.send_media_to_model,
                    run_response=run_response,
                    compression_manager=team.compression_manager if team.compress_tool_results else None,
                    after_tool_results=abuild_team_after_tool_results_callback(
                        team, run_response, team_session, run_messages, run_context
                    ),
                )  # type: ignore

                # Check for cancellation after model call
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # If an output model is provided, generate output using the output model
                await agenerate_response_with_output_model(
                    team, model_response=model_response, run_messages=run_messages, run_response=run_response
                )

                # If a parser model is provided, structure the response separately
                await aparse_response_with_parser_model(
                    team,
                    model_response=model_response,
                    run_messages=run_messages,
                    run_context=run_context,
                    run_response=run_response,
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

                    return await _hooks.ahandle_team_run_paused(
                        team, run_response=run_response, session=team_session, run_context=run_context
                    )

                # 8. Always add media to run_response for caller availability
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
                merge_background_metrics(run_response.metrics, collect_background_metrics(memory_task, learning_task))

                await araise_if_cancelled(run_response.run_id)  # type: ignore
                # 12. Create session summary
                if team.session_summary_manager is not None:
                    # Upsert the RunOutput to Team Session before creating the session summary
                    team_session.upsert_run(run_response=run_response)
                    try:
                        await team.session_summary_manager.acreate_session_summary(
                            session=team_session, run_metrics=run_response.metrics
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # Generate followups if enabled
                from agno.team._response import agenerate_team_followups

                await agenerate_team_followups(team, run_response=run_response)

                run_response.status = RunStatus.completed

                # 13. Cleanup and store the run response and session
                await _acleanup_and_store(team, run_response=run_response, session=team_session)

                # Log Team Telemetry
                await alog_team_telemetry(team, session_id=team_session.session_id, run_id=run_response.run_id)

                log_debug(f"Team Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response

            except RunCancelledException as e:
                run_response = _handle_team_run_cancellation(run_response, e, run_messages, session=team_session)
                if run_response.run_id:
                    await adrain_member_tasks(run_response.run_id)
                try:
                    await _acleanup_and_store(team, run_response=run_response, session=team_session)
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                return run_response

            except (InputCheckError, OutputCheckError) as e:
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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

            except (KeyboardInterrupt, asyncio.CancelledError) as cancel_exc:
                run_response = _handle_team_run_cancellation(
                    run_response, KeyboardInterrupt(), run_messages, session=team_session
                )
                if team_session is not None:
                    if isinstance(cancel_exc, asyncio.CancelledError):
                        # Client disconnect: persist on a detached task so the cancel scope can't abort the write
                        _persist_cancelled_team_run_in_background(
                            team, run_response=run_response, session=team_session, run_context=run_context
                        )
                    else:
                        # Ctrl-C under asyncio.run: persist inline; a detached task would not run before the loop exits
                        await _acleanup_and_store(
                            team, run_response=run_response, session=team_session, run_context=run_context
                        )
                # Re-raise on disconnect to propagate it; return the partial on Ctrl-C
                if isinstance(cancel_exc, asyncio.CancelledError):
                    raise
                return run_response

            except Exception as e:
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    await asyncio.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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
        except Exception as e:
            log_error(f"Background run {run_response.run_id} failed: {str(e)}")
            # Persist ERROR status
            try:
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
                team_session.upsert_run(run_response=run_response)
                await asave_session(team, session=team_session)
            except Exception as e:
                log_error(f"Failed to persist error state for background run {run_response.run_id}: {str(e)}")
            # Note: acleanup_run is already called by _arun's finally block

    task = asyncio.create_task(_background_task())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # 5. Return immediately with the PENDING response
    return run_response


async def _arun_background_stream(
    team: "Team",
    run_response: TeamRunOutput,
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
) -> AsyncIterator[str]:
    """Background streaming team run that survives client disconnections.

    1. Persists RUNNING status in DB
    2. Spawns a detached asyncio.Task that runs _arun_stream
    3. Buffers events (via event_buffer) and publishes to SSE subscribers
    4. Yields SSE-formatted strings via an asyncio.Queue

    The detached task keeps running even if the client disconnects.
    The caller (router) just yields the SSE strings to the client.
    """
    from agno.team._session import asave_session
    from agno.team._storage import _aread_or_create_session, _update_metadata

    run_id = run_response.run_id
    if not run_id:
        raise ValueError("run_id is required for background streaming")

    # 1. Persist RUNNING status so the run is visible in the DB immediately
    run_response.status = RunStatus.running

    team_session = await _aread_or_create_session(team, session_id=session_id, user_id=user_id)
    _update_metadata(team, session=team_session)
    team_session.upsert_run(run_response=run_response)
    await asave_session(team, session=team_session)

    log_info(f"Background stream run {run_id} persisted with RUNNING status")

    # 2. Create queue for forwarding SSE strings to the caller
    sse_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    # 3. Spawn detached background task
    async def _background_producer() -> None:
        from agno.os.managers import event_buffer, sse_subscriber_manager
        from agno.os.utils import format_sse_event_with_index

        try:
            async for event in _arun_stream(
                team,
                run_response=run_response,
                run_context=run_context,
                user_id=user_id,
                response_format=response_format,
                stream_events=stream_events,
                yield_run_output=yield_run_output or False,
                session_id=session_id,
                add_history_to_context=add_history_to_context,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            ):
                if isinstance(event, TeamRunOutput):
                    continue

                # Buffer event for reconnection support
                event_index: Optional[int] = None
                try:
                    event_index = event_buffer.add_event(run_id, event)
                except Exception:
                    log_warning(f"Failed to buffer event for run {run_id}")

                # Format as SSE
                sse_data = format_sse_event_with_index(event, event_index=event_index, run_id=run_id)

                # Push to primary queue (original client)
                try:
                    await sse_queue.put(sse_data)
                except Exception:
                    log_warning(f"Failed to push SSE data to queue for run {run_id}")

                # Publish to SSE subscribers (resumed clients)
                try:
                    await sse_subscriber_manager.publish(
                        run_id, event_index if event_index is not None else -1, sse_data
                    )
                except Exception:
                    log_warning(f"Failed to publish SSE data to subscribers for run {run_id}")

        except Exception:
            log_error(f"Background stream run {run_id} failed", exc_info=True)
            # Persist ERROR status
            try:
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
                team_session.upsert_run(run_response=run_response)
                await asave_session(team, session=team_session)
            except Exception:
                log_error(f"Failed to persist error state for background stream run {run_id}", exc_info=True)

        finally:
            # Signal primary queue FIRST — unblocks the original client
            try:
                await sse_queue.put(None)
            except Exception:
                log_warning(f"Failed to signal primary queue for run {run_id} completion")

            # Mark run completed in event buffer (status is set by _arun_stream/acleanup_and_store)
            try:
                event_buffer.set_run_completed(run_id, run_response.status or RunStatus.completed)
            except Exception:
                log_warning(f"Failed to mark run {run_id} as completed in event buffer")

            # Signal SSE subscribers that run is done (shielded to survive task cancellation)
            try:
                await asyncio.shield(sse_subscriber_manager.complete(run_id))
            except (Exception, asyncio.CancelledError):
                log_warning(f"Failed to signal SSE subscribers for run {run_id} completion")

    task = asyncio.create_task(_background_producer())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # 4. Yield SSE strings from the queue
    while True:
        sse_data = await sse_queue.get()
        if sse_data is None:
            break
        yield sse_data


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
    from agno.team._tools import _aget_learning_tools, _check_and_refresh_mcp_tools, _determine_tools_for_model

    # Fallback for tasks mode (streaming not yet supported)
    # Dispatch to task mode streaming if applicable
    from agno.team.mode import TeamMode

    if team.mode == TeamMode.tasks:
        async for event in _arun_tasks_stream(
            team,
            run_response=run_response,
            run_context=run_context,
            session_id=session_id,
            user_id=user_id,
            response_format=response_format,
            stream_events=stream_events,
            yield_run_output=yield_run_output,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            add_history_to_context=add_history_to_context,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        ):
            yield event
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

            # Bind run_messages early — pre-hook iteration checks cancellation
            # before run_messages is built, and the cancellation handler reads it.
            run_messages: Optional[RunMessages] = None
            try:
                await araise_if_cancelled(run_response.run_id)  # type: ignore
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
                learning_tools = await _aget_learning_tools(team, user_id, team_session)
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
                    learning_tools=learning_tools,
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
                        if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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
                        if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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
                        team, run_response=run_response, session=team_session, run_context=run_context
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
                merge_background_metrics(run_response.metrics, collect_background_metrics(memory_task, learning_task))

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
                        await team.session_summary_manager.acreate_session_summary(
                            session=team_session, run_metrics=run_response.metrics
                        )
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

                # Generate followups if enabled
                from agno.team._response import agenerate_team_followups_stream

                async for event in agenerate_team_followups_stream(
                    team, run_response=run_response, stream_events=stream_events
                ):
                    yield event

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
                run_response = _handle_team_run_cancellation(run_response, e, run_messages, session=team_session)
                cancelled_event, completed_event = _build_team_cancel_terminal_events(
                    team,
                    run_response,
                    error=e,
                    run_context=run_context,
                )
                if run_response.run_id:
                    await adrain_member_tasks(run_response.run_id)
                try:
                    await _acleanup_and_store(team, run_response=run_response, session=team_session)
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break

            except (InputCheckError, OutputCheckError) as e:
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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

            except (KeyboardInterrupt, asyncio.CancelledError, GeneratorExit) as cancel_exc:
                run_response = _handle_team_run_cancellation(
                    run_response, KeyboardInterrupt(), run_messages, session=team_session
                )
                # Build terminal events first so they are stored on the run
                cancelled_event, completed_event = _build_team_cancel_terminal_events(
                    team,
                    run_response,
                    error=KeyboardInterrupt(),
                    run_context=run_context,
                )
                if team_session is not None:
                    if isinstance(cancel_exc, (asyncio.CancelledError, GeneratorExit)):
                        # Client disconnect: persist on a detached task so the cancel scope can't abort the write.
                        # GeneratorExit is raised when the SSE StreamingResponse closes the generator on disconnect.
                        _persist_cancelled_team_run_in_background(
                            team, run_response=run_response, session=team_session, run_context=run_context
                        )
                    else:
                        # Ctrl-C under asyncio.run: persist inline; a detached task would not run before the loop exits
                        await _acleanup_and_store(
                            team, run_response=run_response, session=team_session, run_context=run_context
                        )
                # Re-raise on disconnect (client gone); yield the terminal events on Ctrl-C
                if isinstance(cancel_exc, (asyncio.CancelledError, GeneratorExit)):
                    raise
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break

            except Exception as e:
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    await asyncio.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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
    run_response.metrics = RunMetrics()
    run_response.metrics.start_timer()

    # Background execution: return immediately with PENDING status
    if background:
        if not team.db:
            raise ValueError(
                "Background execution requires a database to be configured on the team for run persistence."
            )
        if opts.stream:
            # background=True, stream=True: run in background task, stream events via queue
            return _arun_background_stream(  # type: ignore[return-value]
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


def _normalize_team_cancellation_reason(
    run_response: TeamRunOutput,
    error: Union[RunCancelledException, KeyboardInterrupt],
) -> str:
    """Return a non-empty, human-readable reason for a team-run cancellation."""
    if isinstance(error, RunCancelledException):
        return str(error) or f"Run {run_response.run_id} was cancelled"
    return "Operation cancelled by user"


def _handle_team_run_cancellation(
    run_response: TeamRunOutput,
    error: Union[RunCancelledException, KeyboardInterrupt],
    run_messages: Optional["RunMessages"] = None,
    session: Optional[TeamSession] = None,
) -> TeamRunOutput:
    """Prepare a team run response for cancellation: set status, preserve content and messages."""
    reason = _normalize_team_cancellation_reason(run_response, error)
    log_debug(f"Team run {run_response.run_id} was cancelled")
    run_response.status = RunStatus.cancelled
    has_partial_content = bool(run_response.content)
    if not run_response.content:
        run_response.content = reason
    if run_response.messages is None and run_messages is not None:
        messages_for_run_response = [msg for msg in run_messages.messages if msg.add_to_agent_memory]
        # Preserve partial streamed content as the assistant message, filling an empty trailing one if present
        if has_partial_content:
            partial_content = str(run_response.content)
            trailing_assistant = next(
                (msg for msg in reversed(messages_for_run_response) if msg.role == "assistant"),
                None,
            )
            if trailing_assistant is None:
                messages_for_run_response.append(Message(role="assistant", content=partial_content))
            elif not trailing_assistant.content:
                trailing_assistant.content = partial_content
        if messages_for_run_response:
            run_response.messages = messages_for_run_response
    # Cancel can interrupt the team's outer add_member_run; re-link any member runs that the
    # delegate-task cancel branch already upserted into session.runs (intent-based cancel path)
    if session is not None:
        existing_member_run_ids = {member_response.run_id for member_response in (run_response.member_responses or [])}
        for session_run in session.runs or []:
            if (
                getattr(session_run, "parent_run_id", None) == run_response.run_id
                and session_run.run_id not in existing_member_run_ids
            ):
                run_response.add_member_run(session_run)
    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()
    # Clear pause state so cancel wins over a paused HITL run
    if run_response.requirements:
        run_response.requirements = [req for req in run_response.requirements if req.is_resolved()]
    if run_response.tools:
        for tool in run_response.tools:
            if tool.is_paused:
                tool.requires_confirmation = False
                tool.requires_user_input = False
                tool.external_execution_required = False
    return run_response


def _build_team_cancel_terminal_events(
    team: "Team",
    run_response: TeamRunOutput,
    error: Union[RunCancelledException, KeyboardInterrupt],
    run_context: Optional[RunContext] = None,
) -> Tuple[TeamRunCancelledEvent, TeamRunCompletedEvent]:
    """Return the (cancelled, completed) terminal event pair for a cancelled team run."""
    # Update run_response.session_state before creating the events
    if run_context is not None and run_context.session_state is not None:
        run_response.session_state = run_context.session_state
    cancelled_event = cast(
        TeamRunCancelledEvent,
        handle_event(
            create_team_run_cancelled_event(
                from_run_response=run_response,
                reason=_normalize_team_cancellation_reason(run_response, error),
            ),
            run_response,
            events_to_skip=team.events_to_skip,
            store_events=team.store_events,
        ),
    )
    completed_event = cast(
        TeamRunCompletedEvent,
        handle_event(
            create_team_run_completed_event(from_run_response=run_response),
            run_response,
            events_to_skip=team.events_to_skip,
            store_events=team.store_events,
        ),
    )
    return cancelled_event, completed_event


# ---------------------------------------------------------------------------
# Post-run cleanup (moved from _storage.py)
# ---------------------------------------------------------------------------


def _cleanup_and_store(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> None:
    import copy

    from agno.run.approval import update_approval_run_status
    from agno.team._session import update_session_metrics

    if run_response.run_id:
        cleanup_member_runs(run_response.run_id)

    # Scrub a shallow copy for storage — the original run_response is never
    # mutated so the caller always sees generated media regardless of store_media.
    storage_copy = copy.copy(run_response)
    scrub_run_output_for_storage(team, storage_copy)

    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Update run_response.session_state before saving
    if run_context is not None and run_context.session_state is not None:
        run_response.session_state = run_context.session_state
        storage_copy.session_state = run_context.session_state

    # Add scrubbed RunOutput to Team Session
    session.upsert_run(run_response=storage_copy)

    # Calculate session metrics
    update_session_metrics(team, session=session, run_response=run_response)

    # Update session state before saving the session
    if run_context is not None and run_context.session_state is not None:
        if session.session_data is not None:
            session.session_data["session_state"] = run_context.session_state
        else:
            session.session_data = {"session_state": run_context.session_state}

    # Save session to memory
    team.save_session(session=session)

    # Update approval run_status if this run has an associated approval.
    if run_response.status is not None and run_response.run_id is not None:
        update_approval_run_status(team.db, run_response.run_id, run_response.status)


async def _acleanup_and_store(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> None:
    import copy

    from agno.run.approval import aupdate_approval_run_status
    from agno.team._session import update_session_metrics

    if run_response.run_id:
        await acleanup_member_runs(run_response.run_id)

    # Scrub a shallow copy for storage — the original run_response is never
    # mutated so the caller always sees generated media regardless of store_media.
    storage_copy = copy.copy(run_response)
    scrub_run_output_for_storage(team, storage_copy)

    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Update run_response.session_state before saving
    if run_context is not None and run_context.session_state is not None:
        run_response.session_state = run_context.session_state
        storage_copy.session_state = run_context.session_state

    # Add scrubbed RunOutput to Team Session
    session.upsert_run(run_response=storage_copy)

    # Calculate session metrics
    update_session_metrics(team, session=session, run_response=run_response)

    # Update session state before saving the session
    if run_context is not None and run_context.session_state is not None:
        if session.session_data is not None:
            session.session_data["session_state"] = run_context.session_state
        else:
            session.session_data = {"session_state": run_context.session_state}

    # Save session to memory
    await team.asave_session(session=session)

    # Update approval run_status if this run has an associated approval.
    if run_response.status is not None and run_response.run_id is not None:
        await aupdate_approval_run_status(team.db, run_response.run_id, run_response.status)


def _persist_cancelled_team_run_in_background(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> None:
    """Persist a cancelled team run on a detached background task.

    On a client disconnect the request runs inside an anyio cancel scope; awaiting
    _acleanup_and_store inline lets the DB write be re-cancelled mid-flight, losing the
    run. Scheduling it on _background_tasks runs to completion outside that scope. Completed
    members' content is already on run_response; in-flight member tasks are not drained here
    since on a cancel/disconnect they are themselves cancelled and would never complete.
    """

    async def _persist() -> None:
        try:
            await _acleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
            # The _arun finally also cleans up, but on a disconnect that await can be
            # re-cancelled; clean up here too so the run is never left tracked.
            if run_response.run_id:
                await acleanup_run(run_response.run_id)
        except Exception as store_err:
            log_warning(f"Failed to persist cancelled run: {store_err}")

    task = asyncio.create_task(_persist())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ---------------------------------------------------------------------------
# Mid-run checkpointing (checkpoint="tool-batch") for Team
# Mirrors the agent-side helpers in agno/agent/_run.py.
# ---------------------------------------------------------------------------


def flush_in_flight_messages_on_error_team(
    run_response: TeamRunOutput,
    run_messages: Optional["RunMessages"],  # noqa: F821
) -> None:
    """Copy in-flight conversation into ``run_response.messages`` for the
    terminal ERROR write. Mirrors agent's ``flush_in_flight_messages_on_error``.

    Same scenario: model API call fails before any tool batch fires, so the
    mid-run checkpoint hook never ran and ``_update_run_response`` never
    populated ``run_response.messages``. Without this flush, the ERROR row
    persists with empty messages and the conversation that led to the
    failure is lost.

    Only sets ``run_response.messages`` when empty — preserves anything a
    mid-run hook captured.
    """
    if run_messages is None:
        return
    if run_response.messages:
        return
    if not run_messages.messages:
        return
    run_response.messages = [m for m in run_messages.messages if m.add_to_agent_memory]


def _persist_team_run_in_session(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> None:
    """Persist mid-run state for a team without the terminal-only steps
    (timer stop, approval update). Same write path as ``_cleanup_and_store``
    minus those finalization side effects.
    """
    import copy

    from agno.team._session import update_session_metrics
    from agno.utils.agent import isolate_media_scrub_targets

    storage_copy = copy.copy(run_response)
    # Mid-run checkpoint: scrubbing mutates shared objects in place, and the
    # shallow copy aliases the live run. Isolate what the scrubs touch so a
    # checkpoint never strips state off the still-running team run.
    if not team.store_media:
        isolate_media_scrub_targets(storage_copy)
    if storage_copy.member_responses and team.store_member_responses:
        # save_session -> _scrub_member_responses scrubs each member in place;
        # deep-copy so it operates on the storage copy, not the live member runs.
        storage_copy.member_responses = copy.deepcopy(storage_copy.member_responses)
    scrub_run_output_for_storage(team, storage_copy)

    if run_context is not None and run_context.session_state is not None:
        run_response.session_state = run_context.session_state
        storage_copy.session_state = run_context.session_state

    session.upsert_run(run_response=storage_copy)
    update_session_metrics(team, session=session, run_response=run_response)

    if run_context is not None and run_context.session_state is not None:
        if session.session_data is not None:
            session.session_data["session_state"] = run_context.session_state
        else:
            session.session_data = {"session_state": run_context.session_state}

    team.save_session(session=session)


async def _apersist_team_run_in_session(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> None:
    """Async variant of :func:`_persist_team_run_in_session`."""
    import copy

    from agno.team._session import update_session_metrics
    from agno.utils.agent import isolate_media_scrub_targets

    storage_copy = copy.copy(run_response)
    # Mid-run checkpoint: scrubbing mutates shared objects in place, and the
    # shallow copy aliases the live run. Isolate what the scrubs touch so a
    # checkpoint never strips state off the still-running team run.
    if not team.store_media:
        isolate_media_scrub_targets(storage_copy)
    if storage_copy.member_responses and team.store_member_responses:
        # save_session -> _scrub_member_responses scrubs each member in place;
        # deep-copy so it operates on the storage copy, not the live member runs.
        storage_copy.member_responses = copy.deepcopy(storage_copy.member_responses)
    scrub_run_output_for_storage(team, storage_copy)

    if run_context is not None and run_context.session_state is not None:
        run_response.session_state = run_context.session_state
        storage_copy.session_state = run_context.session_state

    session.upsert_run(run_response=storage_copy)
    update_session_metrics(team, session=session, run_response=run_response)

    if run_context is not None and run_context.session_state is not None:
        if session.session_data is not None:
            session.session_data["session_state"] = run_context.session_state
        else:
            session.session_data = {"session_state": run_context.session_state}

    await team.asave_session(session=session)


def _sync_team_run_response_with_model_response(
    run_response: TeamRunOutput,
    run_messages: "RunMessages",  # noqa: F821
    model_response: "ModelResponse",  # noqa: F821
) -> None:
    """Mirror the in-flight model_response state onto run_response for a team.

    Same shape as the agent helper, with one team-specific concern: ``child_run_id``
    (the delegation -> member-run link) is patched onto the existing
    ``run_response.tools`` entries during tool execution, NOT onto
    ``model_response.tool_executions``. A naive ``run_response.tools = list(...)``
    would therefore drop the linkage on every mid-run checkpoint taken after a
    delegation. Carry it over by ``tool_call_id``, mirroring the streaming merge
    in :mod:`agno.team._response`.
    """
    if model_response.tool_executions is not None:
        existing_child_run_ids = {
            tool.tool_call_id: tool.child_run_id
            for tool in (run_response.tools or [])
            if tool.tool_call_id is not None and tool.child_run_id is not None
        }
        new_tools = list(model_response.tool_executions)
        if existing_child_run_ids:
            for tool in new_tools:
                if tool.child_run_id is None and tool.tool_call_id in existing_child_run_ids:
                    tool.child_run_id = existing_child_run_ids[tool.tool_call_id]
        run_response.tools = new_tools
    run_response.messages = [m for m in run_messages.messages if m.add_to_agent_memory]


def _mark_team_checkpoint_message(run_response: TeamRunOutput) -> None:
    """Mark the current message boundary as checkpointed for client timelines."""
    if not run_response.messages:
        return
    message = run_response.messages[-1]
    message.checkpoint_status = run_response.status.value if run_response.status else None
    message.checkpoint_created_at = int(unix_time())


def checkpoint_team_run(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> None:
    """Persist a mid-run team checkpoint. No-op unless ``team.checkpoint == "tool-batch"``."""
    if team.checkpoint != "tool-batch":
        return
    run_response.status = RunStatus.running
    run_response.last_checkpoint_at_message_index = len(run_response.messages or [])
    _mark_team_checkpoint_message(run_response)
    _persist_team_run_in_session(team, run_response, session, run_context)


async def acheckpoint_team_run(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> None:
    """Async variant of :func:`checkpoint_team_run`."""
    if team.checkpoint != "tool-batch":
        return
    run_response.status = RunStatus.running
    run_response.last_checkpoint_at_message_index = len(run_response.messages or [])
    _mark_team_checkpoint_message(run_response)
    await _apersist_team_run_in_session(team, run_response, session, run_context)


def build_team_after_tool_results_callback(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_messages: "RunMessages",  # noqa: F821
    run_context: Optional[RunContext] = None,
) -> Optional[Any]:
    """Build the sync ``after_tool_results`` callback for ``team.checkpoint='tool-batch'``.

    Returns ``None`` (the zero-cost path) when checkpointing is not enabled.
    Otherwise returns a callback that syncs run_response with the in-flight
    model_response and writes a checkpoint to the session.
    """
    if team.checkpoint != "tool-batch":
        return None

    def _callback(model_response):
        _sync_team_run_response_with_model_response(run_response, run_messages, model_response)
        checkpoint_team_run(team, run_response, session, run_context)

    return _callback


def abuild_team_after_tool_results_callback(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_messages: "RunMessages",  # noqa: F821
    run_context: Optional[RunContext] = None,
) -> Optional[Any]:
    """Async variant of :func:`build_team_after_tool_results_callback`."""
    if team.checkpoint != "tool-batch":
        return None

    async def _callback(model_response):
        _sync_team_run_response_with_model_response(run_response, run_messages, model_response)
        await acheckpoint_team_run(team, run_response, session, run_context)

    return _callback


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
            log_warning(f"Failed to resolve dependencies for {key}: {str(e)}")


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
            log_warning(f"Failed to resolve context for '{key}': {str(e)}")


# ---------------------------------------------------------------------------
# continue_run infrastructure
# ---------------------------------------------------------------------------


def _get_continue_run_messages(
    team: "Team",
    input: List[Message],
    session: Optional[TeamSession] = None,
    add_history_to_context: Optional[bool] = None,
    run_context: Optional[RunContext] = None,
) -> RunMessages:
    """Build a RunMessages object from the existing conversation messages.

    Similar to agent's get_continue_run_messages - extracts system and user messages
    from the existing message list for the continuation run.
    """
    run_messages = RunMessages()

    if add_history_to_context is None:
        add_history_to_context = team.add_history_to_context

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

    # Skip re-fetching history if input already contains it (run_response path).
    input_has_history = any(msg.from_history for msg in input)

    # Build messages: system first, then history (if needed), then remaining input
    if system_message is not None:
        run_messages.messages.append(system_message)

    if add_history_to_context and session is not None and not input_has_history:
        from copy import deepcopy

        from agno.utils.message import filter_tool_calls

        skip_role = team.system_message_role if team.system_message_role not in ["user", "assistant", "tool"] else None

        history: List[Message] = session.get_messages(
            last_n_runs=team.num_history_runs,
            limit=team.num_history_messages,
            skip_roles=[skip_role] if skip_role else None,
            team_id=team.id if team.parent_team_id is not None else None,
        )

        if len(history) > 0:
            history_copy = [deepcopy(msg) for msg in history]
            for _msg in history_copy:
                _msg.from_history = True
            if team.max_tool_calls_from_history is not None:
                filter_tool_calls(history_copy, team.max_tool_calls_from_history)
            log_debug(f"Adding {len(history_copy)} messages from history")
            run_messages.messages += history_copy

    # Add remaining input messages (skip system to avoid duplication)
    for msg in input:
        if msg is not system_message:
            run_messages.messages.append(msg)

    # Set messages on run_context so tool hooks can access the current message history
    if run_context is not None:
        run_context.messages = run_messages.messages

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
        handle_ask_user_tool_update,
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
                deque(run_tool(team, run_response, run_messages, _t, functions=_functions, team_mode=True), maxlen=0)  # type: ignore
            else:
                reject_tool_call(team, run_messages, _t, functions=_functions)  # type: ignore
                _t.confirmed = False
                _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                _t.tool_call_error = True
            _t.requires_confirmation = False

        # Case 2: Handle external execution required tools
        elif _t.external_execution_required is not None and _t.external_execution_required is True:
            handle_external_execution_update(team, run_messages=run_messages, tool=_t)  # type: ignore

        # Case 3a: Agentic user input required
        elif _t.tool_name == "get_user_input" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_get_user_input_tool_update(team, run_messages=run_messages, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True

        # Case 3b: User feedback (ask_user) required
        elif _t.tool_name == "ask_user" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_ask_user_tool_update(team, run_messages=run_messages, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True

        # Case 4: Handle user input required tools
        elif _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_user_input_update(team, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True
            deque(run_tool(team, run_response, run_messages, _t, functions=_functions, team_mode=True), maxlen=0)  # type: ignore


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
        handle_ask_user_tool_update,
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
                    team_mode=True,
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

        # Case 3a: Agentic user input required
        elif _t.tool_name == "get_user_input" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_get_user_input_tool_update(team, run_messages=run_messages, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True

        # Case 3b: User feedback (ask_user) required
        elif _t.tool_name == "ask_user" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_ask_user_tool_update(team, run_messages=run_messages, tool=_t)  # type: ignore
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
                team_mode=True,
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
        handle_ask_user_tool_update,
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
                async for _ in arun_tool(team, run_response, run_messages, _t, functions=_functions, team_mode=True):  # type: ignore
                    pass
            else:
                reject_tool_call(team, run_messages, _t, functions=_functions)  # type: ignore
                _t.confirmed = False
                _t.confirmation_note = _t.confirmation_note or "Tool call was rejected"
                _t.tool_call_error = True
            _t.requires_confirmation = False

        elif _t.external_execution_required is not None and _t.external_execution_required is True:
            handle_external_execution_update(team, run_messages=run_messages, tool=_t)  # type: ignore

        # Case 3a: Agentic user input required
        elif _t.tool_name == "get_user_input" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_get_user_input_tool_update(team, run_messages=run_messages, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True

        # Case 3b: User feedback (ask_user) required
        elif _t.tool_name == "ask_user" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_ask_user_tool_update(team, run_messages=run_messages, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True

        elif _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_user_input_update(team, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True
            async for _ in arun_tool(team, run_response, run_messages, _t, functions=_functions, team_mode=True):  # type: ignore
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
        handle_ask_user_tool_update,
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
                    team_mode=True,
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

        # Case 3a: Agentic user input required
        elif _t.tool_name == "get_user_input" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_get_user_input_tool_update(team, run_messages=run_messages, tool=_t)  # type: ignore
            _t.requires_user_input = False
            _t.answered = True

        # Case 3b: User feedback (ask_user) required
        elif _t.tool_name == "ask_user" and _t.requires_user_input is not None and _t.requires_user_input is True:
            handle_ask_user_tool_update(team, run_messages=run_messages, tool=_t)  # type: ignore
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
                team_mode=True,
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


def _merge_tools_preserving_approval(
    original_tools: List[Any],
    updated_tools_map: Dict[str, Any],
) -> List[Any]:
    """Merge updated tool executions from the continue payload with the original session tools.

    When a client sends tool updates during continue_run, the payload typically
    only includes HITL-relevant fields (confirmed, answered, user_input_schema, etc.)
    and omits approval metadata (approval_type, approval_id). A naive replacement
    would lose these fields, preventing the approval resolution gate from finding
    and applying the admin's decision to the correct tools.

    This function preserves approval_type and approval_id from the session originals
    whenever the incoming tool does not carry them.
    """
    merged: List[Any] = []
    for orig in original_tools:
        updated = updated_tools_map.get(orig.tool_call_id)
        if updated is not None:
            for attr in ("approval_type", "approval_id"):
                if getattr(updated, attr, None) is None and getattr(orig, attr, None) is not None:
                    setattr(updated, attr, getattr(orig, attr))
            merged.append(updated)
        else:
            merged.append(orig)
    return merged


def _backfill_approval_to_requirements(
    run_response: Any,
    old_requirements: Optional[List[Any]] = None,
) -> None:
    """Restore approval metadata on requirements' tool_execution objects after a continue payload merge.

    During continue_run the client's requirements replace the session originals,
    but approval_type/approval_id are typically absent from the client payload.
    This function copies those fields back from two sources (checked in priority order):

    1. run_response.tools — covers team-level approval tools whose metadata was
       already preserved by _merge_tools_preserving_approval.
    2. old_requirements (the pre-overwrite session requirements) — covers member-level
       approval tools where run_response.tools only contains delegate_task_to_member
       entries that have no approval_type. The original session requirements carry it.
    """
    reqs = getattr(run_response, "requirements", None)
    if not reqs:
        return

    # Build lookup from both sources
    by_id: Dict[str, Any] = {}
    # Old requirements first (lower priority)
    if old_requirements:
        for old_req in old_requirements:
            old_te = getattr(old_req, "tool_execution", None)
            if old_te and old_te.tool_call_id:
                by_id[old_te.tool_call_id] = old_te
    # run_response.tools second (higher priority, overwrites)
    for t in getattr(run_response, "tools", None) or []:
        if t.tool_call_id and getattr(t, "approval_type", None) is not None:
            by_id[t.tool_call_id] = t

    for req in reqs:
        te = getattr(req, "tool_execution", None)
        if te and te.tool_call_id and te.tool_call_id in by_id:
            src = by_id[te.tool_call_id]
            for attr in ("approval_type", "approval_id"):
                if getattr(te, attr, None) is None and getattr(src, attr, None) is not None:
                    setattr(te, attr, getattr(src, attr))


def _has_member_requirements(requirements: List[Any]) -> bool:
    """Check if any requirements are for member agents (have member_agent_id set)."""
    return any(getattr(req, "member_agent_id", None) is not None for req in requirements)


def _has_team_level_requirements(requirements: List[Any]) -> bool:
    """Check if any requirements are for team-level tools (no member_agent_id)."""
    return any(getattr(req, "member_agent_id", None) is None for req in requirements)


def _member_continue_kwargs_from_run_context(run_context: Optional[RunContext]) -> Dict[str, Any]:
    """Build kwargs to forward team run_context state to a member's continue_run call.

    Without this, member tools resumed via continue_run would lose access to the
    dependencies/metadata/knowledge_filters the team carried at pause time
    (see https://github.com/agno-agi/agno/issues/8135). The member's session_state
    is rehydrated from the shared DB session, so it does not need to be forwarded
    here (and `Agent.acontinue_run` does not accept a `session_state` parameter).
    """
    if run_context is None:
        return {}

    kwargs: Dict[str, Any] = {}
    if run_context.dependencies is not None:
        kwargs["dependencies"] = run_context.dependencies
    if run_context.metadata is not None:
        kwargs["metadata"] = run_context.metadata
    if run_context.knowledge_filters is not None:
        kwargs["knowledge_filters"] = run_context.knowledge_filters
    return kwargs


def _route_requirements_to_members(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> List[str]:
    """Route member requirements back to the appropriate member agents (sync, non-streaming).

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
        member_run_id = reqs[0].member_run_id if reqs else None

        if member_run_output is None and member_run_id:
            # Same-process resume: the paused member output is still held on the live team run.
            if run_response.member_responses:
                for sibling_response in run_response.member_responses:
                    if getattr(sibling_response, "run_id", None) == member_run_id:
                        member_run_output = sibling_response
                        break
            # After process restart: member_responses is empty (it's only assembled at runtime),
            # so fall back to the team session's sibling runs persisted in the DB.
            if member_run_output is None and session is not None and session.runs:
                for session_run in session.runs:
                    if getattr(session_run, "run_id", None) == member_run_id:
                        member_run_output = session_run  # type: ignore[assignment]
                        break

        member_run_id = getattr(member_run_output, "run_id", None) if member_run_output is not None else member_run_id
        if member_run_id and run_response.run_id is not None:
            register_member_run(run_response.run_id, member_run_id)

        # Forward team's run_context state to the member so dependencies and
        # session_state remain accessible to member tools after continue_run.
        member_continue_kwargs = _member_continue_kwargs_from_run_context(run_context)

        if member_run_output is not None:
            # Update requirements and tool executions on the member's run output
            member_run_output.requirements = reqs
            updated_tools = [req.tool_execution for req in reqs if req.tool_execution is not None]
            if updated_tools and member_run_output.tools:
                updated_map = {t.tool_call_id: t for t in updated_tools}
                member_run_output.tools = [updated_map.get(t.tool_call_id, t) for t in member_run_output.tools]

            member_response = member.continue_run(
                run_response=member_run_output,  # type: ignore[arg-type]
                session_id=session.session_id,
                **member_continue_kwargs,
            )
        else:
            # Fallback: use run_id (requires DB or cached session)
            member_response = member.continue_run(  # type: ignore[arg-type]
                run_id=member_run_id,
                requirements=reqs,
                session_id=session.session_id,
                **member_continue_kwargs,
            )

        # Check if member is still paused (chained HITL)
        if getattr(member_response, "is_paused", False):
            from agno.team._tools import _propagate_member_pause

            _propagate_member_pause(run_response, member, member_response)
        else:
            # Update the member's run in the team session so its status is persisted
            # (member agents skip save_session when team_id is set)
            session.upsert_run(member_response)

            content = getattr(member_response, "content", None) or "Task completed"
            member_results.append(f"[{member.name or member_id}]: {content}")

        # Clear _member_run_response references to allow GC of the member RunOutput
        for req in reqs:
            req._member_run_response = None

    return member_results


def _route_requirements_to_members_stream(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    member_results: List[str],
    run_context: Optional[RunContext] = None,
    stream_events: bool = False,
) -> Iterator[Union[TeamRunOutputEvent, RunOutputEvent]]:
    """Route member requirements back to the appropriate member agents (sync, streaming).

    Yields member streaming events (RunContent, etc.) to the caller, and appends
    result descriptions to the provided member_results list.

    Following the same pattern as delegate_task_to_member: iterate the member's
    streaming response, yield intermediate events, capture the final RunOutput.

    Args:
        member_results: Mutable list to collect member result strings.

    Yields:
        Member streaming events (RunOutputEvent, TeamRunOutputEvent).
    """
    from agno.run.requirement import RunRequirement
    from agno.team._tools import _find_member_route_by_id

    # Group requirements by member
    member_reqs: Dict[str, List[RunRequirement]] = {}
    for req in run_response.requirements or []:
        mid = getattr(req, "member_agent_id", None)
        if mid is not None:
            member_reqs.setdefault(mid, []).append(req)

    for member_id, reqs in member_reqs.items():
        route_result = _find_member_route_by_id(team, member_id, run_context=run_context)
        if route_result is None:
            log_warning(f"Could not find member with ID {member_id} for continue_run routing")
            member_results.append(f"[{member_id}]: Could not route requirement — member not found")
            continue

        _, member = route_result

        member_run_output = getattr(reqs[0], "_member_run_response", None)
        member_run_id = reqs[0].member_run_id if reqs else None

        if member_run_output is None and member_run_id:
            # Same-process resume: the paused member output is still held on the live team run.
            if run_response.member_responses:
                for sibling_response in run_response.member_responses:
                    if getattr(sibling_response, "run_id", None) == member_run_id:
                        member_run_output = sibling_response
                        break
            # After process restart: member_responses is empty (it's only assembled at runtime),
            # so fall back to the team session's sibling runs persisted in the DB.
            if member_run_output is None and session is not None and session.runs:
                for session_run in session.runs:
                    if getattr(session_run, "run_id", None) == member_run_id:
                        member_run_output = session_run  # type: ignore[assignment]
                        break

        member_run_id = getattr(member_run_output, "run_id", None) if member_run_output is not None else member_run_id
        if member_run_id and run_response.run_id is not None:
            register_member_run(run_response.run_id, member_run_id)

        # Forward team's run_context state to the member so dependencies and
        # session_state remain accessible to member tools after continue_run.
        member_continue_kwargs = _member_continue_kwargs_from_run_context(run_context)

        if member_run_output is not None:
            member_run_output.requirements = reqs
            updated_tools = [req.tool_execution for req in reqs if req.tool_execution is not None]
            if updated_tools and member_run_output.tools:
                updated_map = {t.tool_call_id: t for t in updated_tools}
                member_run_output.tools = [updated_map.get(t.tool_call_id, t) for t in member_run_output.tools]

            member_response_stream = member.continue_run(  # type: ignore[call-overload]
                run_response=member_run_output,  # type: ignore[arg-type]
                session_id=session.session_id,
                stream=True,
                stream_events=stream_events or team.stream_member_events,
                yield_run_output=True,
                **member_continue_kwargs,
            )
        else:
            member_response_stream = member.continue_run(  # type: ignore[call-overload]
                run_id=member_run_id,
                requirements=reqs,
                session_id=session.session_id,
                stream=True,
                stream_events=stream_events or team.stream_member_events,
                yield_run_output=True,
                **member_continue_kwargs,
            )

        # Iterate the member's streaming response — yield intermediate events,
        member_response: Optional[Union[RunOutput, TeamRunOutput]] = None
        for event in member_response_stream:  # type: ignore[union-attr]
            if isinstance(event, (RunOutput, TeamRunOutput)):
                member_response = event
                continue  # Don't yield the final RunOutput

            if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
                raise_if_cancelled(run_response.run_id)  # type: ignore

            # Set parent_run_id on member events (same as delegate_task_to_member)
            event.parent_run_id = getattr(event, "parent_run_id", None) or run_response.run_id

            # Forward member terminals regardless of stream_events so the wire always sees a terminal.
            if isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES) or stream_events or team.stream_member_events:
                yield handle_event(
                    event,
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

        if member_response is None:
            log_warning(f"Member {member_id} streaming did not yield a final RunOutput")
            member_results.append(f"[{member.name or member_id}]: Task completed (no final output)")
        elif getattr(member_response, "is_paused", False):
            from agno.team._tools import _propagate_member_pause

            _propagate_member_pause(run_response, member, member_response)
        else:
            session.upsert_run(member_response)
            content = getattr(member_response, "content", None) or "Task completed"
            member_results.append(f"[{member.name or member_id}]: {content}")

        # Clear _member_run_response references to allow GC of the member RunOutput
        for req in reqs:
            req._member_run_response = None


async def _aroute_requirements_to_members(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    run_context: Optional[RunContext] = None,
) -> List[str]:
    """Route member requirements back to the appropriate member agents (async, non-streaming).

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
        member_run_output = getattr(reqs[0], "_member_run_response", None)
        member_run_id = reqs[0].member_run_id if reqs else None

        if member_run_output is None and member_run_id:
            # Same-process resume: the paused member output is still held on the live team run.
            if run_response.member_responses:
                for sibling_response in run_response.member_responses:
                    if getattr(sibling_response, "run_id", None) == member_run_id:
                        member_run_output = sibling_response
                        break
            # After process restart: member_responses is empty (it's only assembled at runtime),
            # so fall back to the team session's sibling runs persisted in the DB.
            if member_run_output is None and session is not None and session.runs:
                for session_run in session.runs:
                    if getattr(session_run, "run_id", None) == member_run_id:
                        member_run_output = session_run  # type: ignore[assignment]
                        break

        member_run_id = getattr(member_run_output, "run_id", None) if member_run_output is not None else member_run_id
        if member_run_id and run_response.run_id is not None:
            await aregister_member_run(run_response.run_id, member_run_id)

        # Forward team's run_context state to the member so dependencies and
        # session_state remain accessible to member tools after continue_run.
        member_continue_kwargs = _member_continue_kwargs_from_run_context(run_context)

        if member_run_output is not None:
            member_run_output.requirements = reqs
            updated_tools = [req.tool_execution for req in reqs if req.tool_execution is not None]
            if updated_tools and member_run_output.tools:
                updated_map = {t.tool_call_id: t for t in updated_tools}
                member_run_output.tools = [updated_map.get(t.tool_call_id, t) for t in member_run_output.tools]

            member_response = await member.acontinue_run(  # type: ignore[misc]
                run_response=member_run_output,  # type: ignore[arg-type]
                session_id=session.session_id,
                **member_continue_kwargs,
            )
        else:
            member_response = await member.acontinue_run(  # type: ignore[misc]
                run_id=member_run_id,
                requirements=reqs,
                session_id=session.session_id,
                **member_continue_kwargs,
            )

        # Clear _member_run_response references to allow GC of the member RunOutput
        for req in reqs:
            req._member_run_response = None

        if getattr(member_response, "is_paused", False):
            from agno.team._tools import _propagate_member_pause

            _propagate_member_pause(run_response, member, member_response)
            return None
        else:
            # Update the member's run in the team session so its status is persisted
            # (member agents skip save_session when team_id is set, so we do it here)
            session.upsert_run(member_response)

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


async def _aroute_requirements_to_members_stream(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    member_results: List[str],
    run_context: Optional[RunContext] = None,
    stream_events: bool = False,
) -> AsyncIterator[Union[TeamRunOutputEvent, RunOutputEvent]]:
    """Route member requirements back to the appropriate member agents (async, streaming).

    Yields member streaming events (RunContent, etc.) to the caller, and appends
    result descriptions to the provided member_results list.

    Following the same pattern as adelegate_task_to_member: iterate the member's
    async streaming response, yield intermediate events, capture the final RunOutput.

    Note: When streaming, members are processed sequentially (not with asyncio.gather)
    because we need to yield events as they arrive.

    Args:
        member_results: Mutable list to collect member result strings.

    Yields:
        Member streaming events (RunOutputEvent, TeamRunOutputEvent).
    """
    from agno.run.requirement import RunRequirement
    from agno.team._tools import _find_member_route_by_id

    # Group requirements by member
    member_reqs: Dict[str, List[RunRequirement]] = {}
    for req in run_response.requirements or []:
        mid = getattr(req, "member_agent_id", None)
        if mid is not None:
            member_reqs.setdefault(mid, []).append(req)

    for member_id, reqs in member_reqs.items():
        route_result = _find_member_route_by_id(team, member_id, run_context=run_context)
        if route_result is None:
            log_warning(f"Could not find member with ID {member_id} for continue_run routing")
            member_results.append(f"[{member_id}]: Could not route requirement — member not found")
            continue

        _, member = route_result

        member_run_output = getattr(reqs[0], "_member_run_response", None)
        member_run_id = reqs[0].member_run_id if reqs else None

        if member_run_output is None and member_run_id:
            # Same-process resume: the paused member output is still held on the live team run.
            if run_response.member_responses:
                for sibling_response in run_response.member_responses:
                    if getattr(sibling_response, "run_id", None) == member_run_id:
                        member_run_output = sibling_response
                        break
            # After process restart: member_responses is empty (it's only assembled at runtime),
            # so fall back to the team session's sibling runs persisted in the DB.
            if member_run_output is None and session is not None and session.runs:
                for session_run in session.runs:
                    if getattr(session_run, "run_id", None) == member_run_id:
                        member_run_output = session_run  # type: ignore[assignment]
                        break

        member_run_id = getattr(member_run_output, "run_id", None) if member_run_output is not None else member_run_id
        if member_run_id and run_response.run_id is not None:
            await aregister_member_run(run_response.run_id, member_run_id)

        # Forward team's run_context state to the member so dependencies and
        # session_state remain accessible to member tools after continue_run.
        member_continue_kwargs = _member_continue_kwargs_from_run_context(run_context)

        if member_run_output is not None:
            member_run_output.requirements = reqs
            updated_tools = [req.tool_execution for req in reqs if req.tool_execution is not None]
            if updated_tools and member_run_output.tools:
                updated_map = {t.tool_call_id: t for t in updated_tools}
                member_run_output.tools = [updated_map.get(t.tool_call_id, t) for t in member_run_output.tools]

            member_response_stream = member.acontinue_run(  # type: ignore[call-overload]
                run_response=member_run_output,  # type: ignore[arg-type]
                session_id=session.session_id,
                stream=True,
                stream_events=stream_events or team.stream_member_events,
                yield_run_output=True,
                **member_continue_kwargs,
            )
        else:
            member_response_stream = member.acontinue_run(  # type: ignore[call-overload]
                run_id=member_run_id,
                requirements=reqs,
                session_id=session.session_id,
                stream=True,
                stream_events=stream_events or team.stream_member_events,
                yield_run_output=True,
                **member_continue_kwargs,
            )

        # Iterate the member's async streaming response — yield intermediate events,
        member_response: Optional[Union[RunOutput, TeamRunOutput]] = None
        async for event in member_response_stream:  # type: ignore[union-attr]
            if isinstance(event, (RunOutput, TeamRunOutput)):
                member_response = event
                continue  # Don't yield the final RunOutput

            if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
                await araise_if_cancelled(run_response.run_id)  # type: ignore

            # Set parent_run_id on member events (same as adelegate_task_to_member)
            event.parent_run_id = getattr(event, "parent_run_id", None) or run_response.run_id

            # Forward member terminals regardless of stream_events so the wire always sees a terminal.
            if isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES) or stream_events or team.stream_member_events:
                yield handle_event(
                    event,
                    run_response,
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

        if member_response is None:
            log_warning(f"Member {member_id} streaming did not yield a final RunOutput")
            member_results.append(f"[{member.name or member_id}]: Task completed (no final output)")
        elif getattr(member_response, "is_paused", False):
            from agno.team._tools import _propagate_member_pause

            _propagate_member_pause(run_response, member, member_response)
        else:
            session.upsert_run(member_response)
            content = getattr(member_response, "content", None) or "Task completed"
            member_results.append(f"[{member.name or member_id}]: {content}")

        # Clear _member_run_response references to allow GC of the member RunOutput
        for req in reqs:
            req._member_run_response = None


def _build_continuation_message(member_results: List[str]) -> str:
    """Build a user message from member results to feed back into the team model."""
    if not member_results:
        return "The delegated task has been completed."
    parts = ["Member results after human-in-the-loop resolution:"]
    parts.extend(member_results)
    return "\n".join(parts)


def _tool_result_requires_human_input(tool: ToolExecution) -> bool:
    result = tool.result or ""
    return isinstance(result, str) and "requires human input" in result.lower()


def _prepare_member_hitl_continuation(
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    member_results: List[str],
) -> None:
    """Prepare run_response and run_messages for member HITL continuation.

    Updates the delegate_task_to_member/delegate_task_to_members tool result in both
    run_response.tools and the corresponding message in run_messages. Also resets run
    state for continuation.

    This is called after the member agent's HITL has been resolved and we need to
    continue the team run with the member's results.
    """

    continuation_message = _build_continuation_message(member_results)

    target_tool_call_ids: set[str] = set()
    for tool in run_response.tools or []:
        if tool.tool_name in {
            "delegate_task_to_member",
            "delegate_task_to_members",
        } and _tool_result_requires_human_input(tool):
            tool.result = continuation_message
            if tool.tool_call_id is not None:
                target_tool_call_ids.add(tool.tool_call_id)

    if not target_tool_call_ids:
        for tool in run_response.tools or []:
            if _tool_result_requires_human_input(tool):
                tool.result = continuation_message
                if tool.tool_call_id is not None:
                    target_tool_call_ids.add(tool.tool_call_id)

    # Update the existing tool result messages in run_messages
    if target_tool_call_ids:
        for msg in run_messages.messages:
            if msg.role == "tool" and msg.tool_call_id in target_tool_call_ids:
                msg.content = continuation_message

    # Reset run state for continuation
    run_response.status = RunStatus.running
    run_response.content = None


async def _ahandle_model_response_for_continue(
    team: "Team",
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    run_context: RunContext,
    tools: List[Any],
    team_session: "TeamSession",
    response_format: Optional[Any] = None,
) -> Optional[TeamRunOutput]:
    """Handle async model response for team continue_run (non-streaming).

    Shared logic for both team-level and member HITL continuation.
    Returns the run_response if paused (needs to return early), otherwise None.
    """
    from agno.team._response import (
        _convert_response_to_structured_format,
        _update_run_response,
        agenerate_response_with_output_model,
        aparse_response_with_parser_model,
    )

    team.model = cast(Model, team.model)
    model_response: ModelResponse = await acall_model_with_fallback(
        team.model,
        team.fallback_config,
        messages=run_messages.messages,
        response_format=response_format,
        tools=tools,
        tool_choice=team.tool_choice,
        tool_call_limit=team.tool_call_limit,
        run_response=run_response,
        send_media_to_model=team.send_media_to_model,
        compression_manager=team.compression_manager if team.compress_tool_results else None,
        after_tool_results=abuild_team_after_tool_results_callback(
            team, run_response, team_session, run_messages, run_context
        ),
    )

    await araise_if_cancelled(run_response.run_id)  # type: ignore

    await agenerate_response_with_output_model(team, model_response, run_messages, run_response=run_response)
    await aparse_response_with_parser_model(
        team, model_response, run_messages, run_context=run_context, run_response=run_response
    )

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
            team, run_response=run_response, session=team_session, run_context=run_context
        )

    _convert_response_to_structured_format(team, run_response=run_response, run_context=run_context)
    store_media_util(run_response, model_response)

    return None  # Continue with post-hooks


# ---------------------------------------------------------------------------
# Continue / fork / truncate helpers
# Mirrors the agent-side helpers in agno/agent/_run.py with one additional
# concern: team runs have member RunOutput rows in session.runs (linked via
# parent_run_id). On fork, these get deep-copied with fresh run_ids so the
# forked team owns its own member rows (per design decision).
# ---------------------------------------------------------------------------


def _truncate_team_run_to_checkpoint(run_response: "TeamRunOutput", message_index: int) -> None:
    """Truncate the team run's messages to length ``message_index`` and
    prune tools / requirements that referenced removed messages.

    Time-travel for teams. Mirrors :func:`agno.agent._run._truncate_run_to_checkpoint`
    in shape; the only team-specific consideration is that ``member_responses``
    survives truncation untouched — a member completed delegation is a
    permanent fact in the team's history regardless of where we rewind to.
    """
    if run_response.messages is None or message_index < 0:
        return
    if message_index >= len(run_response.messages):
        return

    # Snap the boundary down so we never cut between an assistant tool_call and
    # its result (an orphaned call is rejected by most providers).
    from agno.utils.message import safe_truncation_index

    safe_index = safe_truncation_index(run_response.messages, message_index)
    if safe_index != message_index:
        log_warning(
            f"Truncation index {message_index} would orphan a tool call; "
            f"snapped to {safe_index} to keep the transcript valid."
        )
    message_index = safe_index

    run_response.messages = run_response.messages[:message_index]

    valid_tool_call_ids: set = set()
    for msg in run_response.messages:
        tool_call_id = getattr(msg, "tool_call_id", None)
        if tool_call_id:
            valid_tool_call_ids.add(tool_call_id)
        tool_calls = getattr(msg, "tool_calls", None) or []
        for tc in tool_calls:
            tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
            if tc_id:
                valid_tool_call_ids.add(tc_id)

    if run_response.tools:
        run_response.tools = [t for t in run_response.tools if t.tool_call_id in valid_tool_call_ids]
    if run_response.requirements:
        run_response.requirements = [
            req
            for req in run_response.requirements
            if req.tool_execution and req.tool_execution.tool_call_id in valid_tool_call_ids
        ]

    run_response.last_checkpoint_at_message_index = message_index


def _fork_team_run(run_response: "TeamRunOutput", message_index: int) -> "TeamRunOutput":
    """Deep-clone a team run with a new ``run_id``, set fork metadata, and
    truncate to ``message_index``.

    Scope is the team's own state (messages, tools, requirements, metrics).
    Member runs that the original team produced stay where they are — they
    are durable records of delegation work attached to the **original** team
    via ``parent_run_id``. The forked team's ``member_responses`` field
    points at those same member objects (deep-copied so mutating the fork
    can't corrupt them), but no new member rows are written to the session.

    Rationale: from the team's perspective a member is just a tool the team
    delegated to — its output is already baked into the team's messages.
    Forking the team is parity with agent forking; member state is out of
    scope, same as fallback models / parser models / followups.

    Resets ``metrics`` and ``created_at`` so the fork reports only its own
    work — same invariant as agent's :func:`_fork_run`.
    """
    import copy
    from time import time as _time

    from agno.utils.message import safe_truncation_index

    # Snap to a pair-safe boundary so fork metadata matches the truncation that
    # _truncate_team_run_to_checkpoint will actually perform.
    message_index = safe_truncation_index(run_response.messages or [], message_index)

    forked = copy.deepcopy(run_response)
    forked.run_id = str(uuid4())
    forked.forked_from_run_id = run_response.run_id
    forked.forked_from_message_index = message_index
    forked.metrics = RunMetrics()
    forked.created_at = int(_time())

    _truncate_team_run_to_checkpoint(forked, message_index)
    return forked


def _apply_continue_modifiers_team(
    run_response: "TeamRunOutput",
    fork: bool,
    message_index: Optional[int],
) -> "TeamRunOutput":
    """Apply ``fork`` and/or ``message_index`` to a loaded team run_response.

    Mirrors agent's :func:`_apply_continue_modifiers`. Returns the same
    instance when only truncating, a new instance (with cloned members)
    when forking.
    """
    if fork:
        idx = message_index if message_index is not None else len(run_response.messages or [])
        return _fork_team_run(run_response, idx)
    if message_index is not None:
        _truncate_team_run_to_checkpoint(run_response, message_index)
    return run_response


def _will_truncate_team_run(run_response: "TeamRunOutput", message_index: Optional[int]) -> bool:
    if message_index is None:
        return False
    return 0 <= message_index < len(run_response.messages or [])


def _find_regenerate_checkpoint_team(run_response: "TeamRunOutput") -> int:
    """For ``regenerate=True``, compute the message index to truncate to.

    Mirrors agent's :func:`_find_regenerate_checkpoint` (parity with PR
    #7157's ``_strip_final_assistant_messages``): drop ONLY the trailing
    assistant messages without ``tool_calls`` — i.e. the final response.
    Intermediate tool-calling assistant messages and their tool results
    are preserved, so regeneration produces a fresh summary of the same
    tool outputs without re-running tools.
    """
    messages = run_response.messages or []
    i = len(messages)
    while i > 0 and messages[i - 1].role == "assistant" and not messages[i - 1].tool_calls:
        i -= 1
    if i == 0:
        raise ValueError("Cannot regenerate: team run has no non-assistant messages to regenerate from.")
    return i


def _find_last_user_message_index_team(run_response: "TeamRunOutput") -> int:
    """For ``continue_from="last_user"``: walk backwards to the last user
    message and return its index + 1. Drops everything past it (including
    intermediate tool exchanges) — distinct from regenerate, which keeps
    intermediate tool calls.
    """
    messages = run_response.messages or []
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            return i + 1
    raise ValueError("Cannot resolve `continue_from='last_user'`: team run has no user messages.")


def _resolve_continue_from_team(
    run_response: "TeamRunOutput",
    *,
    continue_from: Union[int, Literal["end", "last_user"]],
    regenerate: bool = False,
) -> int:
    """Resolve the public continuation selector into a message boundary index.

    See :func:`agno.agent._run._resolve_continue_from` for the agent equivalent;
    ``"last_user"`` and ``regenerate=True`` have intentionally different
    semantics (the latter preserves intermediate tool exchanges).
    """
    if regenerate:
        if continue_from in ("end", "last_user"):
            return _find_regenerate_checkpoint_team(run_response)
        raise ValueError("`regenerate=True` derives the continuation boundary automatically.")

    messages = run_response.messages or []
    if isinstance(continue_from, int):
        return continue_from
    if continue_from == "end":
        return len(messages)
    if continue_from == "last_user":
        return _find_last_user_message_index_team(run_response)

    raise ValueError("`continue_from` must be an integer message index, 'end', or 'last_user'.")


def _normalize_regenerate_params_team(
    run_response: Optional["TeamRunOutput"],
    *,
    regenerate: bool,
    replace_original: Optional[bool],
    additional_instructions: Optional[str],
    fork: bool,
    continue_index: Optional[int],
    input: Optional[str],
) -> Tuple[bool, Optional[int], Optional[str]]:
    """Normalize regenerate-sugar params for teams. Mirrors agent helper.

    ``regenerate=True`` ALWAYS forks (1-run-1-loop invariant); the source run is
    always retained in storage. ``replace_original`` controls history visibility
    of the source only. It defaults to True: the source is marked ``REGENERATED``
    so history-builders skip it and the new run replaces it. Pass False to keep
    both runs visible. Only meaningful with ``regenerate=True``.
    """
    if additional_instructions is not None and input is not None:
        raise ValueError("Provide either `additional_instructions` or `input`, not both.")
    if replace_original is not None and not regenerate:
        raise ValueError("`replace_original` only makes sense with `regenerate=True`.")

    if not regenerate:
        return fork, continue_index, input

    if fork:
        raise ValueError(
            "`regenerate=True` derives the destructive/preserving choice from "
            "`replace_original`; do not pass `fork=True` directly."
        )
    if run_response is None:
        raise ValueError("`regenerate=True` requires a loaded run_response to compute the checkpoint.")

    resolved_input = additional_instructions if additional_instructions is not None else input
    return (True, _find_regenerate_checkpoint_team(run_response), resolved_input)


def _maybe_append_input_message_team(
    run_response: "TeamRunOutput",
    new_input: Optional[str],
    team: "Team",
) -> None:
    """Append a new user-role message to the team run's ``messages`` so the
    model loop sees it. Used when the caller passes ``input=`` or
    ``additional_instructions=`` to /continue.
    """
    if not new_input:
        return
    new_message = Message(role="user", content=new_input)
    if run_response.messages is None:
        run_response.messages = [new_message]
    else:
        run_response.messages.append(new_message)


# ---------------------------------------------------------------------------
# Session forking — mirrors agent's fork_session_dispatch
# ---------------------------------------------------------------------------


def _build_forked_team_session(source_session: TeamSession, new_user_id: Optional[str]) -> TeamSession:
    """Deep-copy ``source_session`` into a brand-new ``TeamSession`` with a
    fresh ``session_id`` and fresh ``run_id``s for every copied run.

    Lineage shape mirrors the agent:
    - ``session.session_data["forked_from_session_id"]``: the immediate parent
      session_id (overwritten on each re-fork).
    - ``run.forked_from_session_id``: each run's **original** session_id, set
      only-if-empty so nested forks keep pointing at the root.
    """
    import copy
    import time as _time

    now = int(_time.time())
    new_session_id = str(uuid4())
    forked_runs = copy.deepcopy(source_session.runs or [])

    for run in forked_runs:
        run.run_id = str(uuid4())
        run.session_id = new_session_id
        if not getattr(run, "forked_from_session_id", None):
            run.forked_from_session_id = source_session.session_id

    new_session_data = copy.deepcopy(source_session.session_data) or {}
    new_session_data["forked_from_session_id"] = source_session.session_id

    return TeamSession(
        session_id=new_session_id,
        team_id=source_session.team_id,
        user_id=new_user_id or source_session.user_id,
        workflow_id=source_session.workflow_id,
        team_data=copy.deepcopy(source_session.team_data),
        session_data=new_session_data,
        metadata=copy.deepcopy(source_session.metadata),
        runs=forked_runs,
        summary=copy.deepcopy(source_session.summary),
        created_at=now,
        updated_at=now,
    )


def fork_session_dispatch(
    team: "Team",
    *,
    source_session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    """Branch a team session into a new independent session (sync)."""
    from agno.team._init import _has_async_db
    from agno.team._storage import _read_or_create_session

    if _has_async_db(team):
        raise RuntimeError("`fork_session` is not supported with an async database. Use `afork_session` instead.")

    source_session_id = source_session_id or team.session_id
    if source_session_id is None:
        raise ValueError("source_session_id is required to fork a session.")

    team.initialize_team()
    source_session = _read_or_create_session(team, session_id=source_session_id, user_id=user_id)
    if not source_session.runs:
        raise ValueError("Source session has no runs to fork.")

    new_session = _build_forked_team_session(source_session, new_user_id=user_id)
    team.save_session(session=new_session)
    return new_session.session_id


async def afork_session_dispatch(
    team: "Team",
    *,
    source_session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    """Async variant of :func:`fork_session_dispatch`."""
    from agno.team._init import _has_async_db
    from agno.team._storage import _aread_or_create_session, _read_or_create_session

    source_session_id = source_session_id or team.session_id
    if source_session_id is None:
        raise ValueError("source_session_id is required to fork a session.")

    team.initialize_team()

    if _has_async_db(team):
        source_session = await _aread_or_create_session(team, session_id=source_session_id, user_id=user_id)
    else:
        source_session = _read_or_create_session(team, session_id=source_session_id, user_id=user_id)

    if not source_session.runs:
        raise ValueError("Source session has no runs to fork.")

    new_session = _build_forked_team_session(source_session, new_user_id=user_id)
    if _has_async_db(team):
        await team.asave_session(session=new_session)
    else:
        team.save_session(session=new_session)
    return new_session.session_id


def continue_run_dispatch(
    team: "Team",
    run_response: Optional[TeamRunOutput] = None,
    *,
    run_id: Optional[str] = None,
    requirements: Optional[List[Any]] = None,
    # --- Continue sugar (mirrors agent dispatch) ---
    input: Optional[str] = None,
    continue_from: Union[int, Literal["end", "last_user"]] = "end",
    fork: bool = False,
    regenerate: bool = False,
    replace_original: Optional[bool] = None,
    additional_instructions: Optional[str] = None,
    # --- Stream/control ---
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

    Handles both team-level tool pauses and member-agent tool pauses, plus
    the snapshot dispatch (regenerate / fork / time-travel) — see the
    corresponding agent docstring in ``agno/agent/_run.py`` for the full
    variant table. Auto-fork-on-COMPLETED is enforced: continuing a
    COMPLETED team run produces a new ``run_id`` with the member rows
    cloned (per ADR — forked teams own their member rows).
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
        runs = team_session.runs or []
        run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
        if run_response is None:
            raise RuntimeError(f"No runs found for run ID {run_id}")

    run_response = cast(TeamRunOutput, run_response)

    if run_response.status == RunStatus.cancelled:
        raise ValueError(f"Cannot continue run {run_response.run_id}: run is cancelled")

    # --- Snapshot dispatch (regenerate / fork / time-travel) ----------------
    continue_index: Optional[int] = _resolve_continue_from_team(
        run_response,
        continue_from=continue_from,
        regenerate=regenerate,
    )
    # Normalize sugar params into canonical (fork, continue_index, input)
    # form. Mirrors the agent dispatch — see agno/agent/_run.py.
    fork, continue_index, input = _normalize_regenerate_params_team(
        run_response,
        regenerate=regenerate,
        replace_original=replace_original,
        additional_instructions=additional_instructions,
        fork=fork,
        continue_index=continue_index,
        input=input,
    )
    original_run_id_for_lineage = run_response.run_id if regenerate else None

    # Auto-fork on COMPLETED — preserves the "1 run = 1 model loop" invariant.
    # A COMPLETED loop ran end-to-end; any further model call is a NEW loop
    # and must get a new run_id. Mid-flight states (RUNNING / PAUSED) resume
    # in place because their loop never finished. ERROR / CANCELLED are NOT
    # auto-forked (retry semantics) — same call as agent.
    if not fork and run_response.status == RunStatus.completed:
        fork = True

    # Apply modifiers BEFORE the requirements machinery. If we forked, the
    # rest of the dispatch operates on the new run with cloned members.
    _did_snapshot_dispatch = fork or _will_truncate_team_run(run_response, continue_index)
    run_response = _apply_continue_modifiers_team(run_response, fork, continue_index)
    if regenerate and original_run_id_for_lineage:
        run_response.regenerated_from = original_run_id_for_lineage
        if replace_original is not False and run_response.forked_from_run_id:
            # Mark the original run REGENERATED so history builders skip it.
            for r in team_session.runs or []:
                if r.run_id == original_run_id_for_lineage:
                    r.status = RunStatus.regenerated
                    break

    # Append the new user-message (from input / additional_instructions) so
    # the model loop picks it up.
    if input:
        _maybe_append_input_message_team(run_response, input, team)

    # A freshly-forked run has no PAUSED requirements contract — skip the
    # HITL machinery and route straight to the model loop. Member-level
    # tool resolution for HITL is a property of the SOURCE run; the fork
    # is a new attempt and its tools/messages are seeded from the
    # snapshot.
    if _did_snapshot_dispatch:
        # Reset run state for a fresh model loop on the forked run.
        run_response.status = RunStatus.running
        run_response.content = None

        response_format = get_response_format(team, run_context=run_context) if team.parser_model is None else None
        team.model = cast(Model, team.model)

        team_run_context_local: Dict[str, Any] = {}
        _tools_fork = _determine_tools_for_model(
            team,
            model=team.model,
            run_response=run_response,
            run_context=run_context,
            team_run_context=team_run_context_local,
            session=team_session,
            user_id=user_id,
            async_mode=False,
            stream=opts.stream or False,
            stream_events=opts.stream_events or False,
        )

        input_messages = run_response.messages or []
        run_messages = _get_continue_run_messages(
            team,
            input=input_messages,
            session=team_session,
            add_history_to_context=team.add_history_to_context,
            run_context=run_context,
        )

        log_debug(f"Team Continue Run (forked): {run_response.run_id}", center=True)

        if opts.stream:
            return _continue_run_stream(
                team,
                run_response=run_response,
                run_messages=run_messages,
                run_context=run_context,
                tools=_tools_fork,
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
                tools=_tools_fork,
                session=team_session,
                user_id=user_id,
                response_format=response_format,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )
    # --- End snapshot dispatch ----------------------------------------------

    # Save old requirements before overwriting — needed to preserve approval fields for member-level tools
    old_requirements = run_response.requirements

    # Normalize and apply requirements
    if requirements:
        requirements = _normalize_requirements_payload(requirements)
        run_response.requirements = requirements
        # Update tools from requirements, preserving approval fields the FE omits
        updated_tools = [req.tool_execution for req in requirements if req.tool_execution is not None]
        if updated_tools and run_response.tools:
            updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
            run_response.tools = _merge_tools_preserving_approval(run_response.tools, updated_tools_map)
        elif updated_tools:
            run_response.tools = updated_tools
        _backfill_approval_to_requirements(run_response, old_requirements=old_requirements)

        # Also apply any resolved approval
        if run_response.tools:
            from agno.run.approval import check_and_apply_approval_resolution

            try:
                check_and_apply_approval_resolution(team.db, run_id_resolved, run_response)
            except RuntimeError:
                raise ValueError(
                    "To continue a run from a given run_id, the requirements parameter must be provided "
                    "(or resolve an admin approval first)."
                )
    elif run_response.tools:
        from agno.run.approval import check_and_apply_approval_resolution

        try:
            check_and_apply_approval_resolution(team.db, run_id_resolved, run_response)
        except RuntimeError:
            # No resolved approval found — fall through to bare-resume rather
            # than raising. The run may be a crashed mid-flight run (RUNNING /
            # ERROR / CANCELLED) where we want to resume from persisted
            # messages, not insist on HITL requirements.
            _did_snapshot_dispatch = True  # treat as resume-only; route to team-leader model call
    else:
        # No requirements AND no tools — this is a bare resume of a mid-flight
        # run (RUNNING / ERROR / CANCELLED that crashed before any tool batch).
        # Don't raise; let the team-leader model loop run with whatever
        # messages survived in run_response.
        _did_snapshot_dispatch = True

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

        if opts.stream:
            # Streaming: use the generator variant that yields member events.
            # We collect member_results via a mutable list and chain with the
            # team continuation stream below.
            member_event_stream = _route_requirements_to_members_stream(
                team,
                run_response=run_response,
                session=team_session,
                member_results=member_results,
                run_context=run_context,
                stream_events=opts.stream_events or False,
            )
        else:
            member_event_stream = None
            member_results = _route_requirements_to_members(
                team,
                run_response=run_response,
                session=team_session,
                run_context=run_context,
            )

        # For non-streaming, member routing is done eagerly above.
        # For streaming, we must consume member events lazily inside a returned generator.
        # But first we need to check for chained pauses AFTER member routing completes.
        # So for streaming, we defer everything to a wrapper generator.
        if opts.stream and member_event_stream is not None:
            return _continue_run_dispatch_stream_with_member_events(
                team=team,
                run_response=run_response,
                member_event_stream=member_event_stream,
                member_results=member_results,
                original_member_req_ids=original_member_req_ids,
                team_level_reqs=team_level_reqs,
                has_team_level=has_team_level,
                team_session=team_session,
                run_context=run_context,
                opts=opts,
                user_id=user_id,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )

        # Non-streaming: merge and check for chained pauses
        newly_propagated = [r for r in (run_response.requirements or []) if id(r) not in original_member_req_ids]
        run_response.requirements = team_level_reqs + newly_propagated

        # Check if any members are still paused
        if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
            from agno.team import _hooks

            return _hooks.handle_team_run_paused(
                team, run_response=run_response, session=team_session, run_context=run_context
            )

    # Handle team-level tool resolution
    if has_team_level or _did_snapshot_dispatch:
        # Includes _did_snapshot_dispatch: bare-resume of a crashed run (no
        # requirements, no tools) still needs the team-leader model call to
        # produce a response. Without this, those runs would fall through
        # with no model invocation.
        # Guard: if team-level requirements are unresolved, re-pause instead of auto-rejecting
        unresolved_team = [
            r
            for r in (run_response.requirements or [])
            if getattr(r, "member_agent_id", None) is None and not r.is_resolved()
        ]
        if unresolved_team:
            from agno.team import _hooks

            if opts.stream:
                return _hooks.handle_team_run_paused_stream(
                    team, run_response=run_response, session=team_session, run_context=run_context
                )  # type: ignore
            else:
                return _hooks.handle_team_run_paused(
                    team, run_response=run_response, session=team_session, run_context=run_context
                )

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
        run_messages = _get_continue_run_messages(
            team,
            input=input_messages,
            session=team_session,
            add_history_to_context=team.add_history_to_context,
            run_context=run_context,
        )

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

    # Member-only case: continue the same run with member results
    if member_results and not has_team_level:
        response_format = get_response_format(team, run_context=run_context) if team.parser_model is None else None
        team.model = cast(Model, team.model)

        # Prepare tools for the continuation
        team_run_context: Dict[str, Any] = {}  # type: ignore[no-redef]
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

        # Get existing messages
        input_messages = run_response.messages or []
        run_messages = _get_continue_run_messages(
            team,
            input=input_messages,
            session=team_session,
            add_history_to_context=team.add_history_to_context,
            run_context=run_context,
        )

        # Prepare for member HITL continuation
        _prepare_member_hitl_continuation(run_response, run_messages, member_results)

        log_debug(f"Team Continue Run (Member HITL): {run_response.run_id}", center=True)

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

    # Fallback: nothing to do
    run_response.status = RunStatus.completed
    _cleanup_and_store(team, run_response=run_response, session=team_session)
    return run_response


def _continue_run_dispatch_stream_with_member_events(
    team: "Team",
    run_response: TeamRunOutput,
    member_event_stream: Iterator[Union[TeamRunOutputEvent, RunOutputEvent]],
    member_results: List[str],
    original_member_req_ids: set,
    team_level_reqs: list,
    has_team_level: bool,
    team_session: TeamSession,
    run_context: RunContext,
    opts: "ResolvedRunOptions",
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> Iterator[Union[TeamRunOutputEvent, RunOutputEvent, TeamRunOutput]]:
    """Sync streaming wrapper that yields member events then continues the team run.

    This generator first yields all member streaming events from the member routing,
    then proceeds with the normal team continuation (model call, etc.).
    """
    from agno.team._response import get_response_format
    from agno.team._tools import _determine_tools_for_model

    # Phase 1: Yield member streaming events
    try:
        yield from member_event_stream
    except RunCancelledException as e:
        run_response = _handle_team_run_cancellation(run_response, e, session=team_session)
        cancelled_event, completed_event = _build_team_cancel_terminal_events(
            team, run_response, error=e, run_context=run_context
        )
        try:
            _cleanup_and_store(team, run_response=run_response, session=team_session, run_context=run_context)
        except Exception as store_err:
            log_warning(f"Failed to persist cancelled run: {store_err}")
        yield cancelled_event
        yield completed_event
        if opts.yield_run_output:
            yield run_response
        return
    except KeyboardInterrupt:
        run_response = _handle_team_run_cancellation(run_response, KeyboardInterrupt(), session=team_session)
        cancelled_event, completed_event = _build_team_cancel_terminal_events(
            team, run_response, error=KeyboardInterrupt(), run_context=run_context
        )
        try:
            _cleanup_and_store(team, run_response=run_response, session=team_session, run_context=run_context)
        except Exception as store_err:
            log_warning(f"Failed to persist cancelled run: {store_err}")
        yield cancelled_event
        yield completed_event
        if opts.yield_run_output:
            yield run_response
        return

    # Phase 2: After member routing completes, check for chained pauses
    newly_propagated = [r for r in (run_response.requirements or []) if id(r) not in original_member_req_ids]
    run_response.requirements = team_level_reqs + newly_propagated

    if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
        from agno.team import _hooks

        yield from _hooks.handle_team_run_paused_stream(
            team, run_response=run_response, session=team_session, run_context=run_context
        )
        return

    # Phase 3: Continue the team run with member results
    if has_team_level:
        unresolved_team = [
            r
            for r in (run_response.requirements or [])
            if getattr(r, "member_agent_id", None) is None and not r.is_resolved()
        ]
        if unresolved_team:
            from agno.team import _hooks

            yield from _hooks.handle_team_run_paused_stream(
                team, run_response=run_response, session=team_session, run_context=run_context
            )
            return

        response_format = get_response_format(team, run_context=run_context) if team.parser_model is None else None
        team.model = cast(Model, team.model)

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
            stream=True,
            stream_events=opts.stream_events or False,
        )

        input_messages = run_response.messages or []
        run_messages = _get_continue_run_messages(
            team,
            input=input_messages,
            session=team_session,
            add_history_to_context=team.add_history_to_context,
            run_context=run_context,
        )

        _handle_team_tool_call_updates(team, run_response=run_response, run_messages=run_messages, tools=_tools)

        run_response.status = RunStatus.running
        run_response.content = None

        log_debug(f"Team Continue Run Start: {run_response.run_id}", center=True)

        yield from _continue_run_stream(
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
        return

    if member_results:
        response_format = get_response_format(team, run_context=run_context) if team.parser_model is None else None
        team.model = cast(Model, team.model)

        team_run_context_2: Dict[str, Any] = {}
        _tools = _determine_tools_for_model(
            team,
            model=team.model,
            run_response=run_response,
            run_context=run_context,
            team_run_context=team_run_context_2,
            session=team_session,
            user_id=user_id,
            async_mode=False,
            stream=True,
            stream_events=opts.stream_events or False,
        )

        input_messages = run_response.messages or []
        run_messages = _get_continue_run_messages(
            team,
            input=input_messages,
            session=team_session,
            add_history_to_context=team.add_history_to_context,
            run_context=run_context,
        )

        _prepare_member_hitl_continuation(run_response, run_messages, member_results)

        log_debug(f"Team Continue Run (Member HITL): {run_response.run_id}", center=True)

        yield from _continue_run_stream(
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
        return

    # Fallback: nothing more to do
    run_response.status = RunStatus.completed
    _cleanup_and_store(team, run_response=run_response, session=team_session)
    if opts.yield_run_output:
        yield run_response


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
                model_response: ModelResponse = call_model_with_fallback(
                    team.model,
                    team.fallback_config,
                    messages=run_messages.messages,
                    response_format=response_format,
                    tools=tools,
                    tool_choice=team.tool_choice,
                    tool_call_limit=team.tool_call_limit,
                    run_response=run_response,
                    send_media_to_model=team.send_media_to_model,
                    compression_manager=team.compression_manager if team.compress_tool_results else None,
                    after_tool_results=build_team_after_tool_results_callback(
                        team, run_response, session, run_messages, run_context
                    ),
                )

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # Parse with output/parser models if needed
                parse_response_with_output_model(team, model_response, run_messages, run_response=run_response)
                parse_response_with_parser_model(
                    team, model_response, run_messages, run_context=run_context, run_response=run_response
                )

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

                    return _hooks.handle_team_run_paused(
                        team, run_response=run_response, session=session, run_context=run_context
                    )

                # Convert to structured format
                _convert_response_to_structured_format(team, run_response=run_response, run_context=run_context)

                # Always add media to run_response for caller availability
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
                        team.session_summary_manager.create_session_summary(
                            session=session, run_metrics=run_response.metrics
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                # Complete
                run_response.status = RunStatus.completed
                _cleanup_and_store(team, run_response=run_response, session=session)

                log_team_telemetry(team, session_id=session.session_id, run_id=run_response.run_id)
                log_debug(f"Team Continue Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response

            except RunCancelledException as e:
                run_response = _handle_team_run_cancellation(run_response, e, run_messages, session=session)
                try:
                    _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                return run_response

            except (InputCheckError, OutputCheckError) as e:
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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
                run_response = _handle_team_run_cancellation(
                    run_response, KeyboardInterrupt(), run_messages, session=session
                )
                try:
                    _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                return run_response

            except Exception as e:
                if attempt < num_attempts - 1:
                    import time as _time

                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries
                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    _time.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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
                        if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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
                        if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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

                    yield from _hooks.handle_team_run_paused_stream(
                        team, run_response=run_response, session=session, run_context=run_context
                    )
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
                        team.session_summary_manager.create_session_summary(
                            session=session, run_metrics=run_response.metrics
                        )
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
                run_response = _handle_team_run_cancellation(run_response, e, run_messages, session=session)
                cancelled_event, completed_event = _build_team_cancel_terminal_events(
                    team,
                    run_response,
                    error=e,
                    run_context=run_context,
                )
                try:
                    _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break

            except (InputCheckError, OutputCheckError) as e:
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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
                run_response = _handle_team_run_cancellation(
                    run_response, KeyboardInterrupt(), run_messages, session=session
                )
                cancelled_event, completed_event = _build_team_cancel_terminal_events(
                    team,
                    run_response,
                    error=KeyboardInterrupt(),
                    run_context=run_context,
                )
                try:
                    _cleanup_and_store(team, run_response=run_response, session=session, run_context=run_context)
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break

            except Exception as e:
                if attempt < num_attempts - 1:
                    import time as _time

                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries
                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    _time.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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


async def _acontinue_run_background_stream(
    team: Team,
    run_context: RunContext,
    session_id: str,
    run_response: Optional[TeamRunOutput] = None,
    run_id: Optional[str] = None,
    requirements: Optional[List[Any]] = None,
    input: Optional[str] = None,
    continue_from: Union[int, Literal["end", "last_user"]] = "end",
    fork: bool = False,
    regenerate: bool = False,
    replace_original: Optional[bool] = None,
    additional_instructions: Optional[str] = None,
    user_id: Optional[str] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    stream_events: bool = False,
    yield_run_output: Optional[bool] = None,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> AsyncIterator[str]:
    """Background streaming continue-run that survives client disconnections.

    Mirrors _arun_background_stream but drives _acontinue_run_stream instead of
    _arun_stream. Used for HITL scenarios where a paused run resumes and the
    client needs reconnection support.

    Without this, team.acontinue_run(background=True, stream=True) would route
    to _acontinue_run_stream and yield raw TeamRunOutputEvent objects directly
    into FastAPI's StreamingResponse, which calls .encode() per chunk and
    raises::

        AttributeError: 'RunContinuedEvent' object has no attribute 'encode'

    1. Persists RUNNING status in DB
    2. Spawns a detached asyncio.Task that runs _acontinue_run_stream
    3. Buffers events (via event_buffer) and publishes to SSE subscribers
    4. Yields SSE-formatted strings via an asyncio.Queue
    """
    from agno.team._session import asave_session
    from agno.team._storage import _aread_or_create_session, _update_metadata

    _run_id = run_id or (run_response.run_id if run_response else None)
    if not _run_id:
        raise ValueError("run_id is required for background streaming continue-run")

    # 1. Persist RUNNING status so the run is visible in the DB immediately
    team_session = await _aread_or_create_session(team, session_id=session_id, user_id=user_id)
    _update_metadata(team, session=team_session)

    if run_response is not None:
        run_response.status = RunStatus.running
        team_session.upsert_run(run_response=run_response)
    await asave_session(team, session=team_session)

    log_info(f"Background continue-run stream {_run_id} persisted with RUNNING status")

    # 2. Create queue for forwarding SSE strings to the caller
    sse_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    # 3. Spawn detached background task
    async def _background_producer() -> None:
        from agno.os.managers import event_buffer, sse_subscriber_manager
        from agno.os.utils import format_sse_event_with_index

        try:
            async for event in _acontinue_run_stream(
                team,
                run_response=run_response,
                run_context=run_context,
                requirements=requirements,
                input=input,
                continue_from=continue_from,
                fork=fork,
                regenerate=regenerate,
                replace_original=replace_original,
                additional_instructions=additional_instructions,
                run_id=_run_id,
                user_id=user_id,
                session_id=session_id,
                response_format=response_format,
                stream_events=stream_events,
                yield_run_output=yield_run_output or False,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            ):
                if isinstance(event, TeamRunOutput):
                    continue

                # Buffer event for reconnection support
                event_index: Optional[int] = None
                try:
                    event_index = event_buffer.add_event(_run_id, event)
                except Exception:
                    log_warning(f"Failed to buffer event for continue-run {_run_id}")

                # Format as SSE
                sse_data = format_sse_event_with_index(event, event_index=event_index, run_id=_run_id)

                # Push to primary queue (original client)
                try:
                    await sse_queue.put(sse_data)
                except Exception:
                    log_warning(f"Failed to push SSE data to queue for continue-run {_run_id}")

                # Publish to SSE subscribers (resumed clients)
                try:
                    await sse_subscriber_manager.publish(
                        _run_id, event_index if event_index is not None else -1, sse_data
                    )
                except Exception:
                    log_warning(f"Failed to publish SSE data to subscribers for continue-run {_run_id}")

        except Exception:
            log_error(f"Background continue-run stream {_run_id} failed", exc_info=True)
            # Persist ERROR status
            try:
                if run_response is not None:
                    run_response.status = RunStatus.error
                    team_session.upsert_run(run_response=run_response)
                    await asave_session(team, session=team_session)
            except Exception:
                log_error(
                    f"Failed to persist error state for background continue-run stream {_run_id}",
                    exc_info=True,
                )

        finally:
            # Signal primary queue FIRST — unblocks the original client
            try:
                await sse_queue.put(None)
            except Exception:
                log_warning(f"Failed to signal primary queue for continue-run {_run_id} completion")

            # Mark run completed in event buffer
            try:
                final_status = (run_response.status if run_response else None) or RunStatus.completed
                event_buffer.set_run_completed(_run_id, final_status)
            except Exception:
                log_warning(f"Failed to mark continue-run {_run_id} as completed in event buffer")

            # Signal SSE subscribers that run is done (shielded to survive task cancellation)
            try:
                await asyncio.shield(sse_subscriber_manager.complete(_run_id))
            except (Exception, asyncio.CancelledError):
                log_warning(f"Failed to signal SSE subscribers for continue-run {_run_id} completion")

    task = asyncio.create_task(_background_producer())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # 4. Yield SSE strings from the queue
    while True:
        sse_data = await sse_queue.get()
        if sse_data is None:
            break
        yield sse_data


def acontinue_run_dispatch(  # type: ignore
    team: "Team",
    run_response: Optional[TeamRunOutput] = None,
    *,
    run_id: Optional[str] = None,
    requirements: Optional[List[Any]] = None,
    # --- Continue sugar (mirrors agent dispatch) ---
    input: Optional[str] = None,
    continue_from: Union[int, Literal["end", "last_user"]] = "end",
    fork: bool = False,
    regenerate: bool = False,
    replace_original: Optional[bool] = None,
    additional_instructions: Optional[str] = None,
    # --- Stream/control ---
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
    background: bool = False,
    **kwargs: Any,
) -> Union[TeamRunOutput, AsyncIterator[Union[TeamRunOutputEvent, RunOutputEvent, TeamRunOutput]]]:
    """Continue a paused team run (async entry point).

    Routes between _acontinue_run, _acontinue_run_stream, and
    _acontinue_run_background_stream based on the stream and background options.
    Snapshot dispatch parameters (``regenerate``, ``fork``, ``continue_from``,
    ``replace_original``, ``additional_instructions``, ``input``) flow
    through to the inner functions which apply them after loading the run.
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

    if background:
        if not team.db:
            raise ValueError(
                "Background execution requires a database to be configured on the team for run persistence."
            )
        if opts.stream:
            # background=True, stream=True: run in background task, yield SSE strings via queue
            return _acontinue_run_background_stream(  # type: ignore[return-value]
                team,
                run_response=run_response,
                run_context=run_context,
                requirements=requirements,
                input=input,
                continue_from=continue_from,
                fork=fork,
                regenerate=regenerate,
                replace_original=replace_original,
                additional_instructions=additional_instructions,
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
        # background=True, stream=False is not supported for continue_run yet —
        # fall through to the regular non-streaming path to preserve prior behavior.

    if opts.stream:
        return _acontinue_run_stream(
            team,
            run_response=run_response,
            run_context=run_context,
            requirements=requirements,
            input=input,
            continue_from=continue_from,
            fork=fork,
            regenerate=regenerate,
            replace_original=replace_original,
            additional_instructions=additional_instructions,
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
            input=input,
            continue_from=continue_from,
            fork=fork,
            regenerate=regenerate,
            replace_original=replace_original,
            additional_instructions=additional_instructions,
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
    # --- Snapshot dispatch sugar (mirrors sync continue_run_dispatch) ---
    input: Optional[str] = None,
    continue_from: Union[int, Literal["end", "last_user"]] = "end",
    fork: bool = False,
    regenerate: bool = False,
    replace_original: Optional[bool] = None,
    additional_instructions: Optional[str] = None,
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
    from agno.team._telemetry import alog_team_telemetry
    from agno.team._tools import _aget_learning_tools, _check_and_refresh_mcp_tools, _determine_tools_for_model

    log_debug(f"Team Continue Run: {run_response.run_id if run_response else run_id}", center=True)

    team_session: Optional[TeamSession] = None

    try:
        num_attempts = team.retries + 1
        for attempt in range(num_attempts):
            try:
                # Bind run_messages early — cancellation can fire before run_messages
                # is built, and the cancellation handler reads it.
                run_messages: Optional[RunMessages] = None
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
                    runs = team_session.runs or []
                    run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
                    if run_response is None:
                        raise RuntimeError(f"No runs found for run ID {run_id}")

                run_response = cast(TeamRunOutput, run_response)

                if run_response.status == RunStatus.cancelled:
                    raise ValueError(f"Cannot continue run {run_response.run_id}: run is cancelled")

                # --- Snapshot dispatch (regenerate / fork / time-travel) ---
                continue_index: Optional[int] = _resolve_continue_from_team(
                    run_response,
                    continue_from=continue_from,
                    regenerate=regenerate,
                )
                # Mirrors the sync continue_run_dispatch.
                fork, continue_index, input = _normalize_regenerate_params_team(
                    run_response,
                    regenerate=regenerate,
                    replace_original=replace_original,
                    additional_instructions=additional_instructions,
                    fork=fork,
                    continue_index=continue_index,
                    input=input,
                )
                original_run_id_for_lineage = run_response.run_id if regenerate else None

                # Auto-fork on COMPLETED — preserves 1-run-1-loop invariant.
                if not fork and run_response.status == RunStatus.completed:
                    fork = True

                _did_snapshot_dispatch = fork or _will_truncate_team_run(run_response, continue_index)
                run_response = _apply_continue_modifiers_team(run_response, fork, continue_index)
                if regenerate and original_run_id_for_lineage:
                    run_response.regenerated_from = original_run_id_for_lineage
                    if replace_original is not False and run_response.forked_from_run_id:
                        for r in team_session.runs or []:
                            if r.run_id == original_run_id_for_lineage:
                                r.status = RunStatus.regenerated
                                break

                # Append input/additional_instructions as a user message.
                if input:
                    _maybe_append_input_message_team(run_response, input, team)
                # --- End snapshot dispatch ---

                # Save old requirements before overwriting — needed for member-level approval fields
                old_requirements = run_response.requirements

                # A freshly-forked run has no PAUSED requirements contract;
                # skip the HITL machinery entirely. The fork is a fresh
                # attempt seeded from the snapshot — no tools/approvals to
                # resolve. Without this gate, the dispatch raises "requirements
                # parameter must be provided" for forked runs that have no
                # surviving requirements.
                if _did_snapshot_dispatch:
                    # Reset content so update_run_response doesn't append to
                    # stale content from the source run.
                    run_response.content = None
                # Normalize and apply requirements
                elif requirements:
                    requirements = _normalize_requirements_payload(requirements)
                    run_response.requirements = requirements
                    updated_tools = [req.tool_execution for req in requirements if req.tool_execution is not None]
                    if updated_tools and run_response.tools:
                        updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
                        run_response.tools = _merge_tools_preserving_approval(run_response.tools, updated_tools_map)
                    elif updated_tools:
                        run_response.tools = updated_tools
                    _backfill_approval_to_requirements(run_response, old_requirements=old_requirements)

                    # Also apply any resolved approval
                    if run_response.tools:
                        from agno.run.approval import acheck_and_apply_approval_resolution

                        try:
                            await acheck_and_apply_approval_resolution(
                                team.db, run_response.run_id or run_id or "", run_response
                            )
                        except RuntimeError:
                            raise ValueError(
                                "To continue a run from a given run_id, the requirements parameter must be provided "
                                "(or resolve an admin approval first)."
                            )
                elif run_response.tools:
                    from agno.run.approval import acheck_and_apply_approval_resolution

                    try:
                        await acheck_and_apply_approval_resolution(
                            team.db, run_response.run_id or run_id or "", run_response
                        )
                    except RuntimeError:
                        # Fall through to bare-resume rather than raising.
                        # Same rationale as the sync dispatch — see comment there.
                        _did_snapshot_dispatch = True
                else:
                    # Bare resume of a mid-flight run (RUNNING/ERROR/CANCELLED)
                    # — no requirements, no tools. Let the team-leader model
                    # loop run with whatever messages survived. Same as sync.
                    _did_snapshot_dispatch = True

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
                        team,
                        run_response=run_response,
                        session=team_session,
                        run_context=run_context,
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
                            team, run_response=run_response, session=team_session, run_context=run_context
                        )

                # Handle team-level tool resolution
                if has_team_level or _did_snapshot_dispatch:
                    # Includes _did_snapshot_dispatch: a freshly-forked team run has no
                    # requirements but still needs the team-leader model call
                    # to produce a response. Without this, forked runs would
                    # fall through to terminal cleanup with content=None.
                    # Guard: if team-level requirements are unresolved, re-pause instead of auto-rejecting
                    unresolved_team = [
                        r
                        for r in (run_response.requirements or [])
                        if getattr(r, "member_agent_id", None) is None and not r.is_resolved()
                    ]
                    if unresolved_team:
                        from agno.team import _hooks

                        return await _hooks.ahandle_team_run_paused(
                            team, run_response=run_response, session=team_session, run_context=run_context
                        )

                    team.model = cast(Model, team.model)
                    await _check_and_refresh_mcp_tools(team)

                    team_run_context: Dict[str, Any] = {}
                    learning_tools = await _aget_learning_tools(team, user_id, team_session)
                    _tools = _determine_tools_for_model(
                        team,
                        model=team.model,
                        run_response=run_response,
                        run_context=run_context,
                        team_run_context=team_run_context,
                        session=team_session,
                        user_id=user_id,
                        async_mode=True,
                        learning_tools=learning_tools,
                    )

                    input_messages = run_response.messages or []
                    run_messages = _get_continue_run_messages(
                        team,
                        input=input_messages,
                        session=team_session,
                        add_history_to_context=team.add_history_to_context,
                        run_context=run_context,
                    )

                    await _ahandle_team_tool_call_updates(
                        team, run_response=run_response, run_messages=run_messages, tools=_tools
                    )

                    run_response.status = RunStatus.running
                    run_response.content = None

                    # Handle model response using shared helper
                    paused_result = await _ahandle_model_response_for_continue(
                        team,
                        run_response=run_response,
                        run_messages=run_messages,
                        run_context=run_context,
                        tools=_tools,
                        team_session=team_session,
                        response_format=response_format,
                    )
                    if paused_result is not None:
                        return paused_result

                elif member_results:
                    # Member-only: continue the same run with results
                    team.model = cast(Model, team.model)
                    await _check_and_refresh_mcp_tools(team)

                    team_run_context: Dict[str, Any] = {}  # type: ignore[no-redef]
                    learning_tools = await _aget_learning_tools(team, user_id, team_session)
                    _tools = _determine_tools_for_model(
                        team,
                        model=team.model,
                        run_response=run_response,
                        run_context=run_context,
                        team_run_context=team_run_context,
                        session=team_session,
                        user_id=user_id,
                        async_mode=True,
                        learning_tools=learning_tools,
                    )

                    input_messages = run_response.messages or []
                    run_messages = _get_continue_run_messages(
                        team,
                        input=input_messages,
                        session=team_session,
                        add_history_to_context=team.add_history_to_context,
                        run_context=run_context,
                    )

                    # Prepare for member HITL continuation
                    _prepare_member_hitl_continuation(run_response, run_messages, member_results)

                    log_debug(f"Team Continue Run (Member HITL): {run_response.run_id}", center=True)

                    # Handle model response using shared helper
                    paused_result = await _ahandle_model_response_for_continue(
                        team,
                        run_response=run_response,
                        run_messages=run_messages,
                        run_context=run_context,
                        tools=_tools,
                        team_session=team_session,
                        response_format=response_format,
                    )
                    if paused_result is not None:
                        return paused_result

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
                        await team.session_summary_manager.acreate_session_summary(
                            session=team_session, run_metrics=run_response.metrics
                        )
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
                run_response = _handle_team_run_cancellation(run_response, e, run_messages, session=team_session)
                if run_response.run_id:
                    await adrain_member_tasks(run_response.run_id)
                if team_session is not None:
                    await _acleanup_and_store(team, run_response=run_response, session=team_session)
                return run_response

            except (InputCheckError, OutputCheckError) as e:
                run_response = cast(TeamRunOutput, run_response)
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
                if run_response.content is None:
                    run_response.content = str(e)
                log_error(f"Validation failed: {str(e)} | Check: {e.check_trigger}")

                if team_session is not None:
                    await _acleanup_and_store(team, run_response=run_response, session=team_session)
                return run_response

            except (KeyboardInterrupt, asyncio.CancelledError) as cancel_exc:
                if run_response is None:
                    run_response = TeamRunOutput(run_id=run_id)
                run_response = cast(TeamRunOutput, run_response)
                run_response = _handle_team_run_cancellation(
                    run_response, KeyboardInterrupt(), run_messages, session=team_session
                )
                if team_session is not None:
                    if isinstance(cancel_exc, asyncio.CancelledError):
                        # Client disconnect: persist on a detached task so the cancel scope can't abort the write
                        _persist_cancelled_team_run_in_background(
                            team, run_response=run_response, session=team_session, run_context=run_context
                        )
                    else:
                        # Ctrl-C under asyncio.run: persist inline; a detached task would not run before the loop exits
                        await _acleanup_and_store(
                            team, run_response=run_response, session=team_session, run_context=run_context
                        )
                # Re-raise on disconnect to propagate it; return the partial on Ctrl-C
                if isinstance(cancel_exc, asyncio.CancelledError):
                    raise
                return run_response

            except ValueError:
                # Validation errors (e.g. cancelled run, missing args) propagate to the caller
                raise
            except Exception as e:
                run_response = cast(TeamRunOutput, run_response)
                if attempt < num_attempts - 1:
                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries
                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    await asyncio.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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
    # --- Snapshot dispatch sugar (mirrors sync continue_run_dispatch) ---
    input: Optional[str] = None,
    continue_from: Union[int, Literal["end", "last_user"]] = "end",
    fork: bool = False,
    regenerate: bool = False,
    replace_original: Optional[bool] = None,
    additional_instructions: Optional[str] = None,
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
    from agno.team._tools import _aget_learning_tools, _check_and_refresh_mcp_tools, _determine_tools_for_model
    from agno.utils.events import create_team_run_continued_event

    log_debug(f"Team Continue Run Stream: {run_response.run_id if run_response else run_id}", center=True)

    team_session: Optional[TeamSession] = None

    try:
        num_attempts = team.retries + 1
        for attempt in range(num_attempts):
            try:
                # Bind run_messages early — cancellation can fire before run_messages
                # is built, and the cancellation handler reads it.
                run_messages: Optional[RunMessages] = None
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
                    runs = team_session.runs or []
                    run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
                    if run_response is None:
                        raise RuntimeError(f"No runs found for run ID {run_id}")

                run_response = cast(TeamRunOutput, run_response)

                if run_response.status == RunStatus.cancelled:
                    raise ValueError(f"Cannot continue run {run_response.run_id}: run is cancelled")

                # --- Snapshot dispatch (regenerate / fork / time-travel) ---
                continue_index: Optional[int] = _resolve_continue_from_team(
                    run_response,
                    continue_from=continue_from,
                    regenerate=regenerate,
                )
                # Mirrors the sync continue_run_dispatch.
                fork, continue_index, input = _normalize_regenerate_params_team(
                    run_response,
                    regenerate=regenerate,
                    replace_original=replace_original,
                    additional_instructions=additional_instructions,
                    fork=fork,
                    continue_index=continue_index,
                    input=input,
                )
                original_run_id_for_lineage = run_response.run_id if regenerate else None

                # Auto-fork on COMPLETED — preserves 1-run-1-loop invariant.
                if not fork and run_response.status == RunStatus.completed:
                    fork = True

                _did_snapshot_dispatch = fork or _will_truncate_team_run(run_response, continue_index)
                run_response = _apply_continue_modifiers_team(run_response, fork, continue_index)
                if regenerate and original_run_id_for_lineage:
                    run_response.regenerated_from = original_run_id_for_lineage
                    if replace_original is not False and run_response.forked_from_run_id:
                        for r in team_session.runs or []:
                            if r.run_id == original_run_id_for_lineage:
                                r.status = RunStatus.regenerated
                                break

                # Append input/additional_instructions as a user message.
                if input:
                    _maybe_append_input_message_team(run_response, input, team)
                # --- End snapshot dispatch ---

                # Save old requirements before overwriting — needed for member-level approval fields
                old_requirements = run_response.requirements

                # A freshly-forked run has no PAUSED requirements contract;
                # skip the HITL machinery entirely. The fork is a fresh
                # attempt seeded from the snapshot — no tools/approvals to
                # resolve. Without this gate, the dispatch raises "requirements
                # parameter must be provided" for forked runs that have no
                # surviving requirements.
                if _did_snapshot_dispatch:
                    # Reset content so update_run_response doesn't append to
                    # stale content from the source run.
                    run_response.content = None
                # Normalize and apply requirements
                elif requirements:
                    requirements = _normalize_requirements_payload(requirements)
                    run_response.requirements = requirements
                    updated_tools = [req.tool_execution for req in requirements if req.tool_execution is not None]
                    if updated_tools and run_response.tools:
                        updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
                        run_response.tools = _merge_tools_preserving_approval(run_response.tools, updated_tools_map)
                    elif updated_tools:
                        run_response.tools = updated_tools
                    _backfill_approval_to_requirements(run_response, old_requirements=old_requirements)

                    # Also apply any resolved approval
                    if run_response.tools:
                        from agno.run.approval import acheck_and_apply_approval_resolution

                        try:
                            await acheck_and_apply_approval_resolution(
                                team.db, run_response.run_id or run_id or "", run_response
                            )
                        except RuntimeError:
                            raise ValueError(
                                "To continue a run from a given run_id, the requirements parameter must be provided "
                                "(or resolve an admin approval first)."
                            )
                elif run_response.tools:
                    from agno.run.approval import acheck_and_apply_approval_resolution

                    try:
                        await acheck_and_apply_approval_resolution(
                            team.db, run_response.run_id or run_id or "", run_response
                        )
                    except RuntimeError:
                        # Fall through to bare-resume rather than raising.
                        # Same rationale as the sync dispatch — see comment there.
                        _did_snapshot_dispatch = True
                else:
                    # Bare resume of a mid-flight run (RUNNING/ERROR/CANCELLED)
                    # — no requirements, no tools. Let the team-leader model
                    # loop run with whatever messages survived. Same as sync.
                    _did_snapshot_dispatch = True

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
                    # Streaming: use the async generator variant that yields member events
                    async for event in _aroute_requirements_to_members_stream(
                        team,
                        run_response=run_response,
                        session=team_session,
                        member_results=member_results,
                        run_context=run_context,
                        stream_events=stream_events,
                    ):
                        yield event
                    # Merge: keep team-level reqs + any newly propagated member reqs (chained HITL)
                    newly_propagated = [
                        r for r in (run_response.requirements or []) if id(r) not in original_member_req_ids
                    ]
                    run_response.requirements = team_level_reqs + newly_propagated

                    if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                        from agno.team import _hooks

                        async for item in _hooks.ahandle_team_run_paused_stream(
                            team, run_response=run_response, session=team_session, run_context=run_context
                        ):
                            yield item
                        if yield_run_output:
                            yield run_response
                        return

                if has_team_level or _did_snapshot_dispatch:
                    # Includes _did_snapshot_dispatch: a freshly-forked team run has no
                    # requirements but still needs the team-leader model call
                    # to produce a response. Without this, forked runs would
                    # fall through to terminal cleanup with content=None.
                    # Guard: if team-level requirements are unresolved, re-pause instead of auto-rejecting
                    unresolved_team = [
                        r
                        for r in (run_response.requirements or [])
                        if getattr(r, "member_agent_id", None) is None and not r.is_resolved()
                    ]
                    if unresolved_team:
                        from agno.team import _hooks

                        async for item in _hooks.ahandle_team_run_paused_stream(
                            team, run_response=run_response, session=team_session, run_context=run_context
                        ):
                            yield item
                        if yield_run_output:
                            yield run_response
                        return

                    team.model = cast(Model, team.model)
                    await _check_and_refresh_mcp_tools(team)

                    team_run_context: Dict[str, Any] = {}
                    learning_tools = await _aget_learning_tools(team, user_id, team_session)
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
                        learning_tools=learning_tools,
                    )

                    input_messages = run_response.messages or []
                    run_messages = _get_continue_run_messages(
                        team,
                        input=input_messages,
                        session=team_session,
                        add_history_to_context=team.add_history_to_context,
                        run_context=run_context,
                    )

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
                            if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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
                            if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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
                            team, run_response=run_response, session=team_session, run_context=run_context
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
                    # Member-only: continue the same run with member results
                    team.model = cast(Model, team.model)
                    await _check_and_refresh_mcp_tools(team)

                    team_run_context: Dict[str, Any] = {}  # type: ignore[no-redef]
                    learning_tools = await _aget_learning_tools(team, user_id, team_session)
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
                        learning_tools=learning_tools,
                    )

                    input_messages = run_response.messages or []
                    run_messages = _get_continue_run_messages(
                        team,
                        input=input_messages,
                        session=team_session,
                        add_history_to_context=team.add_history_to_context,
                        run_context=run_context,
                    )

                    # Prepare for member HITL continuation
                    _prepare_member_hitl_continuation(run_response, run_messages, member_results)

                    log_debug(f"Team Continue Run Stream (Member HITL): {run_response.run_id}", center=True)

                    # Yield RunContinued event
                    if stream_events:
                        yield handle_event(
                            create_team_run_continued_event(run_response),
                            run_response,
                            events_to_skip=team.events_to_skip,
                            store_events=team.store_events,
                        )

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
                            if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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
                            if not isinstance(event, _MEMBER_CANCEL_BYPASS_EVENT_TYPES):
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

                    # Check for new pauses
                    if run_response.requirements and any(not req.is_resolved() for req in run_response.requirements):
                        from agno.team import _hooks

                        async for item in _hooks.ahandle_team_run_paused_stream(
                            team, run_response=run_response, session=team_session, run_context=run_context
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
                        await team.session_summary_manager.acreate_session_summary(
                            session=team_session, run_metrics=run_response.metrics
                        )
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
                run_response = _handle_team_run_cancellation(run_response, e, run_messages, session=team_session)
                cancelled_event, completed_event = _build_team_cancel_terminal_events(
                    team,
                    run_response,
                    error=e,
                    run_context=run_context,
                )
                if run_response.run_id:
                    await adrain_member_tasks(run_response.run_id)
                try:
                    if team_session is not None:
                        await _acleanup_and_store(team, run_response=run_response, session=team_session)
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break

            except (InputCheckError, OutputCheckError) as e:
                run_response = cast(TeamRunOutput, run_response)
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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

            except (KeyboardInterrupt, asyncio.CancelledError, GeneratorExit) as cancel_exc:
                if run_response is None:
                    run_response = TeamRunOutput(run_id=run_id)
                run_response = cast(TeamRunOutput, run_response)
                run_response = _handle_team_run_cancellation(
                    run_response, KeyboardInterrupt(), run_messages, session=team_session
                )
                # Build terminal events first so they are stored on the run
                cancelled_event, completed_event = _build_team_cancel_terminal_events(
                    team,
                    run_response,
                    error=KeyboardInterrupt(),
                    run_context=run_context,
                )
                if team_session is not None:
                    if isinstance(cancel_exc, (asyncio.CancelledError, GeneratorExit)):
                        # Client disconnect: persist on a detached task so the cancel scope can't abort the write.
                        # GeneratorExit is raised when the SSE StreamingResponse closes the generator on disconnect.
                        _persist_cancelled_team_run_in_background(
                            team, run_response=run_response, session=team_session, run_context=run_context
                        )
                    else:
                        # Ctrl-C under asyncio.run: persist inline; a detached task would not run before the loop exits
                        await _acleanup_and_store(
                            team, run_response=run_response, session=team_session, run_context=run_context
                        )
                # Re-raise on disconnect (client gone); yield the terminal events on Ctrl-C
                if isinstance(cancel_exc, (asyncio.CancelledError, GeneratorExit)):
                    raise
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break

            except ValueError:
                # Validation errors (e.g. cancelled run, missing args) propagate to the caller
                raise
            except Exception as e:
                if run_response is None:
                    run_response = TeamRunOutput(run_id=run_id)
                run_response = cast(TeamRunOutput, run_response)
                if attempt < num_attempts - 1:
                    if team.exponential_backoff:
                        delay = team.delay_between_retries * (2**attempt)
                    else:
                        delay = team.delay_between_retries
                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    await asyncio.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error_team(run_response, locals().get("run_messages"))
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
