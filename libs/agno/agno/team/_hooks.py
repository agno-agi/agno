"""Hook execution and stream-response update helpers for Team."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Type,
    Union,
    cast,
    get_args,
)
from uuid import uuid4

from pydantic import BaseModel

from agno.exceptions import (
    InputCheckError,
    OutputCheckError,
)
from agno.media import Audio
from agno.models.base import Model
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.reasoning.step import ReasoningStep, ReasoningSteps
from agno.run import RunContext, RunStatus
from agno.run.agent import RunOutput, RunOutputEvent
from agno.run.messages import RunMessages
from agno.run.team import (
    TeamRunEvent,
    TeamRunInput,
    TeamRunOutput,
    TeamRunOutputEvent,
)
from agno.session import TeamSession
from agno.tools.function import Function
from agno.utils.events import (
    create_team_compression_completed_event,
    create_team_compression_started_event,
    create_team_model_request_completed_event,
    create_team_model_request_started_event,
    create_team_post_hook_completed_event,
    create_team_post_hook_started_event,
    create_team_pre_hook_completed_event,
    create_team_pre_hook_started_event,
    create_team_reasoning_completed_event,
    create_team_reasoning_started_event,
    create_team_reasoning_step_event,
    create_team_run_output_content_event,
    create_team_run_paused_event,
    create_team_tool_call_completed_event,
    create_team_tool_call_error_event,
    create_team_tool_call_started_event,
    handle_event,
)
from agno.utils.hooks import (
    copy_args_for_background,
    filter_hook_args,
    should_run_hook_in_background,
)
from agno.utils.log import (
    log_debug,
    log_error,
    log_exception,
    log_warning,
)
from agno.utils.merge_dict import merge_dictionaries
from agno.utils.reasoning import (
    add_reasoning_metrics_to_metadata,
)
from agno.utils.string import parse_response_dict_str, parse_response_model_str

if TYPE_CHECKING:
    from agno.team.team import Team


# ---------------------------------------------------------------------------
# HITL pause handlers
# ---------------------------------------------------------------------------


def _get_team_paused_content(run_response: TeamRunOutput) -> str:
    """Generate human-readable content for a paused team run."""
    if not run_response.requirements:
        return "Team run paused."
    active = [req for req in run_response.requirements if not req.is_resolved()]
    if not active:
        return "Team run paused."
    parts: list[str] = []
    for req in active:
        member = req.member_agent_name or "unknown member"
        tool_name = req.tool_execution.tool_name if req.tool_execution else "unknown"
        if req.needs_confirmation:
            parts.append(f"- {member}: {tool_name} requires confirmation")
        elif req.needs_user_input:
            parts.append(f"- {member}: {tool_name} requires user input")
        elif req.needs_external_execution:
            parts.append(f"- {member}: {tool_name} requires external execution")
    return "Team run paused. The following members require input:\n" + "\n".join(parts)


def handle_team_run_paused(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    user_id: Optional[str] = None,
) -> TeamRunOutput:
    from agno.team import _api

    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = _get_team_paused_content(run_response)

    _api._cleanup_and_store(team, run_response=run_response, session=session)

    log_debug(f"Team Run Paused: {run_response.run_id}", center=True, symbol="*")
    return run_response


def handle_team_run_paused_stream(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    user_id: Optional[str] = None,
) -> Iterator[Union[TeamRunOutputEvent, RunOutputEvent]]:
    from agno.team import _api

    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = _get_team_paused_content(run_response)

    pause_event = handle_event(
        create_team_run_paused_event(
            from_run_response=run_response,
            tools=run_response.tools,
            requirements=run_response.requirements,
        ),
        run_response,
        events_to_skip=team.events_to_skip,  # type: ignore
        store_events=team.store_events,
    )

    _api._cleanup_and_store(team, run_response=run_response, session=session)

    yield pause_event  # type: ignore

    log_debug(f"Team Run Paused: {run_response.run_id}", center=True, symbol="*")


async def ahandle_team_run_paused(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    user_id: Optional[str] = None,
) -> TeamRunOutput:
    from agno.team import _api

    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = _get_team_paused_content(run_response)

    await _api._acleanup_and_store(team, run_response=run_response, session=session)

    log_debug(f"Team Run Paused: {run_response.run_id}", center=True, symbol="*")
    return run_response


async def ahandle_team_run_paused_stream(
    team: "Team",
    run_response: TeamRunOutput,
    session: TeamSession,
    user_id: Optional[str] = None,
) -> AsyncIterator[Union[TeamRunOutputEvent, RunOutputEvent]]:
    from agno.team import _api

    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = _get_team_paused_content(run_response)

    pause_event = handle_event(
        create_team_run_paused_event(
            from_run_response=run_response,
            tools=run_response.tools,
            requirements=run_response.requirements,
        ),
        run_response,
        events_to_skip=team.events_to_skip,  # type: ignore
        store_events=team.store_events,
    )

    await _api._acleanup_and_store(team, run_response=run_response, session=session)

    yield pause_event  # type: ignore

    log_debug(f"Team Run Paused: {run_response.run_id}", center=True, symbol="*")


def _execute_pre_hooks(
    team: "Team",
    hooks: Optional[List[Callable[..., Any]]],
    run_response: TeamRunOutput,
    run_input: TeamRunInput,
    session: TeamSession,
    run_context: RunContext,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    stream_events: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> Iterator[TeamRunOutputEvent]:
    """Execute multiple pre-hook functions in succession."""
    if hooks is None:
        return

    # Prepare arguments for hooks
    effective_debug_mode = debug_mode if debug_mode is not None else team.debug_mode
    all_args = {
        "run_input": run_input,
        "run_context": run_context,
        "team": team,
        "session": session,
        "user_id": user_id,
        "debug_mode": effective_debug_mode,
    }

    # Check if background_tasks is available and ALL hooks should run in background
    # Note: Pre-hooks running in background may not be able to modify run_input
    if team._run_hooks_in_background is True and background_tasks is not None:
        # Schedule ALL pre_hooks as background tasks
        # Copy args to prevent race conditions
        bg_args = copy_args_for_background(all_args)
        for hook in hooks:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, bg_args)

            # Add to background tasks
            background_tasks.add_task(hook, **filtered_args)
        return

    all_args.update(kwargs)

    for i, hook in enumerate(hooks):
        # Check if this specific hook should run in background (via @hook decorator)
        if should_run_hook_in_background(hook) and background_tasks is not None:
            # Copy args to prevent race conditions
            bg_args = copy_args_for_background(all_args)
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
            continue

        if stream_events:
            yield handle_event(  # type: ignore
                run_response=run_response,
                event=create_team_pre_hook_started_event(
                    from_run_response=run_response, run_input=run_input, pre_hook_name=hook.__name__
                ),
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )
        try:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, all_args)

            hook(**filtered_args)

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_response,
                    event=create_team_pre_hook_completed_event(
                        from_run_response=run_response, run_input=run_input, pre_hook_name=hook.__name__
                    ),
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

        except (InputCheckError, OutputCheckError) as e:
            raise e
        except Exception as e:
            log_error(f"Pre-hook #{i + 1} execution failed: {str(e)}")
            log_exception(e)
        finally:
            # Reset global log mode incase an agent in the pre-hook changed it
            team._set_debug(debug_mode=debug_mode)

    # Update the input on the run_response
    run_response.input = run_input


async def _aexecute_pre_hooks(
    team: "Team",
    hooks: Optional[List[Callable[..., Any]]],
    run_response: TeamRunOutput,
    run_input: TeamRunInput,
    session: TeamSession,
    run_context: RunContext,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    stream_events: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> AsyncIterator[TeamRunOutputEvent]:
    """Execute multiple pre-hook functions in succession (async version)."""
    if hooks is None:
        return

    # Prepare arguments for hooks
    effective_debug_mode = debug_mode if debug_mode is not None else team.debug_mode
    all_args = {
        "run_input": run_input,
        "run_context": run_context,
        "team": team,
        "session": session,
        "user_id": user_id,
        "debug_mode": effective_debug_mode,
    }

    # Check if background_tasks is available and ALL hooks should run in background
    # Note: Pre-hooks running in background may not be able to modify run_input
    if team._run_hooks_in_background is True and background_tasks is not None:
        # Schedule ALL pre_hooks as background tasks
        # Copy args to prevent race conditions
        bg_args = copy_args_for_background(all_args)
        for hook in hooks:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, bg_args)

            # Add to background tasks (both sync and async hooks supported)
            background_tasks.add_task(hook, **filtered_args)
        return

    all_args.update(kwargs)

    for i, hook in enumerate(hooks):
        # Check if this specific hook should run in background (via @hook decorator)
        if should_run_hook_in_background(hook) and background_tasks is not None:
            # Copy args to prevent race conditions
            bg_args = copy_args_for_background(all_args)
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
            continue

        if stream_events:
            yield handle_event(  # type: ignore
                run_response=run_response,
                event=create_team_pre_hook_started_event(
                    from_run_response=run_response, run_input=run_input, pre_hook_name=hook.__name__
                ),
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )
        try:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, all_args)

            from inspect import iscoroutinefunction

            if iscoroutinefunction(hook):
                await hook(**filtered_args)
            else:
                # Synchronous function
                hook(**filtered_args)

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_response,
                    event=create_team_pre_hook_completed_event(
                        from_run_response=run_response, run_input=run_input, pre_hook_name=hook.__name__
                    ),
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

        except (InputCheckError, OutputCheckError) as e:
            raise e
        except Exception as e:
            log_error(f"Pre-hook #{i + 1} execution failed: {str(e)}")
            log_exception(e)
        finally:
            # Reset global log mode incase an agent in the pre-hook changed it
            team._set_debug(debug_mode=debug_mode)

    # Update the input on the run_response
    run_response.input = run_input


def _execute_post_hooks(
    team: "Team",
    hooks: Optional[List[Callable[..., Any]]],
    run_output: TeamRunOutput,
    session: TeamSession,
    run_context: RunContext,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    stream_events: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> Iterator[TeamRunOutputEvent]:
    """Execute multiple post-hook functions in succession."""
    if hooks is None:
        return

    # Prepare arguments for hooks
    effective_debug_mode = debug_mode if debug_mode is not None else team.debug_mode
    all_args = {
        "run_output": run_output,
        "run_context": run_context,
        "team": team,
        "session": session,
        "user_id": user_id,
        "debug_mode": effective_debug_mode,
    }

    # Check if background_tasks is available and ALL hooks should run in background
    if team._run_hooks_in_background is True and background_tasks is not None:
        # Schedule ALL post_hooks as background tasks
        # Copy args to prevent race conditions
        bg_args = copy_args_for_background(all_args)
        for hook in hooks:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, bg_args)

            # Add to background tasks
            background_tasks.add_task(hook, **filtered_args)
        return

    all_args.update(kwargs)

    for i, hook in enumerate(hooks):
        # Check if this specific hook should run in background (via @hook decorator)
        if should_run_hook_in_background(hook) and background_tasks is not None:
            # Copy args to prevent race conditions
            bg_args = copy_args_for_background(all_args)
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
            continue

        if stream_events:
            yield handle_event(  # type: ignore
                run_response=run_output,
                event=create_team_post_hook_started_event(  # type: ignore
                    from_run_response=run_output,
                    post_hook_name=hook.__name__,
                ),
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )
        try:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, all_args)

            hook(**filtered_args)

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_output,
                    event=create_team_post_hook_completed_event(  # type: ignore
                        from_run_response=run_output,
                        post_hook_name=hook.__name__,
                    ),
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )

        except (InputCheckError, OutputCheckError) as e:
            raise e
        except Exception as e:
            log_error(f"Post-hook #{i + 1} execution failed: {str(e)}")
            log_exception(e)
        finally:
            # Reset global log mode incase an agent in the post-hook changed it
            team._set_debug(debug_mode=debug_mode)


async def _aexecute_post_hooks(
    team: "Team",
    hooks: Optional[List[Callable[..., Any]]],
    run_output: TeamRunOutput,
    session: TeamSession,
    run_context: RunContext,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
    stream_events: bool = False,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> AsyncIterator[TeamRunOutputEvent]:
    """Execute multiple post-hook functions in succession (async version)."""
    if hooks is None:
        return

    # Prepare arguments for hooks
    effective_debug_mode = debug_mode if debug_mode is not None else team.debug_mode
    all_args = {
        "run_output": run_output,
        "run_context": run_context,
        "team": team,
        "session": session,
        "user_id": user_id,
        "debug_mode": effective_debug_mode,
    }

    # Check if background_tasks is available and ALL hooks should run in background
    if team._run_hooks_in_background is True and background_tasks is not None:
        # Schedule ALL post_hooks as background tasks
        # Copy args to prevent race conditions
        bg_args = copy_args_for_background(all_args)
        for hook in hooks:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, bg_args)

            # Add to background tasks (both sync and async hooks supported)
            background_tasks.add_task(hook, **filtered_args)
        return

    all_args.update(kwargs)

    for i, hook in enumerate(hooks):
        # Check if this specific hook should run in background (via @hook decorator)
        if should_run_hook_in_background(hook) and background_tasks is not None:
            # Copy args to prevent race conditions
            bg_args = copy_args_for_background(all_args)
            filtered_args = filter_hook_args(hook, bg_args)
            background_tasks.add_task(hook, **filtered_args)
            continue

        if stream_events:
            yield handle_event(  # type: ignore
                run_response=run_output,
                event=create_team_post_hook_started_event(  # type: ignore
                    from_run_response=run_output,
                    post_hook_name=hook.__name__,
                ),
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )
        try:
            # Filter arguments to only include those that the hook accepts
            filtered_args = filter_hook_args(hook, all_args)

            from inspect import iscoroutinefunction

            if iscoroutinefunction(hook):
                await hook(**filtered_args)
            else:
                hook(**filtered_args)

            if stream_events:
                yield handle_event(  # type: ignore
                    run_response=run_output,
                    event=create_team_post_hook_completed_event(  # type: ignore
                        from_run_response=run_output,
                        post_hook_name=hook.__name__,
                    ),
                    events_to_skip=team.events_to_skip,
                    store_events=team.store_events,
                )
        except (InputCheckError, OutputCheckError) as e:
            raise e
        except Exception as e:
            log_error(f"Post-hook #{i + 1} execution failed: {str(e)}")
            log_exception(e)
        finally:
            # Reset global log mode incase an agent in the post-hook changed it
            team._set_debug(debug_mode=debug_mode)


def _update_run_response(
    team: "Team",
    model_response: ModelResponse,
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
):
    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    # Handle structured outputs
    if (output_schema is not None) and not team.use_json_mode and (model_response.parsed is not None):
        # Update the run_response content with the structured output
        run_response.content = model_response.parsed
        # Update the run_response content_type with the structured output class name
        run_response.content_type = "dict" if isinstance(output_schema, dict) else output_schema.__name__
    else:
        # Update the run_response content with the model response content
        if not run_response.content:
            run_response.content = model_response.content
        else:
            run_response.content += model_response.content

    # Update the run_response thinking with the model response thinking
    if model_response.reasoning_content is not None:
        if not run_response.reasoning_content:
            run_response.reasoning_content = model_response.reasoning_content
        else:
            run_response.reasoning_content += model_response.reasoning_content
    # Update provider data
    if model_response.provider_data is not None:
        run_response.model_provider_data = model_response.provider_data
    # Update citations
    if model_response.citations is not None:
        run_response.citations = model_response.citations

    # Update the run_response tools with the model response tool_executions
    if model_response.tool_executions is not None:
        if run_response.tools is None:
            run_response.tools = model_response.tool_executions
        else:
            run_response.tools.extend(model_response.tool_executions)

    # Update the run_response audio with the model response audio
    if model_response.audio is not None:
        run_response.response_audio = model_response.audio

    # Update session_state with changes from model response
    if model_response.updated_session_state is not None and run_response.session_state is not None:
        merge_dictionaries(run_response.session_state, model_response.updated_session_state)

    # Build a list of messages that should be added to the RunOutput
    messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]

    # Update the TeamRunOutput messages
    run_response.messages = messages_for_run_response

    # Update the TeamRunOutput metrics
    run_response.metrics = team._calculate_metrics(messages_for_run_response, current_run_metrics=run_response.metrics)

    if model_response.tool_executions:
        for tool_call in model_response.tool_executions:
            tool_name = tool_call.tool_name
            if tool_name and tool_name.lower() in ["think", "analyze"]:
                tool_args = tool_call.tool_args or {}
                team._update_reasoning_content_from_tool_call(run_response, tool_name, tool_args)


def _handle_model_response_stream(
    team: "Team",
    session: TeamSession,
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    tools: Optional[List[Union[Function, dict]]] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    stream_events: bool = False,
    session_state: Optional[Dict[str, Any]] = None,
    run_context: Optional[RunContext] = None,
) -> Iterator[Union[TeamRunOutputEvent, RunOutputEvent]]:
    team.model = cast(Model, team.model)

    reasoning_state = {
        "reasoning_started": False,
        "reasoning_time_taken": 0.0,
    }

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None
    should_parse_structured_output = output_schema is not None and team.parse_response and team.parser_model is None

    stream_model_response = True
    if should_parse_structured_output:
        log_debug("Response model set, model response is not streamed.")
        stream_model_response = False

    full_model_response = ModelResponse()
    for model_response_event in team.model.response_stream(
        messages=run_messages.messages,
        response_format=response_format,
        tools=tools,
        tool_choice=team.tool_choice,
        tool_call_limit=team.tool_call_limit,
        stream_model_response=stream_model_response,
        run_response=run_response,
        send_media_to_model=team.send_media_to_model,
        compression_manager=team.compression_manager if team.compress_tool_results else None,
    ):
        # Handle LLM request events and compression events from ModelResponse
        if isinstance(model_response_event, ModelResponse):
            if model_response_event.event == ModelResponseEvent.model_request_started.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_team_model_request_started_event(
                            from_run_response=run_response,
                            model=team.model.id,
                            model_provider=team.model.provider,
                        ),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )
                continue

            if model_response_event.event == ModelResponseEvent.model_request_completed.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_team_model_request_completed_event(
                            from_run_response=run_response,
                            model=team.model.id,
                            model_provider=team.model.provider,
                            input_tokens=model_response_event.input_tokens,
                            output_tokens=model_response_event.output_tokens,
                            total_tokens=model_response_event.total_tokens,
                            time_to_first_token=model_response_event.time_to_first_token,
                            reasoning_tokens=model_response_event.reasoning_tokens,
                            cache_read_tokens=model_response_event.cache_read_tokens,
                            cache_write_tokens=model_response_event.cache_write_tokens,
                        ),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )
                continue

            # Handle compression events
            if model_response_event.event == ModelResponseEvent.compression_started.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_team_compression_started_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )
                continue

            if model_response_event.event == ModelResponseEvent.compression_completed.value:
                if stream_events:
                    stats = model_response_event.compression_stats or {}
                    yield handle_event(  # type: ignore
                        create_team_compression_completed_event(
                            from_run_response=run_response,
                            tool_results_compressed=stats.get("tool_results_compressed"),
                            original_size=stats.get("original_size"),
                            compressed_size=stats.get("compressed_size"),
                        ),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )
                continue

        yield from team._handle_model_response_chunk(
            session=session,
            run_response=run_response,
            full_model_response=full_model_response,
            model_response_event=model_response_event,
            reasoning_state=reasoning_state,
            stream_events=stream_events,
            parse_structured_output=should_parse_structured_output,
            session_state=session_state,
            run_context=run_context,
        )

    # 3. Update TeamRunOutput
    if full_model_response.content is not None:
        run_response.content = full_model_response.content
    if full_model_response.reasoning_content is not None:
        run_response.reasoning_content = full_model_response.reasoning_content
    if full_model_response.audio is not None:
        run_response.response_audio = full_model_response.audio
    if full_model_response.citations is not None:
        run_response.citations = full_model_response.citations
    if full_model_response.provider_data is not None:
        run_response.model_provider_data = full_model_response.provider_data

    # Build a list of messages that should be added to the RunOutput
    messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
    # Update the TeamRunOutput messages
    run_response.messages = messages_for_run_response
    # Update the TeamRunOutput metrics
    run_response.metrics = team._calculate_metrics(messages_for_run_response, current_run_metrics=run_response.metrics)

    if stream_events and reasoning_state["reasoning_started"]:
        all_reasoning_steps: List[ReasoningStep] = []
        if run_response.reasoning_steps:
            all_reasoning_steps = cast(List[ReasoningStep], run_response.reasoning_steps)

        if all_reasoning_steps:
            add_reasoning_metrics_to_metadata(run_response, reasoning_state["reasoning_time_taken"])
            yield handle_event(  # type: ignore
                create_team_reasoning_completed_event(
                    from_run_response=run_response,
                    content=ReasoningSteps(reasoning_steps=all_reasoning_steps),
                    content_type=ReasoningSteps.__name__,
                ),
                run_response,
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )


async def _ahandle_model_response_stream(
    team: "Team",
    session: TeamSession,
    run_response: TeamRunOutput,
    run_messages: RunMessages,
    tools: Optional[List[Union[Function, dict]]] = None,
    response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    stream_events: bool = False,
    session_state: Optional[Dict[str, Any]] = None,
    run_context: Optional[RunContext] = None,
) -> AsyncIterator[Union[TeamRunOutputEvent, RunOutputEvent]]:
    team.model = cast(Model, team.model)

    reasoning_state = {
        "reasoning_started": False,
        "reasoning_time_taken": 0.0,
    }

    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None
    should_parse_structured_output = output_schema is not None and team.parse_response and team.parser_model is None

    stream_model_response = True
    if should_parse_structured_output:
        log_debug("Response model set, model response is not streamed.")
        stream_model_response = False

    full_model_response = ModelResponse()
    model_stream = team.model.aresponse_stream(
        messages=run_messages.messages,
        response_format=response_format,
        tools=tools,
        tool_choice=team.tool_choice,
        tool_call_limit=team.tool_call_limit,
        stream_model_response=stream_model_response,
        send_media_to_model=team.send_media_to_model,
        run_response=run_response,
        compression_manager=team.compression_manager if team.compress_tool_results else None,
    )  # type: ignore
    async for model_response_event in model_stream:
        # Handle LLM request events and compression events from ModelResponse
        if isinstance(model_response_event, ModelResponse):
            if model_response_event.event == ModelResponseEvent.model_request_started.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_team_model_request_started_event(
                            from_run_response=run_response,
                            model=team.model.id,
                            model_provider=team.model.provider,
                        ),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )
                continue

            if model_response_event.event == ModelResponseEvent.model_request_completed.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_team_model_request_completed_event(
                            from_run_response=run_response,
                            model=team.model.id,
                            model_provider=team.model.provider,
                            input_tokens=model_response_event.input_tokens,
                            output_tokens=model_response_event.output_tokens,
                            total_tokens=model_response_event.total_tokens,
                            time_to_first_token=model_response_event.time_to_first_token,
                            reasoning_tokens=model_response_event.reasoning_tokens,
                            cache_read_tokens=model_response_event.cache_read_tokens,
                            cache_write_tokens=model_response_event.cache_write_tokens,
                        ),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )
                continue

            # Handle compression events
            if model_response_event.event == ModelResponseEvent.compression_started.value:
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_team_compression_started_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )
                continue

            if model_response_event.event == ModelResponseEvent.compression_completed.value:
                if stream_events:
                    stats = model_response_event.compression_stats or {}
                    yield handle_event(  # type: ignore
                        create_team_compression_completed_event(
                            from_run_response=run_response,
                            tool_results_compressed=stats.get("tool_results_compressed"),
                            original_size=stats.get("original_size"),
                            compressed_size=stats.get("compressed_size"),
                        ),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )
                continue

        for event in team._handle_model_response_chunk(
            session=session,
            run_response=run_response,
            full_model_response=full_model_response,
            model_response_event=model_response_event,
            reasoning_state=reasoning_state,
            stream_events=stream_events,
            parse_structured_output=should_parse_structured_output,
            session_state=session_state,
            run_context=run_context,
        ):
            yield event

    # Update TeamRunOutput
    if full_model_response.content is not None:
        run_response.content = full_model_response.content
    if full_model_response.reasoning_content is not None:
        run_response.reasoning_content = full_model_response.reasoning_content
    if full_model_response.audio is not None:
        run_response.response_audio = full_model_response.audio
    if full_model_response.citations is not None:
        run_response.citations = full_model_response.citations
    if full_model_response.provider_data is not None:
        run_response.model_provider_data = full_model_response.provider_data

    # Build a list of messages that should be added to the RunOutput
    messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
    # Update the TeamRunOutput messages
    run_response.messages = messages_for_run_response
    # Update the TeamRunOutput metrics
    run_response.metrics = team._calculate_metrics(messages_for_run_response, current_run_metrics=run_response.metrics)

    if stream_events and reasoning_state["reasoning_started"]:
        all_reasoning_steps: List[ReasoningStep] = []
        if run_response.reasoning_steps:
            all_reasoning_steps = cast(List[ReasoningStep], run_response.reasoning_steps)

        if all_reasoning_steps:
            add_reasoning_metrics_to_metadata(run_response, reasoning_state["reasoning_time_taken"])
            yield handle_event(  # type: ignore
                create_team_reasoning_completed_event(
                    from_run_response=run_response,
                    content=ReasoningSteps(reasoning_steps=all_reasoning_steps),
                    content_type=ReasoningSteps.__name__,
                ),
                run_response,
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )


def _handle_model_response_chunk(
    team: "Team",
    session: TeamSession,
    run_response: TeamRunOutput,
    full_model_response: ModelResponse,
    model_response_event: Union[ModelResponse, TeamRunOutputEvent, RunOutputEvent],
    reasoning_state: Optional[Dict[str, Any]] = None,
    stream_events: bool = False,
    parse_structured_output: bool = False,
    session_state: Optional[Dict[str, Any]] = None,
    run_context: Optional[RunContext] = None,
) -> Iterator[Union[TeamRunOutputEvent, RunOutputEvent]]:
    if isinstance(model_response_event, tuple(get_args(RunOutputEvent))) or isinstance(
        model_response_event, tuple(get_args(TeamRunOutputEvent))
    ):
        if team.stream_member_events:
            if model_response_event.event == TeamRunEvent.custom_event:  # type: ignore
                if hasattr(model_response_event, "team_id"):
                    model_response_event.team_id = team.id
                if hasattr(model_response_event, "team_name"):
                    model_response_event.team_name = team.name
                if not model_response_event.session_id:  # type: ignore
                    model_response_event.session_id = session.session_id  # type: ignore
                if not model_response_event.run_id:  # type: ignore
                    model_response_event.run_id = run_response.run_id  # type: ignore

            # We just bubble the event up
            yield handle_event(  # type: ignore
                model_response_event,  # type: ignore
                run_response,
                events_to_skip=team.events_to_skip,
                store_events=team.store_events,
            )  # type: ignore
        else:
            # Don't yield anything
            return
    else:
        model_response_event = cast(ModelResponse, model_response_event)
        # If the model response is an assistant_response, yield a RunOutput
        if model_response_event.event == ModelResponseEvent.assistant_response.value:
            content_type = "str"

            should_yield = False
            # Process content
            if model_response_event.content is not None:
                if parse_structured_output:
                    full_model_response.content = model_response_event.content
                    team._convert_response_to_structured_format(full_model_response, run_context=run_context)
                    # Get output_schema from run_context
                    output_schema = run_context.output_schema if run_context else None
                    content_type = "dict" if isinstance(output_schema, dict) else output_schema.__name__  # type: ignore
                    run_response.content_type = content_type
                elif team._member_response_model is not None:
                    full_model_response.content = model_response_event.content
                    team._convert_response_to_structured_format(full_model_response, run_context=run_context)
                    content_type = (
                        "dict"
                        if isinstance(team._member_response_model, dict)
                        else team._member_response_model.__name__
                    )  # type: ignore
                    run_response.content_type = content_type
                elif isinstance(model_response_event.content, str):
                    full_model_response.content = (full_model_response.content or "") + model_response_event.content
                should_yield = True

            # Process reasoning content
            if model_response_event.reasoning_content is not None:
                full_model_response.reasoning_content = (
                    full_model_response.reasoning_content or ""
                ) + model_response_event.reasoning_content
                run_response.reasoning_content = full_model_response.reasoning_content
                should_yield = True

            if model_response_event.redacted_reasoning_content is not None:
                if not full_model_response.reasoning_content:
                    full_model_response.reasoning_content = model_response_event.redacted_reasoning_content
                else:
                    full_model_response.reasoning_content += model_response_event.redacted_reasoning_content
                run_response.reasoning_content = full_model_response.reasoning_content
                should_yield = True

            # Handle provider data (one chunk)
            if model_response_event.provider_data is not None:
                run_response.model_provider_data = model_response_event.provider_data

            # Handle citations (one chunk)
            if model_response_event.citations is not None:
                run_response.citations = model_response_event.citations

            # Process audio
            if model_response_event.audio is not None:
                if full_model_response.audio is None:
                    full_model_response.audio = Audio(id=str(uuid4()), content=b"", transcript="")

                if model_response_event.audio.id is not None:
                    full_model_response.audio.id = model_response_event.audio.id  # type: ignore

                if model_response_event.audio.content is not None:
                    # Handle both base64 string and bytes content
                    if isinstance(model_response_event.audio.content, str):
                        # Decode base64 string to bytes
                        try:
                            import base64

                            decoded_content = base64.b64decode(model_response_event.audio.content)
                            if full_model_response.audio.content is None:
                                full_model_response.audio.content = b""
                            full_model_response.audio.content += decoded_content
                        except Exception:
                            # If decode fails, encode string as bytes
                            if full_model_response.audio.content is None:
                                full_model_response.audio.content = b""
                            full_model_response.audio.content += model_response_event.audio.content.encode("utf-8")
                    elif isinstance(model_response_event.audio.content, bytes):
                        # Content is already bytes
                        if full_model_response.audio.content is None:
                            full_model_response.audio.content = b""
                        full_model_response.audio.content += model_response_event.audio.content

                if model_response_event.audio.transcript is not None:
                    if full_model_response.audio.transcript is None:
                        full_model_response.audio.transcript = ""
                    full_model_response.audio.transcript += model_response_event.audio.transcript  # type: ignore
                if model_response_event.audio.expires_at is not None:
                    full_model_response.audio.expires_at = model_response_event.audio.expires_at  # type: ignore
                if model_response_event.audio.mime_type is not None:
                    full_model_response.audio.mime_type = model_response_event.audio.mime_type  # type: ignore
                if model_response_event.audio.sample_rate is not None:
                    full_model_response.audio.sample_rate = model_response_event.audio.sample_rate
                if model_response_event.audio.channels is not None:
                    full_model_response.audio.channels = model_response_event.audio.channels

                # Yield the audio and transcript bit by bit
                should_yield = True

            if model_response_event.images is not None:
                for image in model_response_event.images:
                    if run_response.images is None:
                        run_response.images = []
                    run_response.images.append(image)

                should_yield = True

            # Only yield the chunk
            if should_yield:
                if content_type == "str":
                    yield handle_event(  # type: ignore
                        create_team_run_output_content_event(
                            from_run_response=run_response,
                            content=model_response_event.content,
                            reasoning_content=model_response_event.reasoning_content,
                            redacted_reasoning_content=model_response_event.redacted_reasoning_content,
                            response_audio=full_model_response.audio,
                            citations=model_response_event.citations,
                            model_provider_data=model_response_event.provider_data,
                            image=model_response_event.images[-1] if model_response_event.images else None,
                        ),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )
                else:
                    yield handle_event(  # type: ignore
                        create_team_run_output_content_event(
                            from_run_response=run_response,
                            content=full_model_response.content,
                            content_type=content_type,
                        ),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )

        # If the model response is a tool_call_started, add the tool call to the run_response
        elif model_response_event.event == ModelResponseEvent.tool_call_started.value:
            # Add tool calls to the run_response
            tool_executions_list = model_response_event.tool_executions
            if tool_executions_list is not None:
                # Add tool calls to the agent.run_response
                if run_response.tools is None:
                    run_response.tools = tool_executions_list
                else:
                    run_response.tools.extend(tool_executions_list)

                for tool in tool_executions_list:
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_team_tool_call_started_event(
                                from_run_response=run_response,
                                tool=tool,
                            ),
                            run_response,
                            events_to_skip=team.events_to_skip,
                            store_events=team.store_events,
                        )

        # If the model response is a tool_call_completed, update the existing tool call in the run_response
        elif model_response_event.event == ModelResponseEvent.tool_call_completed.value:
            if model_response_event.updated_session_state is not None:
                # Update the session_state variable that TeamRunOutput references
                if session_state is not None:
                    merge_dictionaries(session_state, model_response_event.updated_session_state)
                # Also update the DB session object
                if session.session_data is not None:
                    merge_dictionaries(
                        session.session_data["session_state"], model_response_event.updated_session_state
                    )

            if model_response_event.images is not None:
                for image in model_response_event.images:
                    if run_response.images is None:
                        run_response.images = []
                    run_response.images.append(image)

            if model_response_event.videos is not None:
                for video in model_response_event.videos:
                    if run_response.videos is None:
                        run_response.videos = []
                    run_response.videos.append(video)

            if model_response_event.audios is not None:
                for audio in model_response_event.audios:
                    if run_response.audio is None:
                        run_response.audio = []
                    run_response.audio.append(audio)

            if model_response_event.files is not None:
                for file_obj in model_response_event.files:
                    if run_response.files is None:
                        run_response.files = []
                    run_response.files.append(file_obj)

            reasoning_step: Optional[ReasoningStep] = None
            tool_executions_list = model_response_event.tool_executions
            if tool_executions_list is not None:
                # Update the existing tool call in the run_response
                if run_response.tools:
                    # Create a mapping of tool_call_id to index
                    tool_call_index_map = {
                        tc.tool_call_id: i for i, tc in enumerate(run_response.tools) if tc.tool_call_id is not None
                    }
                    # Process tool calls
                    for tool_execution in tool_executions_list:
                        tool_call_id = tool_execution.tool_call_id or ""
                        index = tool_call_index_map.get(tool_call_id)
                        if index is not None:
                            if run_response.tools[index].child_run_id is not None:
                                tool_execution.child_run_id = run_response.tools[index].child_run_id
                            run_response.tools[index] = tool_execution
                else:
                    run_response.tools = tool_executions_list

                # Only iterate through new tool calls
                for tool_call in tool_executions_list:
                    tool_name = tool_call.tool_name or ""
                    if tool_name.lower() in ["think", "analyze"]:
                        tool_args = tool_call.tool_args or {}

                        reasoning_step = team._update_reasoning_content_from_tool_call(
                            run_response, tool_name, tool_args
                        )

                        metrics = tool_call.metrics
                        if metrics is not None and metrics.duration is not None and reasoning_state is not None:
                            reasoning_state["reasoning_time_taken"] = reasoning_state["reasoning_time_taken"] + float(
                                metrics.duration
                            )

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_team_tool_call_completed_event(
                                from_run_response=run_response,
                                tool=tool_call,
                                content=model_response_event.content,
                            ),
                            run_response,
                            events_to_skip=team.events_to_skip,
                            store_events=team.store_events,
                        )
                        if tool_call.tool_call_error:
                            yield handle_event(  # type: ignore
                                create_team_tool_call_error_event(
                                    from_run_response=run_response, tool=tool_call, error=str(tool_call.result)
                                ),
                                run_response,
                                events_to_skip=team.events_to_skip,
                                store_events=team.store_events,
                            )

            if stream_events:
                if reasoning_step is not None:
                    if reasoning_state is not None and not reasoning_state["reasoning_started"]:
                        yield handle_event(  # type: ignore
                            create_team_reasoning_started_event(
                                from_run_response=run_response,
                            ),
                            run_response,
                            events_to_skip=team.events_to_skip,
                            store_events=team.store_events,
                        )
                        reasoning_state["reasoning_started"] = True

                    yield handle_event(  # type: ignore
                        create_team_reasoning_step_event(
                            from_run_response=run_response,
                            reasoning_step=reasoning_step,
                            reasoning_content=run_response.reasoning_content or "",
                        ),
                        run_response,
                        events_to_skip=team.events_to_skip,
                        store_events=team.store_events,
                    )


def _convert_response_to_structured_format(
    team: "Team", run_response: Union[TeamRunOutput, RunOutput, ModelResponse], run_context: Optional[RunContext] = None
):
    # Get output_schema from run_context
    output_schema = run_context.output_schema if run_context else None

    # Convert the response to the structured format if needed
    if output_schema is not None:
        # If the output schema is a dict, do not convert it into a BaseModel
        if isinstance(output_schema, dict):
            if isinstance(run_response.content, dict):
                # Content is already a dict - just set content_type
                if hasattr(run_response, "content_type"):
                    run_response.content_type = "dict"
            elif isinstance(run_response.content, str):
                parsed_dict = parse_response_dict_str(run_response.content)
                if parsed_dict is not None:
                    run_response.content = parsed_dict
                    if hasattr(run_response, "content_type"):
                        run_response.content_type = "dict"
                else:
                    log_warning("Failed to parse JSON response")
        # If the output schema is a Pydantic model and parse_response is True, parse it into a BaseModel
        elif not isinstance(run_response.content, output_schema):
            if isinstance(run_response.content, str) and team.parse_response:
                try:
                    parsed_response_content = parse_response_model_str(run_response.content, output_schema)

                    # Update TeamRunOutput
                    if parsed_response_content is not None:
                        run_response.content = parsed_response_content
                        if hasattr(run_response, "content_type"):
                            run_response.content_type = output_schema.__name__
                    else:
                        log_warning("Failed to convert response to output_schema")
                except Exception as e:
                    log_warning(f"Failed to convert response to output model: {e}")
            else:
                log_warning("Something went wrong. Team run response content is not a string")
    elif team._member_response_model is not None:
        # Handle dict schema from member
        if isinstance(team._member_response_model, dict):
            if isinstance(run_response.content, dict):
                # Content is already a dict - just set content_type
                if hasattr(run_response, "content_type"):
                    run_response.content_type = "dict"
            elif isinstance(run_response.content, str):
                parsed_dict = parse_response_dict_str(run_response.content)
                if parsed_dict is not None:
                    run_response.content = parsed_dict
                    if hasattr(run_response, "content_type"):
                        run_response.content_type = "dict"
                else:
                    log_warning("Failed to parse JSON response")
        # Handle Pydantic schema from member
        elif not isinstance(run_response.content, team._member_response_model):
            if isinstance(run_response.content, str):
                try:
                    parsed_response_content = parse_response_model_str(
                        run_response.content, team._member_response_model
                    )
                    # Update TeamRunOutput
                    if parsed_response_content is not None:
                        run_response.content = parsed_response_content
                        if hasattr(run_response, "content_type"):
                            run_response.content_type = team._member_response_model.__name__
                    else:
                        log_warning("Failed to convert response to output_schema")
                except Exception as e:
                    log_warning(f"Failed to convert response to output model: {e}")
            else:
                log_warning("Something went wrong. Member run response content is not a string")


def _make_memories(
    team: "Team",
    run_messages: RunMessages,
    user_id: Optional[str] = None,
):
    user_message_str = run_messages.user_message.get_content_string() if run_messages.user_message is not None else None
    if (
        user_message_str is not None
        and user_message_str.strip() != ""
        and team.memory_manager is not None
        and team.update_memory_on_run
    ):
        log_debug("Managing user memories")
        team.memory_manager.create_user_memories(
            message=user_message_str,
            user_id=user_id,
            team_id=team.id,
        )


async def _amake_memories(
    team: "Team",
    run_messages: RunMessages,
    user_id: Optional[str] = None,
):
    user_message_str = run_messages.user_message.get_content_string() if run_messages.user_message is not None else None
    if (
        user_message_str is not None
        and user_message_str.strip() != ""
        and team.memory_manager is not None
        and team.update_memory_on_run
    ):
        log_debug("Managing user memories")
        await team.memory_manager.acreate_user_memories(
            message=user_message_str,
            user_id=user_id,
            team_id=team.id,
        )


async def _astart_memory_task(
    team: "Team",
    run_messages: RunMessages,
    user_id: Optional[str],
    existing_task: Optional[asyncio.Task[None]],
) -> Optional[asyncio.Task[None]]:
    """Cancel any existing memory task and start a new one if conditions are met.

    Args:
        run_messages: The run messages containing the user message.
        user_id: The user ID for memory creation.
        existing_task: An existing memory task to cancel before starting a new one.

    Returns:
        A new memory task if conditions are met, None otherwise.
    """
    # Cancel any existing task from a previous retry attempt
    if existing_task is not None and not existing_task.done():
        existing_task.cancel()
        try:
            await existing_task
        except asyncio.CancelledError:
            pass

    # Create new task if conditions are met
    if (
        run_messages.user_message is not None
        and team.memory_manager is not None
        and team.update_memory_on_run
        and not team.enable_agentic_memory
    ):
        log_debug("Starting memory creation in background task.")
        return asyncio.create_task(team._amake_memories(run_messages=run_messages, user_id=user_id))

    return None


def _start_memory_future(
    team: "Team",
    run_messages: RunMessages,
    user_id: Optional[str],
    existing_future: Optional[Future[None]],
) -> Optional[Future[None]]:
    """Cancel any existing memory future and start a new one if conditions are met.

    Args:
        run_messages: The run messages containing the user message.
        user_id: The user ID for memory creation.
        existing_future: An existing memory future to cancel before starting a new one.

    Returns:
        A new memory future if conditions are met, None otherwise.
    """
    # Cancel any existing future from a previous retry attempt
    if existing_future is not None and not existing_future.done():
        existing_future.cancel()

    # Create new future if conditions are met
    if (
        run_messages.user_message is not None
        and team.memory_manager is not None
        and team.update_memory_on_run
        and not team.enable_agentic_memory
    ):
        log_debug("Starting memory creation in background thread.")
        return team.background_executor.submit(team._make_memories, run_messages=run_messages, user_id=user_id)

    return None
