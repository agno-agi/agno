"""Core run loop and execution helpers for Agent."""

from __future__ import annotations

import asyncio
import time
import warnings
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

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.agent._init import _initialize_session_state
from agno.agent._run_options import resolve_run_options
from agno.agent._session import initialize_session, update_session_metrics
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
    RunCancelledEvent,
    RunCompletedEvent,
    RunInput,
    RunOutput,
    RunOutputEvent,
)
from agno.run.approval import (
    acreate_approval_from_pause,
    create_approval_from_pause,
)
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
from agno.run.requirement import RunRequirement
from agno.session import AgentSession
from agno.tools.function import Function
from agno.utils.agent import (
    await_for_open_threads,
    await_for_thread_tasks_stream,
    collect_background_metrics,
    isolate_media_scrub_targets,
    scrub_history_messages_from_run_output,
    scrub_media_from_run_output,
    scrub_tool_results_from_run_output,
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
    create_run_paused_event,
    create_run_started_event,
    create_session_summary_completed_event,
    create_session_summary_started_event,
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
from agno.utils.response import get_paused_content

# Strong references to background tasks so they aren't garbage-collected mid-execution.
# See: https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
_background_tasks: set[asyncio.Task[None]] = set()

# Cancel raises immediately on every event. Only terminal events bypass so the
# run's own cancel handler can yield them to the stream.
_CANCEL_BYPASS_EVENT_TYPES = (
    RunCancelledEvent,
    RunCompletedEvent,
)

# ---------------------------------------------------------------------------
# Run dependency resolution
# ---------------------------------------------------------------------------


def resolve_run_dependencies(agent: Agent, run_context: RunContext) -> None:
    from inspect import iscoroutine, iscoroutinefunction, signature

    # Dependencies should already be resolved in run() method
    log_debug("Resolving dependencies")
    if not isinstance(run_context.dependencies, dict):
        log_warning("Run dependencies are not a dict")
        return

    for key, value in run_context.dependencies.items():
        if iscoroutine(value) or iscoroutinefunction(value):
            log_warning(f"Dependency {key} is a coroutine. Use agent.arun() or agent.aprint_response() instead.")
            continue
        elif callable(value):
            try:
                sig = signature(value)

                # Build kwargs for the function
                kwargs: Dict[str, Any] = {}
                if "agent" in sig.parameters:
                    kwargs["agent"] = agent
                if "run_context" in sig.parameters:
                    kwargs["run_context"] = run_context

                # Run the function
                result = value(**kwargs)

                # Carry the result in the run context
                if result is not None:
                    run_context.dependencies[key] = result

            except Exception as e:
                log_warning(f"Failed to resolve dependencies for '{key}': {str(e)}")
        else:
            run_context.dependencies[key] = value


async def aresolve_run_dependencies(agent: Agent, run_context: RunContext) -> None:
    from inspect import iscoroutine, signature

    log_debug("Resolving context (async)")
    if not isinstance(run_context.dependencies, dict):
        log_warning("Run dependencies are not a dict")
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
                kwargs["agent"] = agent
            if "run_context" in sig.parameters:
                kwargs["run_context"] = run_context

            # Run the function
            result = value(**kwargs)
            if iscoroutine(result):
                result = await result  # type: ignore

            run_context.dependencies[key] = result
        except Exception as e:
            log_warning(f"Failed to resolve context for '{key}': {str(e)}")


# ---------------------------------------------------------------------------
# Pause handling
# ---------------------------------------------------------------------------


def handle_agent_run_paused(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    user_id: Optional[str] = None,
    run_context: Optional[RunContext] = None,
) -> RunOutput:
    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = get_paused_content(run_response)

    # Stamp approval_id on tools before storing so the DB has the complete data.
    create_approval_from_pause(
        db=agent.db, run_response=run_response, agent_id=agent.id, agent_name=agent.name, user_id=user_id
    )

    cleanup_and_store(agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id)

    log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")

    # We return and await confirmation/completion for the tools that require it
    return run_response


def handle_agent_run_paused_stream(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    user_id: Optional[str] = None,
    run_context: Optional[RunContext] = None,
    yield_run_output: bool = False,
) -> Iterator[Union[RunOutputEvent, RunOutput]]:
    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = get_paused_content(run_response)

    # Stamp approval_id on tools before storing so the DB has the complete data.
    create_approval_from_pause(
        db=agent.db, run_response=run_response, agent_id=agent.id, agent_name=agent.name, user_id=user_id
    )

    # Create RunPausedEvent and add to run_response.events before storing
    pause_event = handle_event(
        create_run_paused_event(
            from_run_response=run_response,
            tools=run_response.tools,
            requirements=run_response.requirements,
        ),
        run_response,
        events_to_skip=agent.events_to_skip,  # type: ignore
        store_events=agent.store_events,
    )

    cleanup_and_store(agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id)

    yield pause_event  # type: ignore

    # Also yield the run_response if requested, so callers can capture it
    if yield_run_output:
        yield run_response

    log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")


async def ahandle_agent_run_paused(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    user_id: Optional[str] = None,
    run_context: Optional[RunContext] = None,
) -> RunOutput:
    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = get_paused_content(run_response)

    # Stamp approval_id on tools before storing so the DB has the complete data.
    await acreate_approval_from_pause(
        db=agent.db, run_response=run_response, agent_id=agent.id, agent_name=agent.name, user_id=user_id
    )
    await acleanup_and_store(
        agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
    )

    log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")

    # We return and await confirmation/completion for the tools that require it
    return run_response


async def ahandle_agent_run_paused_stream(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    user_id: Optional[str] = None,
    run_context: Optional[RunContext] = None,
    yield_run_output: bool = False,
) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]:
    run_response.status = RunStatus.paused
    if not run_response.content:
        run_response.content = get_paused_content(run_response)

    # Stamp approval_id on tools before storing so the DB has the complete data.
    await acreate_approval_from_pause(
        db=agent.db, run_response=run_response, agent_id=agent.id, agent_name=agent.name, user_id=user_id
    )

    # Create RunPausedEvent and add to run_response.events before storing
    pause_event = handle_event(
        create_run_paused_event(
            from_run_response=run_response,
            tools=run_response.tools,
            requirements=run_response.requirements,
        ),
        run_response,
        events_to_skip=agent.events_to_skip,  # type: ignore
        store_events=agent.store_events,
    )

    await acleanup_and_store(
        agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
    )

    yield pause_event  # type: ignore

    # Also yield the run_response if requested, so callers can capture it
    if yield_run_output:
        yield run_response

    log_debug(f"Agent Run Paused: {run_response.run_id}", center=True, symbol="*")


def _run(
    agent: Agent,
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
    pre_session: Optional[AgentSession] = None,
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
    7. Start memory creation in background thread
    8. Reason about the task if reasoning is enabled
    9. Generate a response from the Model (includes running function calls)
    10. Update the RunOutput with the model response
    11. Store media if enabled
    12. Convert the response to the structured format if needed
    13. Execute post-hooks
    14. Wait for background memory creation and cultural knowledge creation
    15. Create session summary
    16. Cleanup and store the run response and session
    """
    from agno.agent._hooks import execute_post_hooks, execute_pre_hooks
    from agno.agent._init import disconnect_connectable_tools
    from agno.agent._messages import get_run_messages
    from agno.agent._response import (
        convert_response_to_structured_format,
        generate_followups,
        generate_response_with_output_model,
        handle_reasoning,
        parse_response_with_parser_model,
        update_run_response,
    )
    from agno.agent._storage import load_session_state, read_or_create_session, update_metadata
    from agno.agent._telemetry import log_agent_telemetry
    from agno.agent._tools import determine_tools_for_model

    register_run(run_context.run_id)
    log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

    memory_future = None
    learning_future = None
    cultural_knowledge_future = None
    agent_session: Optional[AgentSession] = None

    try:
        # Set up retry logic
        num_attempts = agent.retries + 1
        for attempt in range(num_attempts):
            if attempt > 0:
                log_debug(f"Retrying Agent run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            # Bind run_messages early — pre-hook iteration checks cancellation
            # before run_messages is built, and the cancellation handler reads it.
            run_messages: Optional[RunMessages] = None
            try:
                # 1. Read or create session. Reuse pre-read session on first attempt.
                if attempt == 0 and pre_session is not None:
                    agent_session = pre_session
                else:
                    agent_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)

                # 2. Update metadata and session state
                if not (attempt == 0 and pre_session is not None):
                    update_metadata(agent, session=agent_session)

                # Initialize session state. Get it from DB if relevant.
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_context.run_id,
                )

                # 3. Resolve dependencies
                if run_context.dependencies is not None:
                    resolve_run_dependencies(agent, run_context=run_context)

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 4. Execute pre-hooks
                run_input = cast(RunInput, run_response.input)
                agent.model = cast(Model, agent.model)
                if agent.pre_hooks is not None:
                    # Can modify the run input
                    pre_hook_iterator = execute_pre_hooks(
                        agent,
                        hooks=agent.pre_hooks,  # type: ignore
                        run_response=run_response,
                        run_input=run_input,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        background_tasks=background_tasks,
                        **kwargs,
                    )
                    # Consume the generator without yielding
                    deque(pre_hook_iterator, maxlen=0)

                # 5. Determine tools for model
                processed_tools = agent.get_tools(
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    user_id=user_id,
                )
                _tools = determine_tools_for_model(
                    agent,
                    model=agent.model,
                    processed_tools=processed_tools,
                    run_response=run_response,
                    session=agent_session,
                    run_context=run_context,
                )

                # 6. Prepare run messages
                run_messages = get_run_messages(
                    agent,
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

                # Start memory creation in background thread
                from agno.agent import _managers

                memory_future = _managers.start_memory_future(
                    agent,
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_future=memory_future,
                )

                # Start learning extraction as a background task (runs concurrently with the main execution)
                learning_future = _managers.start_learning_future(
                    agent,
                    run_messages=run_messages,
                    session=agent_session,
                    user_id=user_id,
                    existing_future=learning_future,
                )

                # Start cultural knowledge creation in background thread
                cultural_knowledge_future = _managers.start_cultural_knowledge_future(
                    agent,
                    run_messages=run_messages,
                    existing_future=cultural_knowledge_future,
                )

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 5. Reason about the task
                handle_reasoning(agent, run_response=run_response, run_messages=run_messages, run_context=run_context)

                # Check for cancellation before model call
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 6. Generate a response from the Model (includes running function calls)
                agent.model = cast(Model, agent.model)

                model_response: ModelResponse = call_model_with_fallback(
                    agent.model,
                    agent.fallback_config,
                    messages=run_messages.messages,
                    tools=_tools,
                    tool_choice=agent.tool_choice,
                    tool_call_limit=agent.tool_call_limit,
                    response_format=response_format,
                    run_response=run_response,
                    send_media_to_model=agent.send_media_to_model,
                    compression_manager=agent.compression_manager if agent.compress_tool_results else None,
                    after_tool_results=build_after_tool_results_callback(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_messages=run_messages,
                        run_context=run_context,
                    ),
                )

                # Check for cancellation after model call
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # If an output model is provided, generate output using the output model
                generate_response_with_output_model(agent, model_response, run_messages, run_response=run_response)

                # If a parser model is provided, structure the response separately
                parse_response_with_parser_model(
                    agent, model_response, run_messages, run_context=run_context, run_response=run_response
                )

                # 7. Update the RunOutput with the model response
                update_run_response(
                    agent,
                    model_response=model_response,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                )

                # We should break out of the run function
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    wait_for_open_threads(
                        memory_future=memory_future,  # type: ignore
                        cultural_knowledge_future=cultural_knowledge_future,  # type: ignore
                        learning_future=learning_future,  # type: ignore
                    )
                    merge_background_metrics(
                        run_response.metrics,
                        collect_background_metrics(memory_future, cultural_knowledge_future, learning_future),
                    )

                    return handle_agent_run_paused(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # 8. Store media in run output for the caller
                store_media_util(run_response, model_response)

                # 9. Convert the response to the structured format if needed
                convert_response_to_structured_format(agent, run_response, run_context=run_context)

                # 9b. Generate follow-up suggestions if enabled
                generate_followups(agent, run_response=run_response)

                # 10. Execute post-hooks after output is generated but before response is returned
                if agent.post_hooks is not None:
                    post_hook_iterator = execute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
                        run_output=run_response,
                        run_context=run_context,
                        session=agent_session,
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
                merge_background_metrics(
                    run_response.metrics,
                    collect_background_metrics(memory_future, cultural_knowledge_future, learning_future),
                )

                # 12. Create session summary
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    agent_session.upsert_run(run=run_response)
                    try:
                        agent.session_summary_manager.create_session_summary(
                            session=agent_session, run_metrics=run_response.metrics
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                run_response.status = RunStatus.completed

                # 13. Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=agent_session, run_context=run_context, user_id=user_id
                )

                # Log Agent Telemetry
                log_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response
            except RunCancelledException as e:
                run_response = _handle_run_cancellation(run_response, e, run_messages)
                try:
                    if agent_session is not None:
                        cleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                return run_response
            except (InputCheckError, OutputCheckError) as e:
                # Handle exceptions during streaming
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                if agent_session is not None:
                    cleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response
            except KeyboardInterrupt:
                run_response = _handle_run_cancellation(run_response, KeyboardInterrupt(), run_messages)
                try:
                    if agent_session is not None:
                        cleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                return run_response

            except Exception as e:
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    time.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    cleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response
    finally:
        # Cancel background futures on error (wait_for_open_threads handles waiting on success)
        for future in (memory_future, cultural_knowledge_future, learning_future):
            if future is not None and not future.done():
                future.cancel()
                try:
                    future.result(timeout=0)
                except Exception:
                    pass

        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always clean up the run tracking
        cleanup_run(run_response.run_id)  # type: ignore

    return run_response


def _run_stream(
    agent: Agent,
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
    pre_session: Optional[AgentSession] = None,
    **kwargs: Any,
) -> Iterator[Union[RunOutputEvent, RunOutput]]:
    """Run the Agent and yield the RunOutput.

    Steps:
    1. Read or create session
    2. Update metadata and session state
    3. Resolve dependencies
    4. Execute pre-hooks
    5. Determine tools for model
    6. Prepare run messages
    7. Start memory creation in background thread
    8. Reason about the task if reasoning is enabled
    9. Process model response
    10. Parse response with parser model if provided
    11. Wait for background memory creation and cultural knowledge creation
    12. Create session summary
    13. Cleanup and store the run response and session
    """
    from agno.agent._hooks import execute_post_hooks, execute_pre_hooks
    from agno.agent._init import disconnect_connectable_tools
    from agno.agent._messages import get_run_messages
    from agno.agent._response import (
        generate_followups_stream,
        generate_response_with_output_model_stream,
        handle_model_response_stream,
        handle_reasoning_stream,
        parse_response_with_parser_model_stream,
    )
    from agno.agent._storage import load_session_state, read_or_create_session, update_metadata
    from agno.agent._telemetry import log_agent_telemetry
    from agno.agent._tools import determine_tools_for_model

    register_run(run_context.run_id)
    log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

    memory_future = None
    learning_future = None
    cultural_knowledge_future = None
    agent_session: Optional[AgentSession] = None

    try:
        # Set up retry logic
        num_attempts = agent.retries + 1
        for attempt in range(num_attempts):
            if attempt > 0:
                log_debug(f"Retrying Agent run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            # Bind run_messages early — pre-hook iteration checks cancellation
            # before run_messages is built, and the cancellation handler reads it.
            run_messages: Optional[RunMessages] = None
            try:
                # 1. Read or create session. Reuse pre-read session on first attempt.
                if attempt == 0 and pre_session is not None:
                    agent_session = pre_session
                else:
                    agent_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)

                # 2. Update metadata and session state
                if not (attempt == 0 and pre_session is not None):
                    update_metadata(agent, session=agent_session)

                # Initialize session state. Get it from DB if relevant.
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_context.run_id,
                )

                # 3. Resolve dependencies
                if run_context.dependencies is not None:
                    resolve_run_dependencies(agent, run_context=run_context)

                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 4. Execute pre-hooks
                run_input = cast(RunInput, run_response.input)
                agent.model = cast(Model, agent.model)
                if agent.pre_hooks is not None:
                    # Can modify the run input
                    pre_hook_iterator = execute_pre_hooks(
                        agent,
                        hooks=agent.pre_hooks,  # type: ignore
                        run_response=run_response,
                        run_input=run_input,
                        run_context=run_context,
                        session=agent_session,
                        user_id=user_id,
                        debug_mode=debug_mode,
                        stream_events=stream_events,
                        background_tasks=background_tasks,
                        **kwargs,
                    )
                    for event in pre_hook_iterator:
                        yield event

                # 5. Determine tools for model
                processed_tools = agent.get_tools(
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    user_id=user_id,
                )
                _tools = determine_tools_for_model(
                    agent,
                    model=agent.model,
                    processed_tools=processed_tools,
                    run_response=run_response,
                    session=agent_session,
                    run_context=run_context,
                )

                # 6. Prepare run messages
                run_messages = get_run_messages(
                    agent,
                    run_response=run_response,
                    input=run_input.input_content,
                    session=agent_session,
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

                # 7. Start memory creation in background thread
                from agno.agent import _managers

                memory_future = _managers.start_memory_future(
                    agent,
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_future=memory_future,
                )

                # Start learning extraction as a background task (runs concurrently with the main execution)
                learning_future = _managers.start_learning_future(
                    agent,
                    run_messages=run_messages,
                    session=agent_session,
                    user_id=user_id,
                    existing_future=learning_future,
                )

                # Start cultural knowledge creation in background thread
                cultural_knowledge_future = _managers.start_cultural_knowledge_future(
                    agent,
                    run_messages=run_messages,
                    existing_future=cultural_knowledge_future,
                )

                # Start the Run by yielding a RunStarted event
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_started_event(run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # 5. Reason about the task if reasoning is enabled
                yield from handle_reasoning_stream(
                    agent,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                    stream_events=stream_events,
                )

                # Check for cancellation before model processing
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 6. Process model response
                if agent.output_model is None:
                    for event in handle_model_response_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        session_state=run_context.session_state,
                        run_context=run_context,
                    ):
                        if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                            raise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event
                else:
                    from agno.run.agent import (
                        IntermediateRunContentEvent,
                        RunContentEvent,
                    )  # type: ignore

                    for event in handle_model_response_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        session_state=run_context.session_state,
                        run_context=run_context,
                    ):
                        if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
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
                    for event in generate_response_with_output_model_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        stream_events=stream_events,
                    ):
                        if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                            raise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event  # type: ignore

                # Check for cancellation after model processing
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 7. Parse response with parser model if provided
                for event in parse_response_with_parser_model_stream(
                    agent,  # type: ignore
                    session=agent_session,
                    run_response=run_response,
                    stream_events=stream_events,
                    run_context=run_context,
                ):
                    if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                        raise_if_cancelled(run_response.run_id)  # type: ignore
                    yield event

                # 7b. Generate follow-up suggestions if enabled
                for event in generate_followups_stream(
                    agent,  # type: ignore
                    run_response=run_response,
                    stream_events=stream_events,
                ):
                    if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                        raise_if_cancelled(run_response.run_id)  # type: ignore
                    yield event

                # We should break out of the run function
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    yield from wait_for_thread_tasks_stream(
                        memory_future=memory_future,  # type: ignore
                        cultural_knowledge_future=cultural_knowledge_future,  # type: ignore
                        learning_future=learning_future,  # type: ignore
                        stream_events=stream_events,
                        run_response=run_response,
                        events_to_skip=agent.events_to_skip,
                        store_events=agent.store_events,
                        get_memories_callback=lambda: agent.get_user_memories(user_id=user_id),
                    )
                    merge_background_metrics(
                        run_response.metrics,
                        collect_background_metrics(memory_future, cultural_knowledge_future, learning_future),
                    )

                    # Handle the paused run
                    yield from handle_agent_run_paused_stream(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                        yield_run_output=yield_run_output or False,
                    )
                    return

                # Yield RunContentCompletedEvent
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_content_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # Execute post-hooks after output is generated but before response is returned
                if agent.post_hooks is not None:
                    yield from execute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
                        run_output=run_response,
                        run_context=run_context,
                        session=agent_session,
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
                    events_to_skip=agent.events_to_skip,
                    store_events=agent.store_events,
                    get_memories_callback=lambda: agent.get_user_memories(user_id=user_id),
                )
                merge_background_metrics(
                    run_response.metrics,
                    collect_background_metrics(memory_future, cultural_knowledge_future, learning_future),
                )

                # 9. Create session summary
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    agent_session.upsert_run(run=run_response)

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )
                    try:
                        agent.session_summary_manager.create_session_summary(
                            session=agent_session, run_metrics=run_response.metrics
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_completed_event(
                                from_run_response=run_response, session_summary=agent_session.summary
                            ),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )

                # Update run_response.session_state before creating RunCompletedEvent
                # This ensures the event has the final state after all tool modifications
                if agent_session.session_data is not None and "session_state" in agent_session.session_data:
                    run_response.session_state = agent_session.session_data["session_state"]

                # Create the run completed event
                completed_event = handle_event(  # type: ignore
                    create_run_completed_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 10. Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=agent_session, run_context=run_context, user_id=user_id
                )

                if stream_events:
                    yield completed_event  # type: ignore

                if yield_run_output:
                    yield run_response

                # Log Agent Telemetry
                log_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                break
            except RunCancelledException as e:
                run_response = _handle_run_cancellation(run_response, e, run_messages)
                cancelled_event, completed_event = _build_cancel_terminal_events(
                    agent,
                    run_response,
                    error=e,
                    run_context=run_context,
                )
                try:
                    if agent_session is not None:
                        cleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break
            except (InputCheckError, OutputCheckError) as e:
                # Handle exceptions during streaming
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
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

                if agent_session is not None:
                    cleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )
                yield run_error
                break
            except KeyboardInterrupt:
                run_response = _handle_run_cancellation(run_response, KeyboardInterrupt(), run_messages)
                cancelled_event, completed_event = _build_cancel_terminal_events(
                    agent,
                    run_response,
                    error=KeyboardInterrupt(),
                    run_context=run_context,
                )
                try:
                    if agent_session is not None:
                        cleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
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
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    time.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
                # Add error event to list of events
                run_error = create_run_error_event(run_response, error=str(e))
                run_response.events = add_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    cleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                yield run_error
    finally:
        # Cancel background futures on error (wait_for_thread_tasks_stream handles waiting on success)
        for future in (memory_future, cultural_knowledge_future, learning_future):
            if future is not None and not future.done():
                future.cancel()
                try:
                    future.result(timeout=0)
                except Exception:
                    pass

        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always clean up the run tracking
        cleanup_run(run_response.run_id)  # type: ignore


def run_dispatch(
    agent: Agent,
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
    from agno.agent._init import has_async_db
    from agno.agent._response import get_response_format

    if has_async_db(agent):
        raise RuntimeError("`run` method is not supported with an async database. Please use `arun` method instead.")

    # Set the id for the run and register it immediately for cancellation tracking
    run_id = run_id or str(uuid4())

    if (add_history_to_context or agent.add_history_to_context) and not agent.db and not agent.team_id:
        log_warning(
            "add_history_to_context is True, but no database has been assigned to the agent. History will not be added to the context."
        )

    background_tasks = kwargs.pop("background_tasks", None)
    if background_tasks is not None:
        from fastapi import BackgroundTasks

        background_tasks: BackgroundTasks = background_tasks  # type: ignore

    # Validate input against input_schema if provided
    validated_input = validate_input(input, agent.input_schema)

    # Normalise hook & guardails
    if not agent._hooks_normalised:
        if agent.pre_hooks:
            agent.pre_hooks = normalize_pre_hooks(agent.pre_hooks)  # type: ignore
        if agent.post_hooks:
            agent.post_hooks = normalize_post_hooks(agent.post_hooks)  # type: ignore
        agent._hooks_normalised = True

    # Initialize session
    session_id, user_id = initialize_session(agent, session_id=session_id, user_id=user_id)

    # Initialize the Agent
    agent.initialize_agent(debug_mode=debug_mode)

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

    # Read existing session and update metadata BEFORE resolving run options,
    # so that session-stored metadata is visible to resolve_run_options.
    from agno.agent._storage import read_or_create_session, update_metadata

    agent_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)
    update_metadata(agent, session=agent_session)

    # Resolve all run options centrally
    opts = resolve_run_options(
        agent,
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

    agent.model = cast(Model, agent.model)

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
        dependencies_provided=dependencies is not None,
        knowledge_filters_provided=knowledge_filters is not None,
        metadata_provided=metadata is not None,
    )

    # Prepare arguments for the model (must be after run_context is fully initialized)
    response_format = get_response_format(agent, run_context=run_context) if agent.parser_model is None else None

    # Create a new run_response for this attempt
    run_response = RunOutput(
        run_id=run_id,
        session_id=session_id,
        agent_id=agent.id,
        user_id=user_id,
        agent_name=agent.name,
        metadata=run_context.metadata,
        session_state=run_context.session_state,
        input=run_input,
    )

    run_response.model = agent.model.id if agent.model is not None else None
    run_response.model_provider = agent.model.provider if agent.model is not None else None

    # Start the run metrics timer, to calculate the run duration
    run_response.metrics = RunMetrics()
    run_response.metrics.start_timer()

    if opts.stream:
        response_iterator = _run_stream(
            agent,
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
            pre_session=agent_session,
            **kwargs,
        )
        return response_iterator
    else:
        response = _run(
            agent,
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
            pre_session=agent_session,
            **kwargs,
        )
        return response


async def _arun(
    agent: Agent,
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
    pre_session: Optional[AgentSession] = None,
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
    from agno.agent._hooks import aexecute_post_hooks, aexecute_pre_hooks
    from agno.agent._init import disconnect_connectable_tools, disconnect_mcp_tools
    from agno.agent._messages import aget_run_messages
    from agno.agent._response import (
        agenerate_followups,
        agenerate_response_with_output_model,
        ahandle_reasoning,
        aparse_response_with_parser_model,
        convert_response_to_structured_format,
        update_run_response,
    )
    from agno.agent._storage import aread_or_create_session, load_session_state, update_metadata
    from agno.agent._telemetry import alog_agent_telemetry
    from agno.agent._tools import determine_tools_for_model

    await aregister_run(run_context.run_id)
    log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

    memory_task = None
    learning_task = None
    cultural_knowledge_task = None
    agent_session: Optional[AgentSession] = None

    # Set up retry logic
    num_attempts = agent.retries + 1

    try:
        for attempt in range(num_attempts):
            if attempt > 0:
                log_debug(f"Retrying Agent run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            # Bind run_messages early — pre-hook iteration checks cancellation
            # before run_messages is built, and the cancellation handler reads it.
            run_messages: Optional[RunMessages] = None
            try:
                # 1. Read or create session. Reuse pre-read session on first attempt.
                if attempt == 0 and pre_session is not None:
                    agent_session = pre_session
                else:
                    agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)

                # 2. Update metadata and session state
                if not (attempt == 0 and pre_session is not None):
                    update_metadata(agent, session=agent_session)

                # Initialize session state. Get it from DB if relevant.
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_context.run_id,
                )

                # 3. Resolve dependencies
                if run_context.dependencies is not None:
                    await aresolve_run_dependencies(agent, run_context=run_context)

                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 4. Execute pre-hooks
                run_input = cast(RunInput, run_response.input)
                agent.model = cast(Model, agent.model)
                if agent.pre_hooks is not None:
                    # Can modify the run input
                    pre_hook_iterator = aexecute_pre_hooks(
                        agent,
                        hooks=agent.pre_hooks,  # type: ignore
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
                agent.model = cast(Model, agent.model)
                processed_tools = await agent.aget_tools(
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    user_id=user_id,
                )

                _tools = determine_tools_for_model(
                    agent,
                    model=agent.model,
                    processed_tools=processed_tools,
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    async_mode=True,
                )

                # 6. Prepare run messages
                run_messages = await aget_run_messages(
                    agent,
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
                from agno.agent import _managers

                memory_task = await _managers.astart_memory_task(
                    agent,
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_task=memory_task,
                )

                # Start learning extraction as a background task
                learning_task = await _managers.astart_learning_task(
                    agent,
                    run_messages=run_messages,
                    session=agent_session,
                    user_id=user_id,
                    existing_task=learning_task,
                )

                # Start cultural knowledge creation as a background task (runs concurrently with the main execution)
                cultural_knowledge_task = await _managers.astart_cultural_knowledge_task(
                    agent,
                    run_messages=run_messages,
                    existing_task=cultural_knowledge_task,
                )

                # Check for cancellation before model call
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 8. Reason about the task if reasoning is enabled
                await ahandle_reasoning(
                    agent, run_response=run_response, run_messages=run_messages, run_context=run_context
                )

                # Check for cancellation before model call
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 9. Generate a response from the Model (includes running function calls)
                model_response: ModelResponse = await acall_model_with_fallback(
                    agent.model,
                    agent.fallback_config,
                    messages=run_messages.messages,
                    tools=_tools,
                    tool_choice=agent.tool_choice,
                    tool_call_limit=agent.tool_call_limit,
                    response_format=response_format,
                    send_media_to_model=agent.send_media_to_model,
                    run_response=run_response,
                    compression_manager=agent.compression_manager if agent.compress_tool_results else None,
                    after_tool_results=abuild_after_tool_results_callback(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_messages=run_messages,
                        run_context=run_context,
                    ),
                )

                # Check for cancellation after model call
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # If an output model is provided, generate output using the output model
                await agenerate_response_with_output_model(
                    agent, model_response=model_response, run_messages=run_messages, run_response=run_response
                )

                # If a parser model is provided, structure the response separately
                await aparse_response_with_parser_model(
                    agent,
                    model_response=model_response,
                    run_messages=run_messages,
                    run_context=run_context,
                    run_response=run_response,
                )

                # 10. Update the RunOutput with the model response
                update_run_response(
                    agent,
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
                    merge_background_metrics(
                        run_response.metrics,
                        collect_background_metrics(memory_task, cultural_knowledge_task, learning_task),
                    )
                    return await ahandle_agent_run_paused(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # 11. Convert the response to the structured format if needed
                convert_response_to_structured_format(agent, run_response, run_context=run_context)

                # 11b. Generate follow-up suggestions if enabled
                await agenerate_followups(agent, run_response=run_response)

                # 12. Store media in run output for the caller
                store_media_util(run_response, model_response)

                # 13. Execute post-hooks (after output is generated but before response is returned)
                if agent.post_hooks is not None:
                    async for _ in aexecute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
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
                merge_background_metrics(
                    run_response.metrics,
                    collect_background_metrics(memory_task, cultural_knowledge_task, learning_task),
                )

                # 15. Create session summary
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    agent_session.upsert_run(run=run_response)
                    try:
                        await agent.session_summary_manager.acreate_session_summary(
                            session=agent_session, run_metrics=run_response.metrics
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                run_response.status = RunStatus.completed

                # 16. Cleanup and store the run response and session
                await acleanup_and_store(
                    agent,
                    run_response=run_response,
                    session=agent_session,
                    run_context=run_context,
                    user_id=user_id,
                )

                # Log Agent Telemetry
                await alog_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response

            except RunCancelledException as e:
                run_response = _handle_run_cancellation(run_response, e, run_messages)
                try:
                    if agent_session is not None:
                        await acleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                return run_response
            except (InputCheckError, OutputCheckError) as e:
                # Handle exceptions during streaming
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response
            except (KeyboardInterrupt, asyncio.CancelledError) as cancel_exc:
                run_response = _handle_run_cancellation(run_response, KeyboardInterrupt(), run_messages)
                if agent_session is not None:
                    if isinstance(cancel_exc, asyncio.CancelledError):
                        # Client disconnect: persist on a detached task so the cancel scope can't abort the write
                        _persist_cancelled_run_in_background(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                    else:
                        # Ctrl-C under asyncio.run: persist inline; a detached task would not run before the loop exits
                        await acleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                # Re-raise on disconnect to propagate it; return the partial on Ctrl-C
                if isinstance(cancel_exc, asyncio.CancelledError):
                    raise
                return run_response
            except Exception as e:
                # Check if this is the last attempt
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    await asyncio.sleep(delay)
                    continue

                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response
    finally:
        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always disconnect MCP tools
        await disconnect_mcp_tools(agent)

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


async def _arun_background(
    agent: Agent,
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
    """Start an agent run in the background and return immediately with PENDING status.

    The run is persisted with PENDING status, then an asyncio task is spawned
    to execute the actual run. The task transitions through RUNNING -> COMPLETED/ERROR.

    Callers can poll for results via agent.aget_run_output(run_id, session_id).
    """
    from agno.agent._session import asave_session
    from agno.agent._storage import aread_or_create_session, update_metadata

    # 1. Register the run for cancellation tracking (before spawning the task)
    await aregister_run(run_context.run_id)

    # 2. Set status to PENDING
    run_response.status = RunStatus.pending

    # 3. Persist the PENDING run so polling can find it immediately
    agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)
    update_metadata(agent, session=agent_session)
    agent_session.upsert_run(run=run_response)
    await asave_session(agent, session=agent_session)

    log_info(f"Background run {run_response.run_id} created with PENDING status")

    # 4. Spawn the background task
    async def _background_task() -> None:
        try:
            # Transition to RUNNING
            run_response.status = RunStatus.running
            agent_session.upsert_run(run=run_response)
            await asave_session(agent, session=agent_session)

            # Execute the actual run — _arun handles everything including
            # session persistence and cleanup
            await _arun(
                agent,
                run_response=run_response,
                run_context=run_context,
                user_id=user_id,
                response_format=response_format,
                session_id=session_id,
                add_history_to_context=add_history_to_context,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )
        except Exception as e:
            log_error(f"Background run {run_response.run_id} failed: {str(e)}")
            # Persist ERROR status
            try:
                run_response.status = RunStatus.error
                agent_session.upsert_run(run=run_response)
                await asave_session(agent, session=agent_session)
            except Exception as e:
                log_error(f"Failed to persist error state for background run {run_response.run_id}: {str(e)}")
            # Note: acleanup_run is already called by _arun's finally block

    task = asyncio.create_task(_background_task())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # 5. Return immediately with the PENDING response
    return run_response


async def _arun_background_stream(
    agent: Agent,
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
) -> AsyncIterator[str]:
    """Background streaming agent run that survives client disconnections.

    1. Persists RUNNING status in DB
    2. Spawns a detached asyncio.Task that runs _arun_stream
    3. Buffers events (via event_buffer) and publishes to SSE subscribers
    4. Yields SSE-formatted strings via an asyncio.Queue

    The detached task keeps running even if the client disconnects.
    The caller (router) just yields the SSE strings to the client.

    Similar to how Workflow._arun_background_stream handles WebSocket streaming,
    but uses SSE transport with event_buffer and sse_subscriber_manager.
    """
    from agno.agent._session import asave_session
    from agno.agent._storage import aread_or_create_session, update_metadata

    run_id = run_response.run_id
    if not run_id:
        raise ValueError("run_id is required for background streaming")

    # 1. Persist RUNNING status so the run is visible in the DB immediately
    run_response.status = RunStatus.running

    agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)
    update_metadata(agent, session=agent_session)
    agent_session.upsert_run(run=run_response)
    await asave_session(agent, session=agent_session)

    log_info(f"Background stream run {run_id} persisted with RUNNING status")

    # 2. Create queue for forwarding SSE strings to the caller
    sse_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    # 3. Spawn detached background task
    async def _background_producer() -> None:
        from agno.os.managers import event_buffer, sse_subscriber_manager
        from agno.os.utils import format_sse_event_with_index

        try:
            async for event in _arun_stream(
                agent,
                run_response=run_response,
                run_context=run_context,
                user_id=user_id,
                response_format=response_format,
                stream_events=stream_events,
                yield_run_output=yield_run_output,
                session_id=session_id,
                add_history_to_context=add_history_to_context,
                add_dependencies_to_context=add_dependencies_to_context,
                add_session_state_to_context=add_session_state_to_context,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                pre_session=agent_session,
                **kwargs,
            ):
                if isinstance(event, RunOutput):
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
                agent_session.upsert_run(run=run_response)
                await asave_session(agent, session=agent_session)
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
    agent: Agent,
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
    pre_session: Optional[AgentSession] = None,
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
    from agno.agent._hooks import aexecute_post_hooks, aexecute_pre_hooks
    from agno.agent._init import disconnect_connectable_tools, disconnect_mcp_tools
    from agno.agent._messages import aget_run_messages
    from agno.agent._response import (
        agenerate_followups_stream,
        agenerate_response_with_output_model_stream,
        ahandle_model_response_stream,
        ahandle_reasoning_stream,
        aparse_response_with_parser_model_stream,
    )
    from agno.agent._storage import aread_or_create_session, load_session_state, update_metadata
    from agno.agent._telemetry import alog_agent_telemetry
    from agno.agent._tools import determine_tools_for_model

    await aregister_run(run_context.run_id)
    log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

    memory_task = None
    cultural_knowledge_task = None
    learning_task = None
    agent_session: Optional[AgentSession] = None

    # Set up retry logic
    num_attempts = agent.retries + 1
    try:
        for attempt in range(num_attempts):
            if attempt > 0:
                log_debug(f"Retrying Agent run {run_response.run_id}. Attempt {attempt + 1} of {num_attempts}...")

            # Bind run_messages early — pre-hook iteration checks cancellation
            # before run_messages is built, and the cancellation handler reads it.
            run_messages: Optional[RunMessages] = None
            try:
                # 1. Read or create session. Reuse pre-read session on first attempt.
                if attempt == 0 and pre_session is not None:
                    agent_session = pre_session
                else:
                    agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)

                # Start the Run by yielding a RunStarted event
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_started_event(run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # 2. Update metadata and session state
                if not (attempt == 0 and pre_session is not None):
                    update_metadata(agent, session=agent_session)

                # Initialize session state. Get it from DB if relevant.
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_context.run_id,
                )

                # 3. Resolve dependencies
                if run_context.dependencies is not None:
                    await aresolve_run_dependencies(agent, run_context=run_context)

                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 4. Execute pre-hooks
                run_input = cast(RunInput, run_response.input)
                agent.model = cast(Model, agent.model)
                if agent.pre_hooks is not None:
                    pre_hook_iterator = aexecute_pre_hooks(
                        agent,
                        hooks=agent.pre_hooks,  # type: ignore
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
                        if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event

                # 5. Determine tools for model
                agent.model = cast(Model, agent.model)
                processed_tools = await agent.aget_tools(
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    user_id=user_id,
                )

                _tools = determine_tools_for_model(
                    agent,
                    model=agent.model,
                    processed_tools=processed_tools,
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    async_mode=True,
                )

                # 6. Prepare run messages
                run_messages = await aget_run_messages(
                    agent,
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
                from agno.agent import _managers

                memory_task = await _managers.astart_memory_task(
                    agent,
                    run_messages=run_messages,
                    user_id=user_id,
                    existing_task=memory_task,
                )

                # Start learning extraction as a background task
                learning_task = await _managers.astart_learning_task(
                    agent,
                    run_messages=run_messages,
                    session=agent_session,
                    user_id=user_id,
                    existing_task=learning_task,
                )

                # Start cultural knowledge creation as a background task (runs concurrently with the main execution)
                cultural_knowledge_task = await _managers.astart_cultural_knowledge_task(
                    agent,
                    run_messages=run_messages,
                    existing_task=cultural_knowledge_task,
                )

                # 8. Reason about the task if reasoning is enabled
                async for item in ahandle_reasoning_stream(
                    agent,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                    stream_events=stream_events,
                ):
                    if not isinstance(item, _CANCEL_BYPASS_EVENT_TYPES):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                    yield item

                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 9. Generate a response from the Model
                if agent.output_model is None:
                    async for event in ahandle_model_response_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        session_state=run_context.session_state,
                        run_context=run_context,
                    ):
                        if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event
                else:
                    from agno.run.agent import (
                        IntermediateRunContentEvent,
                        RunContentEvent,
                    )  # type: ignore

                    async for event in ahandle_model_response_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        session_state=run_context.session_state,
                        run_context=run_context,
                    ):
                        if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
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
                    async for event in agenerate_response_with_output_model_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        stream_events=stream_events,
                    ):
                        if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event

                # Check for cancellation after model processing
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 10. Parse response with parser model if provided
                async for event in aparse_response_with_parser_model_stream(
                    agent,
                    session=agent_session,
                    run_response=run_response,
                    stream_events=stream_events,
                    run_context=run_context,
                ):
                    if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                    yield event  # type: ignore

                # 10b. Generate follow-up suggestions if enabled
                async for event in agenerate_followups_stream(
                    agent,
                    run_response=run_response,
                    stream_events=stream_events,
                ):
                    if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                    yield event  # type: ignore

                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_content_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # Break out of the run function if a tool call is paused
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    async for item in await_for_thread_tasks_stream(
                        memory_task=memory_task,
                        cultural_knowledge_task=cultural_knowledge_task,
                        learning_task=learning_task,
                        stream_events=stream_events,
                        run_response=run_response,
                        events_to_skip=agent.events_to_skip,
                        store_events=agent.store_events,
                        get_memories_callback=lambda: agent.aget_user_memories(user_id=user_id),
                    ):
                        yield item
                    merge_background_metrics(
                        run_response.metrics,
                        collect_background_metrics(memory_task, cultural_knowledge_task, learning_task),
                    )

                    async for item in ahandle_agent_run_paused_stream(  # type: ignore[assignment]
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                        yield_run_output=yield_run_output or False,
                    ):
                        yield item
                    return

                # Execute post-hooks (after output is generated but before response is returned)
                if agent.post_hooks is not None:
                    async for event in aexecute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
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
                    events_to_skip=agent.events_to_skip,
                    store_events=agent.store_events,
                    get_memories_callback=lambda: agent.aget_user_memories(user_id=user_id),
                ):
                    yield item
                merge_background_metrics(
                    run_response.metrics,
                    collect_background_metrics(memory_task, cultural_knowledge_task, learning_task),
                )

                # 12. Create session summary
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    agent_session.upsert_run(run=run_response)

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )
                    try:
                        await agent.session_summary_manager.acreate_session_summary(
                            session=agent_session, run_metrics=run_response.metrics
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_completed_event(
                                from_run_response=run_response, session_summary=agent_session.summary
                            ),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )

                # Update run_response.session_state before creating RunCompletedEvent
                # This ensures the event has the final state after all tool modifications
                if agent_session.session_data is not None and "session_state" in agent_session.session_data:
                    run_response.session_state = agent_session.session_data["session_state"]

                # Create the run completed event
                completed_event = handle_event(
                    create_run_completed_event(from_run_response=run_response),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 13. Cleanup and store the run response and session
                await acleanup_and_store(
                    agent,
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
                await alog_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                # Break out of the run function
                break

            except RunCancelledException as e:
                run_response = _handle_run_cancellation(run_response, e, run_messages)
                cancelled_event, completed_event = _build_cancel_terminal_events(
                    agent,
                    run_response,
                    error=e,
                    run_context=run_context,
                )
                try:
                    if agent_session is not None:
                        await acleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break

            except (InputCheckError, OutputCheckError) as e:
                # Handle exceptions during async streaming
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
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
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # Yield the error event
                yield run_error
                break

            except (KeyboardInterrupt, asyncio.CancelledError, GeneratorExit) as cancel_exc:
                run_response = _handle_run_cancellation(run_response, KeyboardInterrupt(), run_messages)
                # Build terminal events first so they are stored on the run
                cancelled_event, completed_event = _build_cancel_terminal_events(
                    agent,
                    run_response,
                    error=KeyboardInterrupt(),
                    run_context=run_context,
                )
                if agent_session is not None:
                    if isinstance(cancel_exc, (asyncio.CancelledError, GeneratorExit)):
                        # Client disconnect: persist on a detached task so the cancel scope can't abort the write.
                        # GeneratorExit is raised when the SSE StreamingResponse closes the generator on disconnect.
                        _persist_cancelled_run_in_background(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                    else:
                        # Ctrl-C under asyncio.run: persist inline; a detached task would not run before the loop exits
                        await acleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
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
                # Check if this is the last attempt
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    await asyncio.sleep(delay)
                    continue

                # Handle exceptions during async streaming
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
                # Add error event to list of events
                run_error = create_run_error_event(run_response, error=str(e))
                run_response.events = add_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # Yield the error event
                yield run_error
    finally:
        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always disconnect MCP tools
        await disconnect_mcp_tools(agent)

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


def arun_dispatch(  # type: ignore
    agent: Agent,
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
    background: bool = False,
    **kwargs: Any,
) -> Union[RunOutput, AsyncIterator[RunOutputEvent]]:
    """Async Run the Agent and return the response."""

    # Set the id for the run and register it immediately for cancellation tracking
    from agno.agent._response import get_response_format

    run_id = run_id or str(uuid4())

    if (add_history_to_context or agent.add_history_to_context) and not agent.db and not agent.team_id:
        log_warning(
            "add_history_to_context is True, but no database has been assigned to the agent. History will not be added to the context."
        )

    background_tasks = kwargs.pop("background_tasks", None)
    if background_tasks is not None:
        from fastapi import BackgroundTasks

        background_tasks: BackgroundTasks = background_tasks  # type: ignore

    # 2. Validate input against input_schema if provided
    validated_input = validate_input(input, agent.input_schema)

    # Normalise hooks & guardails
    if not agent._hooks_normalised:
        if agent.pre_hooks:
            agent.pre_hooks = normalize_pre_hooks(agent.pre_hooks, async_mode=True)  # type: ignore
        if agent.post_hooks:
            agent.post_hooks = normalize_post_hooks(agent.post_hooks, async_mode=True)  # type: ignore
        agent._hooks_normalised = True

    # Initialize session
    session_id, user_id = initialize_session(agent, session_id=session_id, user_id=user_id)

    # Initialize the Agent
    agent.initialize_agent(debug_mode=debug_mode)

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

    # Read existing session and update metadata BEFORE resolving run options,
    # so that session-stored metadata is visible to resolve_run_options.
    # Note: arun_dispatch is NOT async, so we can only pre-read with a sync DB.
    # For async DB, _arun/_arun_stream will handle the session read themselves.
    from agno.agent._init import has_async_db
    from agno.agent._storage import update_metadata

    _pre_session: Optional[AgentSession] = None
    if not has_async_db(agent):
        from agno.agent._storage import read_or_create_session

        _pre_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)
        update_metadata(agent, session=_pre_session)

    # Resolve all run options centrally
    opts = resolve_run_options(
        agent,
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

    agent.model = cast(Model, agent.model)

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
        dependencies_provided=dependencies is not None,
        knowledge_filters_provided=knowledge_filters is not None,
        metadata_provided=metadata is not None,
    )

    # Prepare arguments for the model (must be after run_context is fully initialized)
    response_format = get_response_format(agent, run_context=run_context) if agent.parser_model is None else None

    # Create a new run_response for this attempt
    run_response = RunOutput(
        run_id=run_id,
        session_id=session_id,
        agent_id=agent.id,
        user_id=user_id,
        agent_name=agent.name,
        metadata=run_context.metadata,
        session_state=run_context.session_state,
        input=run_input,
    )

    run_response.model = agent.model.id if agent.model is not None else None
    run_response.model_provider = agent.model.provider if agent.model is not None else None

    # Start the run metrics timer, to calculate the run duration
    run_response.metrics = RunMetrics()
    run_response.metrics.start_timer()

    # Background execution
    if background:
        if not agent.db:
            raise ValueError(
                "Background execution requires a database to be configured on the agent for run persistence."
            )
        if opts.stream:
            # background=True, stream=True: run in background task, stream events via queue
            return _arun_background_stream(  # type: ignore[return-value]
                agent,
                run_response=run_response,
                run_context=run_context,
                user_id=user_id,
                response_format=response_format,
                stream_events=opts.stream_events,
                yield_run_output=opts.yield_run_output,
                session_id=session_id,
                add_history_to_context=opts.add_history_to_context,
                add_dependencies_to_context=opts.add_dependencies_to_context,
                add_session_state_to_context=opts.add_session_state_to_context,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )
        return _arun_background(  # type: ignore[return-value]
            agent,
            run_response=run_response,
            run_context=run_context,
            user_id=user_id,
            response_format=response_format,
            session_id=session_id,
            add_history_to_context=opts.add_history_to_context,
            add_dependencies_to_context=opts.add_dependencies_to_context,
            add_session_state_to_context=opts.add_session_state_to_context,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )

    # Pass the new run_response to _arun
    if opts.stream:
        return _arun_stream(  # type: ignore
            agent,
            run_response=run_response,
            run_context=run_context,
            user_id=user_id,
            response_format=response_format,
            stream_events=opts.stream_events,
            yield_run_output=opts.yield_run_output,
            session_id=session_id,
            add_history_to_context=opts.add_history_to_context,
            add_dependencies_to_context=opts.add_dependencies_to_context,
            add_session_state_to_context=opts.add_session_state_to_context,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            pre_session=_pre_session,
            **kwargs,
        )  # type: ignore[assignment]
    else:
        return _arun(  # type: ignore
            agent,
            run_response=run_response,
            run_context=run_context,
            user_id=user_id,
            response_format=response_format,
            session_id=session_id,
            add_history_to_context=opts.add_history_to_context,
            add_dependencies_to_context=opts.add_dependencies_to_context,
            add_session_state_to_context=opts.add_session_state_to_context,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            pre_session=_pre_session,
            **kwargs,
        )


def _truncate_run_to_checkpoint(run_response: RunOutput, message_index: int) -> None:
    """Truncate ``run_response.messages`` to length ``message_index`` and prune
    tools / requirements that referenced removed messages.

    Used by the unified /continue dispatch (ADR-003) to support time-travel —
    resuming a run from an earlier point in its conversation. The retained
    state is a strict prefix of the original.

    A tool is kept iff its ``tool_call_id`` is still referenced by either:
    - a remaining tool-role message's ``tool_call_id`` field, or
    - a remaining assistant message's ``tool_calls`` list.

    A requirement is kept iff its underlying tool execution survives. The
    checkpoint marker is updated to ``message_index``.

    No-op when ``message_index >= len(messages)`` or ``message_index < 0``.
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

    # Truncate messages
    run_response.messages = run_response.messages[:message_index]

    # Collect tool_call_ids referenced by the surviving messages
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

    # Filter tools and requirements to those still referenced
    if run_response.tools:
        run_response.tools = [t for t in run_response.tools if t.tool_call_id in valid_tool_call_ids]
    if run_response.requirements:
        run_response.requirements = [
            req
            for req in run_response.requirements
            if req.tool_execution and req.tool_execution.tool_call_id in valid_tool_call_ids
        ]

    # Update the checkpoint marker to the new truncation index
    run_response.last_checkpoint_at_message_index = message_index


def _fork_run(run_response: RunOutput, message_index: int) -> RunOutput:
    """Deep-clone ``run_response`` with a new ``run_id`` and set fork metadata,
    then truncate the clone to ``message_index``.

    The original ``run_response`` is untouched. The returned RunOutput has:
    - a fresh UUID4 ``run_id``
    - ``forked_from_run_id`` set to the original's ``run_id``
    - ``forked_from_message_index`` set to ``message_index``
    - messages / tools / requirements truncated per
      :func:`_truncate_run_to_checkpoint`
    - a fresh ``RunMetrics`` and ``created_at`` (the fork is a new run; it
      should not inherit the parent's timings, token counts, or birthtime).

    Same ``session_id`` — forks are sibling runs within the same session.
    """
    import copy
    from time import time as _time

    from agno.utils.message import safe_truncation_index

    # Snap to a pair-safe boundary so fork metadata matches the truncation that
    # _truncate_run_to_checkpoint will actually perform.
    message_index = safe_truncation_index(run_response.messages or [], message_index)

    forked = copy.deepcopy(run_response)
    forked.run_id = str(uuid4())
    forked.forked_from_run_id = run_response.run_id
    forked.forked_from_message_index = message_index
    # Reset lineage-irrelevant accumulators so the fork reports its own work,
    # not the parent's. Without this, token counts and durations double-count.
    forked.metrics = RunMetrics()
    forked.created_at = int(_time())
    _truncate_run_to_checkpoint(forked, message_index)
    return forked


def _apply_continue_modifiers(
    run_response: RunOutput,
    fork: bool,
    message_index: Optional[int],
) -> RunOutput:
    """Apply ``fork`` and/or ``message_index`` to a loaded run_response.

    Returns the resulting RunOutput — the same instance when only truncating,
    a new instance when forking. Called from continue_run_dispatch /
    acontinue_run_dispatch after a run is loaded and before validation, so the
    rest of the dispatch operates on the modified state.
    """
    if fork:
        idx = message_index if message_index is not None else len(run_response.messages or [])
        return _fork_run(run_response, idx)
    if message_index is not None:
        _truncate_run_to_checkpoint(run_response, message_index)
    return run_response


def _find_regenerate_checkpoint(run_response: RunOutput) -> int:
    """Compute the message index at which to truncate when regenerating.

    Regenerate semantics: drop ONLY the trailing
    assistant messages that have no tool_calls — i.e. the final response
    turn. Intermediate assistant messages with tool_calls and the tool
    results they produced are preserved, so the model regenerates a fresh
    summary of the same tool outputs without re-invoking the tools.

    Walks backwards: pops trailing ``assistant`` messages without
    ``tool_calls``. Stops at the first message that isn't one. Returns
    the message count to keep (length-after-truncation).

    Raises ``ValueError`` if every message is a no-tool-call assistant
    message (nothing to regenerate from).
    """
    messages = run_response.messages or []
    i = len(messages)
    while i > 0 and messages[i - 1].role == "assistant" and not messages[i - 1].tool_calls:
        i -= 1
    if i == 0:
        raise ValueError("Cannot regenerate: run has no non-assistant messages to regenerate from.")
    return i


def _find_last_user_message_index(run_response: RunOutput) -> int:
    """For ``continue_from="last_user"``: walk backwards to the last user
    message and return its index + 1 (the message count to keep).
    """
    messages = run_response.messages or []
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            return i + 1
    raise ValueError("Cannot resolve `continue_from='last_user'`: run has no user messages.")


def _resolve_continue_from(
    run_response: RunOutput,
    *,
    continue_from: Union[int, Literal["end", "last_user"]],
    regenerate: bool = False,
) -> int:
    """Resolve the public continuation selector into a message boundary index.

    - ``"end"`` keeps the whole current transcript
    - ``"last_user"`` keeps through the last user message (drops trailing
      assistant/tool messages, including intermediate tool exchanges)
    - ``int`` keeps ``messages[:int]``

    When ``regenerate=True``, the boundary is computed by
    :func:`_find_regenerate_checkpoint` — which keeps intermediate
    tool_call exchanges so the model regenerates a fresh summary of the
    same tool results. That semantics differs from ``"last_user"``;
    do not conflate them.
    """
    if regenerate:
        if continue_from in ("end", "last_user"):
            return _find_regenerate_checkpoint(run_response)
        raise ValueError("`regenerate=True` derives the continuation boundary automatically.")

    messages = run_response.messages or []
    if isinstance(continue_from, int):
        return continue_from
    if continue_from == "end":
        return len(messages)
    if continue_from == "last_user":
        return _find_last_user_message_index(run_response)

    raise ValueError("`continue_from` must be an integer message index, 'end', or 'last_user'.")


def _normalize_regenerate_params(
    run_response: Optional[RunOutput],
    *,
    regenerate: bool,
    replace_original: Optional[bool],
    additional_instructions: Optional[str],
    fork: bool,
    continue_index: Optional[int],
    input: Optional[str],
) -> tuple[bool, Optional[int], Optional[str]]:
    """Normalize regenerate-sugar params to canonical (fork, continue_index, input).

    Sugar semantics:
    - ``regenerate=True`` → the continuation index is auto-computed to drop the
      final assistant response (and resume from just after the last user
      message). Pair with ``additional_instructions`` to steer the new output.
    - ``replace_original`` → controls history visibility of the source run only;
      the source is ALWAYS retained in storage (``regenerate`` always forks).
      Defaults to True: the source is marked ``REGENERATED`` and hidden from
      history so the new run replaces it. Pass False to keep both the original
      and the regenerated run visible side by side. Only meaningful with
      ``regenerate=True``.
    - ``additional_instructions`` → ``input``. Reserved name for the regenerate
      flow.

    Conflicts (raise ``ValueError``):
    - ``regenerate=True`` with ``fork`` explicitly set (the sugar derives it).
    - ``additional_instructions`` and ``input`` both set.
    - ``replace_original`` set (True or False) without ``regenerate=True``.

    Returns: (resolved_fork, resolved_continue_index, resolved_input).
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
    # ``regenerate`` ALWAYS forks. The 1-run-1-loop invariant demands a new
    # run_id whenever the source run's loop has already completed —
    # ``replace_original`` controls a separate concern (whether the source
    # is marked REGENERATED and hidden from history), not whether to fork.
    return (True, _find_regenerate_checkpoint(run_response), resolved_input)


def _maybe_append_input_message(run_response: RunOutput, new_input: Optional[str], agent: Agent) -> None:
    """If ``new_input`` is a non-empty string, append it as a new user-role message
    to ``run_response.messages``.

    Used by the unified /continue dispatch (ADR-003) when the caller wants to
    extend a persisted run with an additional turn — e.g. continuing a COMPLETED
    run with a follow-up question, or providing context after a mid-flight
    resume. Mutates ``run_response.messages`` in place; the appended message
    flows through ``get_continue_run_messages`` into the model loop.
    """
    if not new_input:
        return
    new_message = Message(role=agent.user_message_role, content=new_input)
    if run_response.messages is None:
        run_response.messages = [new_message]
    else:
        run_response.messages.append(new_message)


def _sync_requirements_with_tools(run_response: RunOutput, updated_tools: List[Any]) -> None:
    """Sync requirements to reference the new tool objects so is_resolved()
    checks operate on the same instances that handle_tool_call_updates modifies.
    """
    if run_response.requirements:
        updated_tools_map = {t.tool_call_id: t for t in updated_tools if t.tool_call_id}

        for req in run_response.requirements:
            if req.tool_execution and req.tool_execution.tool_call_id in updated_tools_map:
                req.tool_execution = updated_tools_map[req.tool_execution.tool_call_id]


def continue_run_dispatch(
    agent: Agent,
    run_response: Optional[RunOutput] = None,
    *,
    run_id: Optional[str] = None,  # type: ignore
    updated_tools: Optional[List[ToolExecution]] = None,
    requirements: Optional[List[RunRequirement]] = None,
    input: Optional[str] = None,
    continue_from: Union[int, Literal["end", "last_user"]] = "end",
    fork: bool = False,
    regenerate: bool = False,
    replace_original: Optional[bool] = None,
    additional_instructions: Optional[str] = None,
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
        input: Optional new user-message text to append before resuming. Use for
            continuing a COMPLETED run with a follow-up, or adding context to an
            RUNNING/ERROR resume.
        continue_from: Continuation boundary. Accepts "end", "last_user",
            or a numeric message index.
        fork: When True, clone the run with a new ``run_id`` before truncating /
            resuming. The original run is untouched; the clone becomes a sibling
            within the same session, with ``forked_from_run_id`` set.
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
    from agno.agent._init import has_async_db, set_default_model
    from agno.agent._messages import get_continue_run_messages
    from agno.agent._response import get_response_format
    from agno.agent._storage import load_session_state, read_or_create_session, update_metadata
    from agno.agent._tools import determine_tools_for_model

    if run_response is None and run_id is None:
        raise ValueError("Either run_response or run_id must be provided.")

    if run_response is None and (run_id is not None and (session_id is None and agent.session_id is None)):
        raise ValueError("Session ID is required to continue a run from a run_id.")

    if has_async_db(agent):
        raise Exception("continue_run() is not supported with an async DB. Please use acontinue_run() instead.")

    background_tasks = kwargs.pop("background_tasks", None)
    if background_tasks is not None:
        from fastapi import BackgroundTasks

        background_tasks: BackgroundTasks = background_tasks  # type: ignore

    session_id = run_response.session_id if run_response else session_id
    run_id: str = run_response.run_id if run_response else run_id  # type: ignore

    session_id, user_id = initialize_session(
        agent,
        session_id=session_id,
        user_id=user_id,
    )
    # Initialize the Agent
    agent.initialize_agent(debug_mode=debug_mode)

    # Read existing session from storage
    agent_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)
    update_metadata(agent, session=agent_session)

    # Initialize session state. Get it from DB if relevant.
    session_state = load_session_state(agent, session=agent_session, session_state={})

    # Resolve all run options centrally
    opts = resolve_run_options(
        agent,
        stream=stream,
        stream_events=stream_events,
        yield_run_output=yield_run_output,
        dependencies=dependencies,
        knowledge_filters=knowledge_filters,
        metadata=metadata,
    )

    # Initialize run context
    run_context = run_context or RunContext(
        run_id=run_id,  # type: ignore
        session_id=session_id,
        user_id=user_id,
        session_state=session_state,
        dependencies=opts.dependencies,
        knowledge_filters=opts.knowledge_filters,
        metadata=opts.metadata,
    )
    # Apply options with precedence: explicit args > existing run_context > resolved defaults.
    opts.apply_to_context(
        run_context,
        dependencies_provided=dependencies is not None,
        knowledge_filters_provided=knowledge_filters is not None,
        metadata_provided=metadata is not None,
    )

    # Resolve dependencies
    if run_context.dependencies is not None:
        resolve_run_dependencies(agent, run_context=run_context)

    # Run can be continued from previous run response or from passed run_response context
    if run_response is not None:
        if run_response.status == RunStatus.cancelled:
            raise ValueError(f"Cannot continue run {run_response.run_id}: run is cancelled")
        # The run is continued from a provided run_response. This contains the updated tools.
        continue_index: Optional[int] = _resolve_continue_from(
            run_response,
            continue_from=continue_from,
            regenerate=regenerate,
        )
        # Normalize regenerate-sugar after the run is loaded (regenerate=True
        # needs it to compute the continuation boundary).
        fork, continue_index, input = _normalize_regenerate_params(
            run_response,
            regenerate=regenerate,
            replace_original=replace_original,
            additional_instructions=additional_instructions,
            fork=fork,
            continue_index=continue_index,
            input=input,
        )
        if not fork and run_response.status == RunStatus.completed:
            fork = True
        # If regenerated_from lineage applies, record it before truncating.
        original_run_id_for_lineage = run_response.run_id if regenerate else None
        run_response = _apply_continue_modifiers(run_response, fork, continue_index)
        if regenerate and original_run_id_for_lineage:
            run_response.regenerated_from = original_run_id_for_lineage
            if replace_original is not False and run_response.forked_from_run_id:
                # Mark the original run as REGENERATED so history builders skip it.
                for r in agent_session.runs or []:
                    if r.run_id == original_run_id_for_lineage:
                        r.status = RunStatus.regenerated
                        break
        input_messages = run_response.messages or []
    elif run_id is not None:
        # The run is continued from a run_id.
        runs = agent_session.runs or []
        run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
        if run_response is None:
            raise RuntimeError(f"No runs found for run ID {run_id}")
        if run_response.status == RunStatus.cancelled:
            raise ValueError(f"Cannot continue run {run_response.run_id}: run is cancelled")

        continue_index = _resolve_continue_from(
            run_response,
            continue_from=continue_from,
            regenerate=regenerate,
        )
        # Normalize regenerate-sugar.
        fork, continue_index, input = _normalize_regenerate_params(
            run_response,
            regenerate=regenerate,
            replace_original=replace_original,
            additional_instructions=additional_instructions,
            fork=fork,
            continue_index=continue_index,
            input=input,
        )
        original_run_id_for_lineage = run_response.run_id if regenerate else None

        # Auto-fork on COMPLETED: continuing a COMPLETED run must NOT reuse the
        # source run_id — that would mix two model loops into one persisted row
        # (corrupted metrics, lying timestamps, ambiguous audit trail).
        # Implicit fork preserves the "1 run = 1 model loop" invariant: the
        # source stays untouched, a sibling run takes over.
        #
        # Triggers whenever the source run is COMPLETED and no explicit
        # fork/checkpoint was passed (those already produce a new run_id).
        # RUNNING/ERROR/PAUSED runs continue in-place because their loop
        # never actually finished — there's no second loop to fork off into.
        if not fork and run_response.status == RunStatus.completed:
            fork = True

        # Apply fork/truncate before validation so the rest of the dispatch operates
        # on the modified state (time-travel + forking land before HITL checks).
        # NOTE: for fork=True, ``run_response.run_id`` becomes a new UUID. The local
        # ``run_id`` variable still points at the ORIGINAL run — used for approval
        # lookups (the fork inherits the original's resolved approval, if any).
        # ``run_response.run_id`` is what gets persisted as the new sibling run.
        run_response = _apply_continue_modifiers(run_response, fork, continue_index)
        if regenerate and original_run_id_for_lineage:
            run_response.regenerated_from = original_run_id_for_lineage
            if replace_original is not False and run_response.forked_from_run_id:
                for r in agent_session.runs or []:
                    if r.run_id == original_run_id_for_lineage:
                        r.status = RunStatus.regenerated
                        break

        input_messages = run_response.messages or []

        # If we have updated_tools, set them in the run_response
        if updated_tools is not None:
            warnings.warn(
                "The 'updated_tools' parameter is deprecated and will be removed in future versions. Use 'requirements' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            run_response.tools = updated_tools
            _sync_requirements_with_tools(run_response, updated_tools)

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
            # No tools / requirements in the body. Two cases:
            # 1. The run has unresolved HITL requirements → try admin-approval
            #    resolution; if none, the caller must provide tools/requirements.
            # 2. The run has no unresolved requirements → just resume from current
            #    state (mid-flight resume, ERROR retry, time-travel, auto-fork
            #    on COMPLETED, etc.). This is the unified /continue path
            #    (ADR-003, ADR-004).
            has_unresolved_requirements = any(not req.is_resolved() for req in (run_response.requirements or []))
            if has_unresolved_requirements:
                from agno.run.approval import check_and_apply_approval_resolution

                try:
                    # This will apply resolution_data to tools if approval is resolved.
                    # Approval lookup still uses the ORIGINAL run_id, even when we
                    # auto-forked — the fork inherits the original's resolved approval.
                    check_and_apply_approval_resolution(agent.db, run_id, run_response)
                except RuntimeError:
                    # No resolved approval found — caller must provide requirements/tools
                    raise ValueError(
                        "Run has unresolved HITL requirements. Provide the `requirements` "
                        "parameter (or resolve an admin approval first)."
                    )
            # else: nothing to resolve — fall through to resume from current state
    else:
        raise ValueError("Either run_response or run_id must be provided.")

    # If the caller supplied a new user-message string (unified /continue body
    # field ``input``), append it to run_response.messages before building
    # run_messages. The new message flows through into the model loop.
    if input:
        _maybe_append_input_message(run_response, input, agent)
        input_messages = run_response.messages or []

    # Prepare arguments for the model
    set_default_model(agent)
    response_format = get_response_format(agent, run_context=run_context) if agent.parser_model is None else None
    agent.model = cast(Model, agent.model)

    processed_tools = agent.get_tools(
        run_response=run_response,
        run_context=run_context,
        session=agent_session,
        user_id=user_id,
    )

    _tools = determine_tools_for_model(
        agent,
        model=agent.model,
        processed_tools=processed_tools,
        run_response=run_response,
        run_context=run_context,
        session=agent_session,
    )

    run_response = cast(RunOutput, run_response)

    log_debug(f"Agent Run Start: {run_response.run_id}", center=True)

    # Prepare run messages
    run_messages = get_continue_run_messages(
        agent,
        input=input_messages,
        session=agent_session,
        add_history_to_context=agent.add_history_to_context,
        run_context=run_context,
    )

    # Reset the run state
    run_response.status = RunStatus.running

    if opts.stream:
        response_iterator = _continue_run_stream(
            agent,
            run_response=run_response,
            run_messages=run_messages,
            run_context=run_context,
            tools=_tools,
            user_id=user_id,
            session=agent_session,
            response_format=response_format,
            stream_events=opts.stream_events,
            yield_run_output=opts.yield_run_output,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )
        return response_iterator
    else:
        response = _continue_run(
            agent,
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
    agent: Agent,
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
    from agno.agent._hooks import execute_post_hooks
    from agno.agent._init import disconnect_connectable_tools
    from agno.agent._response import (
        convert_response_to_structured_format,
        generate_followups,
        generate_response_with_output_model,
        parse_response_with_parser_model,
        update_run_response,
    )
    from agno.agent._telemetry import log_agent_telemetry
    from agno.agent._tools import handle_tool_call_updates

    register_run(run_response.run_id)  # type: ignore

    agent.model = cast(Model, agent.model)

    # 1. Handle the updated tools
    handle_tool_call_updates(agent, run_response=run_response, run_messages=run_messages, tools=tools)

    try:
        num_attempts = agent.retries + 1
        for attempt in range(num_attempts):
            try:
                # Check for cancellation before model call
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # 2. Generate a response from the Model (includes running function calls)
                agent.model = cast(Model, agent.model)
                model_response: ModelResponse = call_model_with_fallback(
                    agent.model,
                    agent.fallback_config,
                    messages=run_messages.messages,
                    response_format=response_format,
                    tools=tools,
                    tool_choice=agent.tool_choice,
                    tool_call_limit=agent.tool_call_limit,
                    run_response=run_response,
                    send_media_to_model=agent.send_media_to_model,
                    compression_manager=agent.compression_manager if agent.compress_tool_results else None,
                    after_tool_results=build_after_tool_results_callback(
                        agent,
                        run_response=run_response,
                        session=session,
                        run_messages=run_messages,
                        run_context=run_context,
                    ),
                )

                # Check for cancellation after model processing
                raise_if_cancelled(run_response.run_id)  # type: ignore

                # If an output model is provided, generate output using the output model
                generate_response_with_output_model(agent, model_response, run_messages, run_response=run_response)

                # If a parser model is provided, structure the response separately
                parse_response_with_parser_model(
                    agent, model_response, run_messages, run_context=run_context, run_response=run_response
                )

                # 3. Update the RunOutput with the model response
                update_run_response(
                    agent,
                    model_response=model_response,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                )

                # We should break out of the run function
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    return handle_agent_run_paused(
                        agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )

                # 4. Convert the response to the structured format if needed
                convert_response_to_structured_format(agent, run_response, run_context=run_context)

                # 4b. Generate follow-up suggestions if enabled
                generate_followups(agent, run_response=run_response)

                # 5. Store media in run output for the caller
                store_media_util(run_response, model_response)

                # 6. Execute post-hooks
                if agent.post_hooks is not None:
                    post_hook_iterator = execute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
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
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    session.upsert_run(run=run_response)

                    try:
                        agent.session_summary_manager.create_session_summary(
                            session=session, run_metrics=run_response.metrics
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 8. Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )

                # Log Agent Telemetry
                log_agent_telemetry(agent, session_id=session.session_id, run_id=run_response.run_id)

                return run_response
            except RunCancelledException as e:
                run_response = _handle_run_cancellation(run_response, e, run_messages)
                try:
                    cleanup_and_store(
                        agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                return run_response
            except (InputCheckError, OutputCheckError) as e:
                run_response = cast(RunOutput, run_response)
                # Handle exceptions during streaming
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )

                return run_response
            except KeyboardInterrupt:
                run_response = _handle_run_cancellation(run_response, KeyboardInterrupt(), run_messages)
                try:
                    cleanup_and_store(
                        agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                return run_response

            except Exception as e:
                run_response = cast(RunOutput, run_response)
                # Check if this is the last attempt
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    time.sleep(delay)
                    continue
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )

                return run_response
    finally:
        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always clean up the run tracking
        cleanup_run(run_response.run_id)  # type: ignore
    return run_response


def _continue_run_stream(
    agent: Agent,
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

    from agno.agent._hooks import execute_post_hooks
    from agno.agent._init import disconnect_connectable_tools
    from agno.agent._response import (
        generate_followups_stream,
        handle_model_response_stream,
        parse_response_with_parser_model_stream,
    )
    from agno.agent._telemetry import log_agent_telemetry
    from agno.agent._tools import handle_tool_call_updates_stream

    register_run(run_response.run_id)  # type: ignore

    # Set up retry logic
    num_attempts = agent.retries + 1
    try:
        for attempt in range(num_attempts):
            try:
                # 1. Resolve dependencies
                if run_context.dependencies is not None:
                    resolve_run_dependencies(agent, run_context=run_context)

                # Start the Run by yielding a RunContinued event
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_continued_event(run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # 2. Handle the updated tools
                for event in handle_tool_call_updates_stream(
                    agent,
                    run_response=run_response,
                    run_messages=run_messages,
                    tools=tools,
                    stream_events=stream_events,
                ):
                    if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                        raise_if_cancelled(run_response.run_id)  # type: ignore
                    yield event

                # 3. Process model response
                for event in handle_model_response_stream(
                    agent,
                    session=session,
                    run_response=run_response,
                    run_messages=run_messages,
                    tools=tools,
                    response_format=response_format,
                    stream_events=stream_events,
                    session_state=run_context.session_state,
                    run_context=run_context,
                ):
                    if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                        raise_if_cancelled(run_response.run_id)  # type: ignore
                    yield event

                # Parse response with parser model if provided
                for event in parse_response_with_parser_model_stream(
                    agent,  # type: ignore
                    session=session,
                    run_response=run_response,
                    stream_events=stream_events,
                    run_context=run_context,
                ):
                    if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                        raise_if_cancelled(run_response.run_id)  # type: ignore
                    yield event

                # Generate follow-up suggestions if enabled
                for event in generate_followups_stream(
                    agent,  # type: ignore
                    run_response=run_response,
                    stream_events=stream_events,
                ):
                    if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                        raise_if_cancelled(run_response.run_id)  # type: ignore
                    yield event

                # Yield RunContentCompletedEvent
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_content_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # We should break out of the run function
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    yield from handle_agent_run_paused_stream(
                        agent,
                        run_response=run_response,
                        session=session,
                        run_context=run_context,
                        user_id=user_id,
                        yield_run_output=yield_run_output or False,
                    )
                    return

                # Execute post-hooks
                if agent.post_hooks is not None:
                    yield from execute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
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
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    session.upsert_run(run=run_response)

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )
                    try:
                        agent.session_summary_manager.create_session_summary(
                            session=session, run_metrics=run_response.metrics
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_completed_event(
                                from_run_response=run_response, session_summary=session.summary
                            ),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )

                # Update run_response.session_state before creating RunCompletedEvent
                # This ensures the event has the final state after all tool modifications
                if session.session_data is not None and "session_state" in session.session_data:
                    run_response.session_state = session.session_data["session_state"]

                # Create the run completed event
                completed_event = handle_event(
                    create_run_completed_event(run_response),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 5. Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )

                if stream_events:
                    yield completed_event  # type: ignore

                if yield_run_output:
                    yield run_response

                # Log Agent Telemetry
                log_agent_telemetry(agent, session_id=session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                break
            except RunCancelledException as e:
                run_response = _handle_run_cancellation(run_response, e, run_messages)
                cancelled_event, completed_event = _build_cancel_terminal_events(
                    agent,
                    run_response,
                    error=e,
                    run_context=run_context,
                )
                try:
                    cleanup_and_store(
                        agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break
            except (InputCheckError, OutputCheckError) as e:
                run_response = cast(RunOutput, run_response)
                # Handle exceptions during streaming
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
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

                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )
                yield run_error
                break
            except KeyboardInterrupt:
                run_response = _handle_run_cancellation(run_response, KeyboardInterrupt(), run_messages)
                cancelled_event, completed_event = _build_cancel_terminal_events(
                    agent,
                    run_response,
                    error=KeyboardInterrupt(),
                    run_context=run_context,
                )
                try:
                    cleanup_and_store(
                        agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                    )
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break

            except Exception as e:
                run_response = cast(RunOutput, run_response)
                # Check if this is the last attempt
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    time.sleep(delay)
                    continue
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
                # Add error event to list of events
                run_error = create_run_error_event(run_response, error=str(e))
                run_response.events = add_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                cleanup_and_store(
                    agent, run_response=run_response, session=session, run_context=run_context, user_id=user_id
                )

                yield run_error
    finally:
        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always clean up the run tracking
        cleanup_run(run_response.run_id)  # type: ignore


def acontinue_run_dispatch(  # type: ignore
    agent: Agent,
    run_response: Optional[RunOutput] = None,
    *,
    run_id: Optional[str] = None,  # type: ignore
    updated_tools: Optional[List[ToolExecution]] = None,
    requirements: Optional[List[RunRequirement]] = None,
    input: Optional[str] = None,
    continue_from: Union[int, Literal["end", "last_user"]] = "end",
    fork: bool = False,
    regenerate: bool = False,
    replace_original: Optional[bool] = None,
    additional_instructions: Optional[str] = None,
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
    background: bool = False,
    **kwargs,
) -> Union[RunOutput, AsyncIterator[Union[RunOutputEvent, RunOutput]]]:
    """Continue a previous run.

    Args:
        run_response: The run response to continue.
        run_id: The run id to continue. Alternative to passing run_response.

        requirements: The requirements to continue the run. This or updated_tools is required with `run_id`.
        input: Optional new user-message text to append before resuming. Use for
            continuing a COMPLETED run with a follow-up, or adding context to an
            RUNNING/ERROR resume.
        continue_from: Continuation boundary. Accepts "end", "last_user",
            or a numeric message index.
        fork: When True, clone the run with a new ``run_id`` before truncating /
            resuming. The original run is untouched; the clone becomes a sibling
            within the same session, with ``forked_from_run_id`` set.
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
    from agno.agent._response import get_response_format

    if run_response is None and run_id is None:
        raise ValueError("Either run_response or run_id must be provided.")

    if run_response is None and (run_id is not None and (session_id is None and agent.session_id is None)):
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

    session_id = run_response.session_id if run_response else session_id
    run_id: str = run_response.run_id if run_response else run_id  # type: ignore

    session_id, user_id = initialize_session(
        agent,
        session_id=session_id,
        user_id=user_id,
    )

    # Initialize the Agent
    agent.initialize_agent(debug_mode=debug_mode)

    # Read existing session and update metadata BEFORE resolving run options,
    # so that session-stored metadata is visible to resolve_run_options.
    from agno.agent._init import has_async_db

    _session_state: Dict[str, Any] = {}
    if not has_async_db(agent):
        from agno.agent._storage import load_session_state, read_or_create_session, update_metadata

        _pre_session = read_or_create_session(agent, session_id=session_id, user_id=user_id)
        update_metadata(agent, session=_pre_session)
        _session_state = load_session_state(agent, session=_pre_session, session_state={})

    # Resolve all run options centrally
    opts = resolve_run_options(
        agent,
        stream=stream,
        stream_events=stream_events,
        yield_run_output=yield_run_output,
        dependencies=dependencies,
        knowledge_filters=knowledge_filters,
        metadata=metadata,
    )

    # Prepare arguments for the model
    agent.model = cast(Model, agent.model)

    # Initialize run context before computing response_format (needs run_context)
    run_context = run_context or RunContext(
        run_id=run_id,  # type: ignore
        session_id=session_id,
        user_id=user_id,
        session_state=_session_state,
        dependencies=opts.dependencies,
        knowledge_filters=opts.knowledge_filters,
        metadata=opts.metadata,
    )
    # Apply options with precedence: explicit args > existing run_context > resolved defaults.
    opts.apply_to_context(
        run_context,
        dependencies_provided=dependencies is not None,
        knowledge_filters_provided=knowledge_filters is not None,
        metadata_provided=metadata is not None,
    )

    response_format = get_response_format(agent, run_context=run_context) if agent.parser_model is None else None

    if background:
        if not agent.db:
            raise ValueError(
                "Background execution requires a database to be configured on the agent for run persistence."
            )
        if opts.stream:
            return _acontinue_run_background_stream(  # type: ignore[return-value]
                agent,
                run_response=run_response,
                run_context=run_context,
                updated_tools=updated_tools,
                requirements=requirements,
                input=input,
                continue_from=continue_from,
                fork=fork,
                regenerate=regenerate,
                replace_original=replace_original,
                additional_instructions=additional_instructions,
                run_id=run_id,
                user_id=user_id,
                session_id=session_id,
                response_format=response_format,
                stream_events=opts.stream_events,
                yield_run_output=opts.yield_run_output,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            )

    if opts.stream:
        return _acontinue_run_stream(
            agent,
            run_response=run_response,
            run_context=run_context,
            updated_tools=updated_tools,
            requirements=requirements,
            input=input,
            continue_from=continue_from,
            fork=fork,
            regenerate=regenerate,
            replace_original=replace_original,
            additional_instructions=additional_instructions,
            run_id=run_id,
            user_id=user_id,
            session_id=session_id,
            response_format=response_format,
            stream_events=opts.stream_events,
            yield_run_output=opts.yield_run_output,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )
    else:
        return _acontinue_run(  # type: ignore
            agent,
            session_id=session_id,
            run_response=run_response,
            run_context=run_context,
            updated_tools=updated_tools,
            requirements=requirements,
            input=input,
            continue_from=continue_from,
            fork=fork,
            regenerate=regenerate,
            replace_original=replace_original,
            additional_instructions=additional_instructions,
            run_id=run_id,
            user_id=user_id,
            response_format=response_format,
            debug_mode=debug_mode,
            background_tasks=background_tasks,
            **kwargs,
        )


async def _acontinue_run_background_stream(
    agent: Agent,
    session_id: str,
    run_context: RunContext,
    run_response: Optional[RunOutput] = None,
    updated_tools: Optional[List[ToolExecution]] = None,
    requirements: Optional[List[RunRequirement]] = None,
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
    yield_run_output: Optional[bool] = None,
    debug_mode: Optional[bool] = None,
    background_tasks: Optional[Any] = None,
    **kwargs: Any,
) -> AsyncIterator[str]:
    """Background streaming continue-run that survives client disconnections.

    Same pattern as _arun_background_stream but delegates to _acontinue_run_stream
    instead of _arun_stream. Used for HITL scenarios where a paused run resumes
    and the client needs reconnection support.

    1. Persists RUNNING status in DB
    2. Spawns a detached asyncio.Task that runs _acontinue_run_stream
    3. Buffers events (via event_buffer) and publishes to SSE subscribers
    4. Yields SSE-formatted strings via an asyncio.Queue
    """
    from agno.agent._session import asave_session
    from agno.agent._storage import aread_or_create_session, update_metadata

    _run_id = run_id or (run_response.run_id if run_response else None)
    if not _run_id:
        raise ValueError("run_id is required for background streaming")

    # 1. Persist RUNNING status so the run is visible in the DB immediately
    agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)
    update_metadata(agent, session=agent_session)

    # Update the run status to RUNNING in the session
    if run_response:
        run_response.status = RunStatus.running
        agent_session.upsert_run(run=run_response)
    await asave_session(agent, session=agent_session)

    log_info(f"Background continue-run stream {_run_id} persisted with RUNNING status")

    # 2. Create queue for forwarding SSE strings to the caller
    sse_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    # 3. Spawn detached background task
    async def _background_producer() -> None:
        from agno.os.managers import event_buffer, sse_subscriber_manager
        from agno.os.utils import format_sse_event_with_index

        try:
            async for event in _acontinue_run_stream(
                agent,
                run_response=run_response,
                run_context=run_context,
                updated_tools=updated_tools,
                requirements=requirements,
                input=input,
                continue_from=continue_from,
                fork=fork,
                regenerate=regenerate,
                replace_original=replace_original,
                additional_instructions=additional_instructions,
                run_id=run_id,
                user_id=user_id,
                session_id=session_id,
                response_format=response_format,
                stream_events=stream_events,
                yield_run_output=yield_run_output or False,
                debug_mode=debug_mode,
                background_tasks=background_tasks,
                **kwargs,
            ):
                if isinstance(event, RunOutput):
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
                if run_response:
                    run_response.status = RunStatus.error
                    agent_session.upsert_run(run=run_response)
                    await asave_session(agent, session=agent_session)
            except Exception:
                log_error(f"Failed to persist error state for background continue-run stream {_run_id}", exc_info=True)

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


async def _acontinue_run(
    agent: Agent,
    session_id: str,
    run_context: RunContext,
    run_response: Optional[RunOutput] = None,
    updated_tools: Optional[List[ToolExecution]] = None,
    requirements: Optional[List[RunRequirement]] = None,
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
    from agno.agent._hooks import aexecute_post_hooks
    from agno.agent._init import disconnect_connectable_tools, disconnect_mcp_tools
    from agno.agent._messages import get_continue_run_messages
    from agno.agent._response import (
        agenerate_followups,
        agenerate_response_with_output_model,
        aparse_response_with_parser_model,
        convert_response_to_structured_format,
        update_run_response,
    )
    from agno.agent._storage import aread_or_create_session, load_session_state, update_metadata
    from agno.agent._telemetry import alog_agent_telemetry
    from agno.agent._tools import ahandle_tool_call_updates, determine_tools_for_model

    log_debug(f"Agent Run Continue: {run_response.run_id if run_response else run_id}", center=True)  # type: ignore
    agent_session: Optional[AgentSession] = None

    # Resolve retry parameters
    try:
        num_attempts = agent.retries + 1
        for attempt in range(num_attempts):
            try:
                # Bind run_messages early — cancellation can fire before run_messages
                # is built, and the cancellation handler reads it.
                run_messages: Optional[RunMessages] = None
                if attempt > 0:
                    log_debug(f"Retrying Agent acontinue_run {run_id}. Attempt {attempt + 1} of {num_attempts}...")

                # 1. Read existing session from db
                agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)

                # 2. Resolve dependencies
                if run_context.dependencies is not None:
                    await aresolve_run_dependencies(agent, run_context=run_context)

                # 3. Update metadata and session state
                update_metadata(agent, session=agent_session)

                # Initialize session state. Get it from DB if relevant.
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_context.run_id,
                )

                # 4. Prepare run response
                if run_response is not None:
                    if run_response.status == RunStatus.cancelled:
                        raise ValueError(f"Cannot continue run {run_response.run_id}: run is cancelled")
                    # The run is continued from a provided run_response. This contains the updated tools.
                    continue_index: Optional[int] = _resolve_continue_from(
                        run_response,
                        continue_from=continue_from,
                        regenerate=regenerate,
                    )
                    fork, continue_index, input = _normalize_regenerate_params(
                        run_response,
                        regenerate=regenerate,
                        replace_original=replace_original,
                        additional_instructions=additional_instructions,
                        fork=fork,
                        continue_index=continue_index,
                        input=input,
                    )
                    if not fork and run_response.status == RunStatus.completed:
                        fork = True
                    original_run_id_for_lineage = run_response.run_id if regenerate else None
                    run_response = _apply_continue_modifiers(run_response, fork, continue_index)
                    if regenerate and original_run_id_for_lineage:
                        run_response.regenerated_from = original_run_id_for_lineage
                        if replace_original is not False and run_response.forked_from_run_id:
                            for r in agent_session.runs or []:
                                if r.run_id == original_run_id_for_lineage:
                                    r.status = RunStatus.regenerated
                                    break
                    input_messages = run_response.messages or []
                elif run_id is not None:
                    # The run is continued from a run_id.
                    runs = agent_session.runs or []
                    run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
                    if run_response is None:
                        raise RuntimeError(f"No runs found for run ID {run_id}")
                    if run_response.status == RunStatus.cancelled:
                        raise ValueError(f"Cannot continue run {run_response.run_id}: run is cancelled")

                    continue_index = _resolve_continue_from(
                        run_response,
                        continue_from=continue_from,
                        regenerate=regenerate,
                    )
                    fork, continue_index, input = _normalize_regenerate_params(
                        run_response,
                        regenerate=regenerate,
                        replace_original=replace_original,
                        additional_instructions=additional_instructions,
                        fork=fork,
                        continue_index=continue_index,
                        input=input,
                    )
                    original_run_id_for_lineage = run_response.run_id if regenerate else None

                    # Auto-fork on COMPLETED — preserves the "1 run = 1 model loop"
                    # invariant. Continuing a run whose model loop already
                    # completed MUST produce a new run_id; otherwise the
                    # persisted row would mix two loops' metrics. The only
                    # in-place resumes are mid-flight ones (RUNNING / ERROR /
                    # PAUSED — the loop never actually finished).
                    if not fork and run_response.status == RunStatus.completed:
                        fork = True

                    # Apply fork/truncate before validation so the rest of the dispatch operates
                    # on the modified state. The local ``run_id`` continues to refer to the
                    # original run (used for HITL approval lookups); ``run_response.run_id``
                    # is the new UUID when fork=True.
                    run_response = _apply_continue_modifiers(run_response, fork, continue_index)
                    if regenerate and original_run_id_for_lineage:
                        run_response.regenerated_from = original_run_id_for_lineage
                        if replace_original is not False and run_response.forked_from_run_id:
                            for r in agent_session.runs or []:
                                if r.run_id == original_run_id_for_lineage:
                                    r.status = RunStatus.regenerated
                                    break

                    input_messages = run_response.messages or []

                    # If we have updated_tools, set them in the run_response
                    if updated_tools is not None:
                        run_response.tools = updated_tools
                        _sync_requirements_with_tools(run_response, updated_tools)

                    # If we have requirements, get the updated tools and set them in the run_response
                    elif requirements is not None:
                        run_response.requirements = requirements
                        updated_tools = [req.tool_execution for req in requirements if req.tool_execution is not None]
                        if updated_tools and run_response.tools:
                            updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
                            run_response.tools = [
                                updated_tools_map.get(tool.tool_call_id, tool) for tool in run_response.tools
                            ]
                        else:
                            run_response.tools = updated_tools

                    else:
                        # No tools / requirements in the body. Two cases:
                        # 1. The run has unresolved HITL requirements → try admin-approval
                        #    resolution; if none, the caller must provide tools/requirements.
                        # 2. The run has no unresolved requirements → just resume from current
                        #    state (mid-flight resume, ERROR retry, time-travel, etc.). This
                        #    is the unified /continue path (ADR-003, ADR-004).
                        has_unresolved_requirements = any(
                            not req.is_resolved() for req in (run_response.requirements or [])
                        )
                        if has_unresolved_requirements:
                            from agno.run.approval import acheck_and_apply_approval_resolution

                            try:
                                # This will apply resolution_data to tools if approval is resolved
                                await acheck_and_apply_approval_resolution(agent.db, run_id, run_response)
                            except RuntimeError:
                                # No resolved approval found — caller must provide requirements/tools
                                raise ValueError(
                                    "Run has unresolved HITL requirements. Provide the `requirements` "
                                    "parameter (or resolve an admin approval first)."
                                )
                        # else: nothing to resolve — fall through to resume from current state
                else:
                    raise ValueError("Either run_response or run_id must be provided.")

                # If the caller supplied a new user-message string (unified /continue
                # body field ``input``), append it to run_response.messages before
                # building run_messages.
                if input:
                    _maybe_append_input_message(run_response, input, agent)
                    input_messages = run_response.messages or []

                run_response = cast(RunOutput, run_response)

                # 5. Determine tools for model
                agent.model = cast(Model, agent.model)
                processed_tools = await agent.aget_tools(
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    user_id=user_id,
                )

                _tools = determine_tools_for_model(
                    agent,
                    model=agent.model,
                    processed_tools=processed_tools,
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    async_mode=True,
                )

                # 6. Prepare run messages
                run_messages = get_continue_run_messages(
                    agent,
                    input=input_messages,
                    session=agent_session,
                    add_history_to_context=agent.add_history_to_context,
                )

                # Reset the run state
                run_response.status = RunStatus.running

                # Register run for cancellation tracking
                await aregister_run(run_response.run_id)  # type: ignore

                # 7. Handle the updated tools
                await ahandle_tool_call_updates(
                    agent, run_response=run_response, run_messages=run_messages, tools=_tools
                )

                # 8. Get model response
                model_response: ModelResponse = await acall_model_with_fallback(
                    agent.model,
                    agent.fallback_config,
                    messages=run_messages.messages,
                    response_format=response_format,
                    tools=_tools,
                    tool_choice=agent.tool_choice,
                    tool_call_limit=agent.tool_call_limit,
                    run_response=run_response,
                    send_media_to_model=agent.send_media_to_model,
                    compression_manager=agent.compression_manager if agent.compress_tool_results else None,
                    after_tool_results=abuild_after_tool_results_callback(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_messages=run_messages,
                        run_context=run_context,
                    ),
                )
                # Check for cancellation after model call
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # If an output model is provided, generate output using the output model
                await agenerate_response_with_output_model(
                    agent, model_response=model_response, run_messages=run_messages, run_response=run_response
                )

                # If a parser model is provided, structure the response separately
                await aparse_response_with_parser_model(
                    agent,
                    model_response=model_response,
                    run_messages=run_messages,
                    run_context=run_context,
                    run_response=run_response,
                )

                # 9. Update the RunOutput with the model response
                update_run_response(
                    agent,
                    model_response=model_response,
                    run_response=run_response,
                    run_messages=run_messages,
                    run_context=run_context,
                )

                # Break out of the run function if a tool call is paused
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    return await ahandle_agent_run_paused(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # 10. Convert the response to the structured format if needed
                convert_response_to_structured_format(agent, run_response, run_context=run_context)

                # 10b. Generate follow-up suggestions if enabled
                await agenerate_followups(agent, run_response=run_response)

                # 11. Store media in run output for the caller
                store_media_util(run_response, model_response)

                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # 12. Execute post-hooks
                if agent.post_hooks is not None:
                    async for _ in aexecute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
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
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    agent_session.upsert_run(run=run_response)

                    try:
                        await agent.session_summary_manager.acreate_session_summary(
                            session=agent_session, run_metrics=run_response.metrics
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 14. Cleanup and store the run response and session
                await acleanup_and_store(
                    agent,
                    run_response=run_response,
                    session=agent_session,
                    run_context=run_context,
                    user_id=user_id,
                )

                # Log Agent Telemetry
                await alog_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                return run_response

            except RunCancelledException as e:
                if run_response is None:
                    run_response = RunOutput(run_id=run_id)
                run_response = _handle_run_cancellation(run_response, e, run_messages)
                try:
                    if agent_session is not None:
                        await acleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                return run_response
            except (InputCheckError, OutputCheckError) as e:
                run_response = cast(RunOutput, run_response)
                # Handle exceptions during streaming
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Validation failed: {str(e)} | Check trigger: {e.check_trigger}")

                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response
            except (KeyboardInterrupt, asyncio.CancelledError) as cancel_exc:
                if run_response is None:
                    run_response = RunOutput(run_id=run_id)
                run_response = _handle_run_cancellation(run_response, KeyboardInterrupt(), run_messages)
                if agent_session is not None:
                    if isinstance(cancel_exc, asyncio.CancelledError):
                        # Client disconnect: persist on a detached task so the cancel scope can't abort the write
                        _persist_cancelled_run_in_background(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                    else:
                        # Ctrl-C under asyncio.run: persist inline; a detached task would not run before the loop exits
                        await acleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                # Re-raise on disconnect to propagate it; return the partial on Ctrl-C
                if isinstance(cancel_exc, asyncio.CancelledError):
                    raise
                return run_response
            except ValueError:
                # Validation errors (e.g. cancelled run, missing args) propagate to the caller
                raise
            except Exception as e:
                run_response = cast(RunOutput, run_response)
                # Check if this is the last attempt
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    await asyncio.sleep(delay)
                    continue

                if not run_response:
                    run_response = RunOutput(run_id=run_id)

                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
                # Add error event to list of events
                run_error = create_run_error_event(run_response, error=str(e))  # type: ignore
                run_response.events = add_error_event(error=run_error, events=run_response.events)  # type: ignore

                # If the content is None, set it to the error message
                if run_response.content is None:  # type: ignore
                    run_response.content = str(e)  # type: ignore

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,  # type: ignore
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                return run_response  # type: ignore

    finally:
        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always disconnect MCP tools
        await disconnect_mcp_tools(agent)

        # Always clean up the run tracking
        await acleanup_run(run_response.run_id)  # type: ignore
    return run_response  # type: ignore


async def _acontinue_run_stream(
    agent: Agent,
    session_id: str,
    run_context: RunContext,
    run_response: Optional[RunOutput] = None,
    updated_tools: Optional[List[ToolExecution]] = None,
    requirements: Optional[List[RunRequirement]] = None,
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
    from agno.agent._hooks import aexecute_post_hooks
    from agno.agent._init import disconnect_connectable_tools, disconnect_mcp_tools
    from agno.agent._messages import get_continue_run_messages
    from agno.agent._response import (
        agenerate_followups_stream,
        agenerate_response_with_output_model_stream,
        ahandle_model_response_stream,
        aparse_response_with_parser_model_stream,
    )
    from agno.agent._storage import aread_or_create_session, load_session_state, update_metadata
    from agno.agent._telemetry import alog_agent_telemetry
    from agno.agent._tools import ahandle_tool_call_updates_stream, determine_tools_for_model

    log_debug(f"Agent Run Continue: {run_response.run_id if run_response else run_id}", center=True)  # type: ignore

    agent_session: Optional[AgentSession] = None

    # Resolve retry parameters
    try:
        num_attempts = agent.retries + 1
        for attempt in range(num_attempts):
            try:
                # Bind run_messages early — cancellation can fire before run_messages
                # is built, and the cancellation handler reads it.
                run_messages: Optional[RunMessages] = None
                # 1. Read existing session from db
                agent_session = await aread_or_create_session(agent, session_id=session_id, user_id=user_id)

                # 2. Update session state and metadata
                update_metadata(agent, session=agent_session)

                # Initialize session state. Get it from DB if relevant.
                run_context.session_state = load_session_state(
                    agent,
                    session=agent_session,
                    session_state=run_context.session_state if run_context.session_state is not None else {},
                )
                _initialize_session_state(
                    run_context.session_state,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_context.run_id,
                )

                # 3. Resolve dependencies
                if run_context.dependencies is not None:
                    await aresolve_run_dependencies(agent, run_context=run_context)

                # 4. Prepare run response
                if run_response is not None:
                    if run_response.status == RunStatus.cancelled:
                        raise ValueError(f"Cannot continue run {run_response.run_id}: run is cancelled")
                    # The run is continued from a provided run_response. This contains the updated tools.
                    continue_index: Optional[int] = _resolve_continue_from(
                        run_response,
                        continue_from=continue_from,
                        regenerate=regenerate,
                    )
                    fork, continue_index, input = _normalize_regenerate_params(
                        run_response,
                        regenerate=regenerate,
                        replace_original=replace_original,
                        additional_instructions=additional_instructions,
                        fork=fork,
                        continue_index=continue_index,
                        input=input,
                    )
                    if not fork and run_response.status == RunStatus.completed:
                        fork = True
                    original_run_id_for_lineage = run_response.run_id if regenerate else None
                    run_response = _apply_continue_modifiers(run_response, fork, continue_index)
                    if regenerate and original_run_id_for_lineage:
                        run_response.regenerated_from = original_run_id_for_lineage
                        if replace_original is not False and run_response.forked_from_run_id:
                            for r in agent_session.runs or []:
                                if r.run_id == original_run_id_for_lineage:
                                    r.status = RunStatus.regenerated
                                    break
                    input_messages = run_response.messages or []

                elif run_id is not None:
                    # The run is continued from a run_id.
                    runs = agent_session.runs or []
                    run_response = next((r for r in runs if r.run_id == run_id), None)  # type: ignore
                    if run_response is None:
                        raise RuntimeError(f"No runs found for run ID {run_id}")
                    if run_response.status == RunStatus.cancelled:
                        raise ValueError(f"Cannot continue run {run_response.run_id}: run is cancelled")

                    continue_index = _resolve_continue_from(
                        run_response,
                        continue_from=continue_from,
                        regenerate=regenerate,
                    )
                    fork, continue_index, input = _normalize_regenerate_params(
                        run_response,
                        regenerate=regenerate,
                        replace_original=replace_original,
                        additional_instructions=additional_instructions,
                        fork=fork,
                        continue_index=continue_index,
                        input=input,
                    )
                    original_run_id_for_lineage = run_response.run_id if regenerate else None

                    # Auto-fork on COMPLETED — preserves the "1 run = 1 model loop"
                    # invariant. Continuing a run whose model loop already
                    # completed MUST produce a new run_id; otherwise the
                    # persisted row would mix two loops' metrics. The only
                    # in-place resumes are mid-flight ones (RUNNING / ERROR /
                    # PAUSED — the loop never actually finished).
                    if not fork and run_response.status == RunStatus.completed:
                        fork = True

                    # Apply fork/truncate before validation so the rest of the dispatch operates
                    # on the modified state. The local ``run_id`` continues to refer to the
                    # original run (used for HITL approval lookups); ``run_response.run_id``
                    # is the new UUID when fork=True.
                    run_response = _apply_continue_modifiers(run_response, fork, continue_index)
                    if regenerate and original_run_id_for_lineage:
                        run_response.regenerated_from = original_run_id_for_lineage
                        if replace_original is not False and run_response.forked_from_run_id:
                            for r in agent_session.runs or []:
                                if r.run_id == original_run_id_for_lineage:
                                    r.status = RunStatus.regenerated
                                    break

                    input_messages = run_response.messages or []

                    # If we have updated_tools, set them in the run_response
                    if updated_tools is not None:
                        run_response.tools = updated_tools
                        _sync_requirements_with_tools(run_response, updated_tools)

                    # If we have requirements, get the updated tools and set them in the run_response
                    elif requirements is not None:
                        run_response.requirements = requirements
                        updated_tools = [req.tool_execution for req in requirements if req.tool_execution is not None]
                        if updated_tools and run_response.tools:
                            updated_tools_map = {tool.tool_call_id: tool for tool in updated_tools}
                            run_response.tools = [
                                updated_tools_map.get(tool.tool_call_id, tool) for tool in run_response.tools
                            ]
                        else:
                            run_response.tools = updated_tools

                    else:
                        # No tools / requirements in the body. Two cases:
                        # 1. The run has unresolved HITL requirements → try admin-approval
                        #    resolution; if none, the caller must provide tools/requirements.
                        # 2. The run has no unresolved requirements → just resume from current
                        #    state (ERROR retry, time-travel, etc.). This is the unified
                        #    /continue path (ADR-003, ADR-004).
                        has_unresolved_requirements = any(
                            not req.is_resolved() for req in (run_response.requirements or [])
                        )
                        if has_unresolved_requirements:
                            from agno.run.approval import acheck_and_apply_approval_resolution

                            try:
                                # This will apply resolution_data to tools if approval is resolved
                                await acheck_and_apply_approval_resolution(agent.db, run_id, run_response)
                            except RuntimeError:
                                # No resolved approval found — caller must provide requirements/tools
                                raise ValueError(
                                    "Run has unresolved HITL requirements. Provide the `requirements` "
                                    "parameter (or resolve an admin approval first)."
                                )
                        # else: nothing to resolve — fall through to resume from current state
                else:
                    raise ValueError("Either run_response or run_id must be provided.")

                # If the caller supplied a new user-message string (unified /continue
                # body field ``input``), append it to run_response.messages before
                # building run_messages.
                if input:
                    _maybe_append_input_message(run_response, input, agent)
                    input_messages = run_response.messages or []

                run_response = cast(RunOutput, run_response)

                # 5. Determine tools for model
                agent.model = cast(Model, agent.model)
                processed_tools = await agent.aget_tools(
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    user_id=user_id,
                )

                _tools = determine_tools_for_model(
                    agent,
                    model=agent.model,
                    processed_tools=processed_tools,
                    run_response=run_response,
                    run_context=run_context,
                    session=agent_session,
                    async_mode=True,
                )

                # 6. Prepare run messages
                run_messages = get_continue_run_messages(
                    agent,
                    input=input_messages,
                    session=agent_session,
                    add_history_to_context=agent.add_history_to_context,
                )

                # Reset the run state
                run_response.status = RunStatus.running

                # Register run for cancellation tracking
                await aregister_run(run_response.run_id)  # type: ignore

                # Start the Run by yielding a RunContinued event
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_continued_event(run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # 7. Handle the updated tools
                async for event in ahandle_tool_call_updates_stream(
                    agent,
                    run_response=run_response,
                    run_messages=run_messages,
                    tools=_tools,
                    stream_events=stream_events,
                ):
                    if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                    yield event

                # 8. Process model response
                if agent.output_model is None:
                    async for event in ahandle_model_response_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        run_context=run_context,
                    ):
                        if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event
                else:
                    from agno.run.agent import (
                        IntermediateRunContentEvent,
                        RunContentEvent,
                    )  # type: ignore

                    async for event in ahandle_model_response_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        tools=_tools,
                        response_format=response_format,
                        stream_events=stream_events,
                        run_context=run_context,
                    ):
                        if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
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
                    async for event in agenerate_response_with_output_model_stream(
                        agent,
                        session=agent_session,
                        run_response=run_response,
                        run_messages=run_messages,
                        stream_events=stream_events,
                    ):
                        if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                            await araise_if_cancelled(run_response.run_id)  # type: ignore
                        yield event

                # Check for cancellation after model processing
                await araise_if_cancelled(run_response.run_id)  # type: ignore

                # Parse response with parser model if provided
                async for event in aparse_response_with_parser_model_stream(
                    agent,
                    session=agent_session,
                    run_response=run_response,
                    stream_events=stream_events,
                    run_context=run_context,
                ):
                    if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                    yield event  # type: ignore

                # Generate follow-up suggestions if enabled
                async for event in agenerate_followups_stream(
                    agent,
                    run_response=run_response,
                    stream_events=stream_events,
                ):
                    if not isinstance(event, _CANCEL_BYPASS_EVENT_TYPES):
                        await araise_if_cancelled(run_response.run_id)  # type: ignore
                    yield event  # type: ignore

                # Yield RunContentCompletedEvent
                if stream_events:
                    yield handle_event(  # type: ignore
                        create_run_content_completed_event(from_run_response=run_response),
                        run_response,
                        events_to_skip=agent.events_to_skip,  # type: ignore
                        store_events=agent.store_events,
                    )

                # Break out of the run function if a tool call is paused
                if any(tool_call.is_paused for tool_call in run_response.tools or []):
                    async for item in ahandle_agent_run_paused_stream(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                        yield_run_output=yield_run_output or False,
                    ):
                        yield item
                    return

                # 8. Execute post-hooks
                if agent.post_hooks is not None:
                    async for event in aexecute_post_hooks(
                        agent,
                        hooks=agent.post_hooks,  # type: ignore
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
                if agent.session_summary_manager is not None and agent.enable_session_summaries:
                    # Upsert the RunOutput to Agent Session before creating the session summary
                    agent_session.upsert_run(run=run_response)

                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_started_event(from_run_response=run_response),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )
                    try:
                        await agent.session_summary_manager.acreate_session_summary(
                            session=agent_session, run_metrics=run_response.metrics
                        )
                    except Exception as e:
                        log_warning(f"Error in session summary creation: {str(e)}")
                    if stream_events:
                        yield handle_event(  # type: ignore
                            create_session_summary_completed_event(
                                from_run_response=run_response, session_summary=agent_session.summary
                            ),
                            run_response,
                            events_to_skip=agent.events_to_skip,  # type: ignore
                            store_events=agent.store_events,
                        )

                # Update run_response.session_state before creating RunCompletedEvent
                # This ensures the event has the final state after all tool modifications
                if agent_session.session_data is not None and "session_state" in agent_session.session_data:
                    run_response.session_state = agent_session.session_data["session_state"]

                # Create the run completed event
                completed_event = handle_event(
                    create_run_completed_event(run_response),
                    run_response,
                    events_to_skip=agent.events_to_skip,  # type: ignore
                    store_events=agent.store_events,
                )

                # Set the run status to completed
                run_response.status = RunStatus.completed

                # 10. Cleanup and store the run response and session
                await acleanup_and_store(
                    agent, run_response=run_response, session=agent_session, run_context=run_context, user_id=user_id
                )

                if stream_events:
                    yield completed_event  # type: ignore

                if yield_run_output:
                    yield run_response

                # Log Agent Telemetry
                await alog_agent_telemetry(agent, session_id=agent_session.session_id, run_id=run_response.run_id)

                log_debug(f"Agent Run End: {run_response.run_id}", center=True, symbol="*")

                break
            except RunCancelledException as e:
                if run_response is None:
                    run_response = RunOutput(run_id=run_id)
                run_response = _handle_run_cancellation(run_response, e, run_messages)
                cancelled_event, completed_event = _build_cancel_terminal_events(
                    agent,
                    run_response,
                    error=e,
                    run_context=run_context,
                )
                try:
                    if agent_session is not None:
                        await acleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                except Exception as store_err:
                    log_warning(f"Failed to persist cancelled run: {store_err}")
                yield cancelled_event  # type: ignore
                yield completed_event  # type: ignore
                if yield_run_output:
                    yield run_response
                break

            except (InputCheckError, OutputCheckError) as e:
                if run_response is None:
                    run_response = RunOutput(run_id=run_id)
                run_response = cast(RunOutput, run_response)
                # Handle exceptions during async streaming
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
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
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # Yield the error event
                yield run_error
                break
            except (KeyboardInterrupt, asyncio.CancelledError, GeneratorExit) as cancel_exc:
                if run_response is None:
                    run_response = RunOutput(run_id=run_id)
                run_response = _handle_run_cancellation(run_response, KeyboardInterrupt(), run_messages)
                # Build terminal events first so they are stored on the run
                cancelled_event, completed_event = _build_cancel_terminal_events(
                    agent,
                    run_response,
                    error=KeyboardInterrupt(),
                    run_context=run_context,
                )
                if agent_session is not None:
                    if isinstance(cancel_exc, (asyncio.CancelledError, GeneratorExit)):
                        # Client disconnect: persist on a detached task so the cancel scope can't abort the write.
                        # GeneratorExit is raised when the SSE StreamingResponse closes the generator on disconnect.
                        _persist_cancelled_run_in_background(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
                        )
                    else:
                        # Ctrl-C under asyncio.run: persist inline; a detached task would not run before the loop exits
                        await acleanup_and_store(
                            agent,
                            run_response=run_response,
                            session=agent_session,
                            run_context=run_context,
                            user_id=user_id,
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
                    run_response = RunOutput(run_id=run_id)
                run_response = cast(RunOutput, run_response)
                # Check if this is the last attempt
                if attempt < num_attempts - 1:
                    # Calculate delay with exponential backoff if enabled
                    if agent.exponential_backoff:
                        delay = agent.delay_between_retries * (2**attempt)
                    else:
                        delay = agent.delay_between_retries

                    log_warning(f"Attempt {attempt + 1}/{num_attempts} failed. Retrying in {delay}s...: {str(e)}")
                    await asyncio.sleep(delay)
                    continue

                # Handle exceptions during async streaming
                run_response.status = RunStatus.error
                flush_in_flight_messages_on_error(run_response, locals().get("run_messages"))
                # Add error event to list of events
                run_error = create_run_error_event(run_response, error=str(e))
                run_response.events = add_error_event(error=run_error, events=run_response.events)

                # If the content is None, set it to the error message
                if run_response.content is None:
                    run_response.content = str(e)

                log_error(f"Error in Agent run: {str(e)}")

                # Cleanup and store the run response and session
                if agent_session is not None:
                    await acleanup_and_store(
                        agent,
                        run_response=run_response,
                        session=agent_session,
                        run_context=run_context,
                        user_id=user_id,
                    )

                # Yield the error event
                yield run_error
    finally:
        # Always disconnect connectable tools
        disconnect_connectable_tools(agent)
        # Always disconnect MCP tools
        await disconnect_mcp_tools(agent)

        # Always clean up the run tracking
        cleanup_run_id = run_response.run_id if run_response and run_response.run_id is not None else run_id
        if cleanup_run_id is not None:
            await acleanup_run(cleanup_run_id)


# ---------------------------------------------------------------------------
# Post-run cleanup
# ---------------------------------------------------------------------------


def save_run_response_to_file(
    agent: Agent,
    run_response: RunOutput,
    input: Optional[Union[str, List, Dict, Message]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    if agent.save_response_to_file is not None and run_response is not None:
        message_str = None
        if input is not None:
            if isinstance(input, str):
                message_str = input
            else:
                log_warning("Did not use input in output file name: input is not a string")
        try:
            from pathlib import Path

            def _sanitize(value: Any) -> str:
                """Strip path-traversal characters from format values."""
                s = str(value) if value is not None else ""
                return s.replace("/", "_").replace("\\", "_").replace("..", "_")

            fn = agent.save_response_to_file.format(
                name=_sanitize(agent.name),
                session_id=_sanitize(session_id),
                user_id=_sanitize(user_id),
                message=_sanitize(message_str),
                run_id=_sanitize(run_response.run_id),
            )
            fn_path = Path(fn)
            if not fn_path.parent.exists():
                fn_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(run_response.content, str):
                fn_path.write_text(run_response.content)
            else:
                import json

                fn_path.write_text(json.dumps(run_response.content, indent=2))
        except Exception as e:
            log_warning(f"Failed to save output to file: {str(e)}")


def scrub_run_output_for_storage(agent: Agent, run_response: RunOutput) -> None:
    """Scrub run output based on storage flags before persisting to database."""
    if not agent.store_media:
        scrub_media_from_run_output(run_response)

    if not agent.store_tool_messages:
        scrub_tool_results_from_run_output(run_response)

    if not agent.store_history_messages:
        scrub_history_messages_from_run_output(run_response)


def _normalize_cancellation_reason(
    run_response: RunOutput,
    error: Union[RunCancelledException, KeyboardInterrupt],
) -> str:
    """Return a non-empty, human-readable reason for a cancellation."""
    if isinstance(error, RunCancelledException):
        return str(error) or f"Run {run_response.run_id} was cancelled"
    return "Operation cancelled by user"


def _handle_run_cancellation(
    run_response: RunOutput,
    error: Union[RunCancelledException, KeyboardInterrupt],
    run_messages: Optional["RunMessages"] = None,
) -> RunOutput:
    """Prepare a run response for cancellation: set status, preserve content and messages."""
    reason = _normalize_cancellation_reason(run_response, error)
    log_debug(f"Run {run_response.run_id} was cancelled")
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


def _build_cancel_terminal_events(
    agent: Agent,
    run_response: RunOutput,
    error: Union[RunCancelledException, KeyboardInterrupt],
    run_context: Optional[RunContext] = None,
) -> Tuple[RunCancelledEvent, RunCompletedEvent]:
    """Return the (cancelled, completed) terminal event pair for a cancelled run."""
    # Update run_response.session_state before creating the events
    if run_context is not None and run_context.session_state is not None:
        run_response.session_state = run_context.session_state
    cancelled_event = cast(
        RunCancelledEvent,
        handle_event(
            create_run_cancelled_event(
                from_run_response=run_response,
                reason=_normalize_cancellation_reason(run_response, error),
            ),
            run_response,
            events_to_skip=agent.events_to_skip,  # type: ignore
            store_events=agent.store_events,
        ),
    )
    completed_event = cast(
        RunCompletedEvent,
        handle_event(
            create_run_completed_event(from_run_response=run_response),
            run_response,
            events_to_skip=agent.events_to_skip,  # type: ignore
            store_events=agent.store_events,
        ),
    )
    return cancelled_event, completed_event


def _scrub_and_propagate_session_state(
    agent: Agent,
    run_response: RunOutput,
    run_context: Optional[RunContext],
    isolate_inflight: bool = False,
) -> RunOutput:
    """Build a scrubbed shallow copy of ``run_response`` and propagate session_state.

    Helper shared by cleanup_and_store (terminal) and persist_run_in_session
    (checkpoint). Scrubbing is in-place on the shallow copy; the original
    ``run_response`` is not mutated except for its session_state (mirrored from
    run_context so the caller sees the latest state).

    ``isolate_inflight`` is set on the mid-run checkpoint path: media scrubbing
    mutates Message/RunInput objects in place, and the shallow copy shares them
    with the still-running run, so without isolation a checkpoint would strip
    media off the live run before its next model turn. Off (terminal) the run is
    finished, so the shared-object scrub is harmless and we avoid the copy.
    """
    import copy

    storage_copy = copy.copy(run_response)
    if isolate_inflight and not agent.store_media:
        isolate_media_scrub_targets(storage_copy)
    scrub_run_output_for_storage(agent, storage_copy)

    if run_context is not None and run_context.session_state is not None:
        run_response.session_state = run_context.session_state
        storage_copy.session_state = run_context.session_state

    return storage_copy


def persist_run_in_session(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
    storage_copy: Optional[RunOutput] = None,
) -> None:
    """Persist the current run state into the session and save the session.

    Shared by terminal cleanup (cleanup_and_store) and mid-run checkpointing
    (checkpoint_run). Performs: scrub a shallow copy (unless one is supplied),
    upsert it into the session's runs list, refresh session metrics, sync
    session_state into session_data, and call save_session.

    Does NOT stop the run timer, write to file, or update approval status —
    those are terminal-only and live in cleanup_and_store.
    """
    from agno.agent import _session

    if storage_copy is None:
        storage_copy = _scrub_and_propagate_session_state(agent, run_response, run_context, isolate_inflight=True)

    # Add scrubbed RunOutput to Agent Session
    session.upsert_run(run=storage_copy)

    # Calculate session metrics
    update_session_metrics(agent, session=session, run_response=run_response)

    # Update session state before saving the session
    if run_context is not None and run_context.session_state is not None:
        if session.session_data is not None:
            session.session_data["session_state"] = run_context.session_state
        else:
            session.session_data = {"session_state": run_context.session_state}

    # Save session to memory
    _session.save_session(agent, session=session)


async def apersist_run_in_session(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
    storage_copy: Optional[RunOutput] = None,
) -> None:
    """Async variant of :func:`persist_run_in_session`."""
    from agno.agent import _session

    if storage_copy is None:
        storage_copy = _scrub_and_propagate_session_state(agent, run_response, run_context, isolate_inflight=True)

    session.upsert_run(run=storage_copy)
    update_session_metrics(agent, session=session, run_response=run_response)

    if run_context is not None and run_context.session_state is not None:
        if session.session_data is not None:
            session.session_data["session_state"] = run_context.session_state
        else:
            session.session_data = {"session_state": run_context.session_state}

    await _session.asave_session(agent, session=session)


def flush_in_flight_messages_on_error(
    run_response: RunOutput,
    run_messages: Optional["RunMessages"],
) -> None:
    """Copy in-flight conversation into ``run_response.messages`` for the
    terminal ERROR write.

    During a normal run, ``run_response.messages`` is populated by
    ``update_run_response`` only **after** the model loop returns
    successfully. If the model loop raises (e.g. provider API failure,
    malformed response, exception in a pre-hook) before any tool batch
    boundary fires, neither ``update_run_response`` nor the mid-run
    checkpoint hook has a chance to flush ``run_messages.messages`` into
    ``run_response.messages``. The terminal ERROR write would then persist
    an empty-message row, losing the conversation that led to the failure
    and making post-mortem debugging impossible.

    Call this from every ``except Exception`` block right before
    ``cleanup_and_store``. It only sets ``run_response.messages`` if it's
    still empty — preserves a partial state that the mid-run hook already
    captured.

    The filter ``m.add_to_agent_memory`` mirrors what the checkpoint hook
    does, so the persisted shape is consistent regardless of which path
    captured it.
    """
    if run_messages is None:
        return
    if run_response.messages:
        # Already populated (e.g. by a mid-run checkpoint hook). Don't
        # overwrite — it may be more complete than run_messages.messages
        # if intervening processing happened.
        return
    if not run_messages.messages:
        return
    run_response.messages = [m for m in run_messages.messages if m.add_to_agent_memory]


def cleanup_and_store(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
    user_id: Optional[str] = None,
) -> None:
    from agno.run.approval import update_approval_run_status

    # Scrub a shallow copy for storage — the original run_response is never
    # mutated so the caller always sees generated media regardless of store_media.
    storage_copy = _scrub_and_propagate_session_state(agent, run_response, run_context)

    # Stop the timer for the Run duration (terminal only)
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Optional: Save output to file if save_response_to_file is set (terminal only)
    save_run_response_to_file(
        agent,
        run_response=storage_copy,
        input=run_response.input.input_content_string() if run_response.input else "",
        session_id=session.session_id,
        user_id=user_id,
    )

    # Persist run into session and save session
    persist_run_in_session(agent, run_response, session, run_context, storage_copy=storage_copy)

    # Update approval run_status if this run has an associated approval.
    # This is a no-op if no approval exists for this run_id. (Terminal only.)
    if run_response.status is not None and run_response.run_id is not None:
        update_approval_run_status(agent.db, run_response.run_id, run_response.status)


async def acleanup_and_store(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
    user_id: Optional[str] = None,
) -> None:
    from agno.run.approval import aupdate_approval_run_status

    storage_copy = _scrub_and_propagate_session_state(agent, run_response, run_context)

    if run_response.metrics:
        run_response.metrics.stop_timer()

    save_run_response_to_file(
        agent,
        run_response=storage_copy,
        input=run_response.input.input_content_string() if run_response.input else "",
        session_id=session.session_id,
        user_id=user_id,
    )

    await apersist_run_in_session(agent, run_response, session, run_context, storage_copy=storage_copy)

    if run_response.status is not None and run_response.run_id is not None:
        await aupdate_approval_run_status(agent.db, run_response.run_id, run_response.status)


def _persist_cancelled_run_in_background(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
    user_id: Optional[str] = None,
) -> None:
    """Persist a cancelled run on a detached background task.

    On a client disconnect the request runs inside an anyio cancel scope; awaiting
    acleanup_and_store inline lets its DB write be re-cancelled mid-flight, losing the
    run. Scheduling it on _background_tasks runs the write to completion outside that
    scope.
    """

    async def _persist() -> None:
        try:
            await acleanup_and_store(
                agent,
                run_response=run_response,
                session=session,
                run_context=run_context,
                user_id=user_id,
            )
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
# Mid-run checkpointing (checkpoint="tool-batch")
# ---------------------------------------------------------------------------


def _sync_run_response_with_model_response(
    run_response: RunOutput,
    run_messages: RunMessages,
    model_response: ModelResponse,
) -> None:
    """Mirror the in-flight model_response/run_messages state onto run_response.

    Called by the checkpoint callback so the persisted snapshot reflects the
    state through the most recent tool batch. The end-of-run ``update_run_response``
    will redo this work; the duplication is intentional — we need an accurate
    intermediate snapshot.
    """
    if model_response.tool_executions is not None:
        run_response.tools = list(model_response.tool_executions)
    run_response.messages = [m for m in run_messages.messages if m.add_to_agent_memory]


def _mark_checkpoint_message(run_response: RunOutput) -> None:
    """Mark the current message boundary as checkpointed for client timelines."""
    if not run_response.messages:
        return
    message = run_response.messages[-1]
    message.checkpoint_status = run_response.status.value if run_response.status else None
    message.checkpoint_created_at = int(unix_time())


def checkpoint_run(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
) -> None:
    """Persist a mid-run checkpoint when ``agent.checkpoint == "tool-batch"``.

    Sets ``RunStatus.running`` and ``last_checkpoint_at_message_index``, then
    persists the run into the session. No-op when checkpointing is not "tool-batch".
    Idempotent — calling twice in a row writes the same state twice.

    Callers are responsible for ensuring ``run_response.messages`` and
    ``run_response.tools`` reflect the state to persist (see
    :func:`_sync_run_response_with_model_response`).
    """
    if agent.checkpoint != "tool-batch":
        return
    run_response.status = RunStatus.running
    run_response.last_checkpoint_at_message_index = len(run_response.messages or [])
    _mark_checkpoint_message(run_response)
    persist_run_in_session(agent, run_response, session, run_context)


async def acheckpoint_run(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_context: Optional[RunContext] = None,
) -> None:
    """Async variant of :func:`checkpoint_run`."""
    if agent.checkpoint != "tool-batch":
        return
    run_response.status = RunStatus.running
    run_response.last_checkpoint_at_message_index = len(run_response.messages or [])
    _mark_checkpoint_message(run_response)
    await apersist_run_in_session(agent, run_response, session, run_context)


def build_after_tool_results_callback(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
) -> Optional[Any]:
    """Build the sync ``after_tool_results`` callback for ``checkpoint="tool-batch"``.

    Returns ``None`` when checkpointing is not enabled — the caller passes the
    result directly to the model's ``after_tool_results=`` kwarg, and the
    zero-cost path is taken when the callback is None.

    The returned callback receives the current ``ModelResponse``, syncs
    ``run_response`` with the in-flight messages/tools, and writes a checkpoint.
    """
    if agent.checkpoint != "tool-batch":
        return None

    def _callback(model_response: ModelResponse) -> None:
        _sync_run_response_with_model_response(run_response, run_messages, model_response)
        checkpoint_run(agent, run_response, session, run_context)

    return _callback


def abuild_after_tool_results_callback(
    agent: Agent,
    run_response: RunOutput,
    session: AgentSession,
    run_messages: RunMessages,
    run_context: Optional[RunContext] = None,
) -> Optional[Any]:
    """Async variant of :func:`build_after_tool_results_callback`."""
    if agent.checkpoint != "tool-batch":
        return None

    async def _callback(model_response: ModelResponse) -> None:
        _sync_run_response_with_model_response(run_response, run_messages, model_response)
        await acheckpoint_run(agent, run_response, session, run_context)

    return _callback


# ---------------------------------------------------------------------------
# Session forking
# ---------------------------------------------------------------------------


def _build_forked_session(source_session: AgentSession, new_user_id: Optional[str]) -> AgentSession:
    """Deep-copy ``source_session`` into a brand-new ``AgentSession`` with fresh
    ``session_id`` and ``run_id``s, recording lineage on both the session and
    each copied run.

    Lineage shape:
    - ``session.session_data["forked_from_session_id"]`` is the **immediate** parent
      session_id, overwritten on each re-fork.
    - ``run.forked_from_session_id`` records each run's **original** session_id, set
      only-if-empty so nested forks keep pointing at the root.

    For root → mid → leaf: ``leaf.session.forked_from_session_id == mid``,
    ``leaf.runs[*].forked_from_session_id == root``.
    """
    import copy
    import time as _time

    now = int(_time.time())
    new_session_id = str(uuid4())
    forked_runs = copy.deepcopy(source_session.runs or [])

    for run in forked_runs:
        run.run_id = str(uuid4())
        run.session_id = new_session_id
        if not run.forked_from_session_id:
            run.forked_from_session_id = source_session.session_id

    new_session_data = copy.deepcopy(source_session.session_data) or {}
    new_session_data["forked_from_session_id"] = source_session.session_id

    return AgentSession(
        session_id=new_session_id,
        agent_id=source_session.agent_id,
        user_id=new_user_id or source_session.user_id,
        team_id=source_session.team_id,
        workflow_id=source_session.workflow_id,
        session_data=new_session_data,
        metadata=copy.deepcopy(source_session.metadata),
        agent_data=copy.deepcopy(source_session.agent_data),
        runs=forked_runs,
        summary=copy.deepcopy(source_session.summary),
        created_at=now,
        updated_at=now,
    )


def fork_session_dispatch(
    agent: Agent,
    *,
    source_session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    """Branch a session into a new independent session.

    Deep-copies every run from the source session into a new session with a
    fresh ``session_id`` and fresh ``run_id``s, so the new session can diverge
    without affecting the original. The source is read scoped to the caller's
    ``user_id`` to prevent cross-user access.

    Args:
        source_session_id: The session to fork. Defaults to ``agent.session_id``.
        user_id: Caller user_id. Must own the source session. The new session
            inherits this user_id.

    Returns:
        The new ``session_id``.
    """
    from agno.agent._init import has_async_db
    from agno.agent._session import save_session
    from agno.agent._storage import read_or_create_session

    if has_async_db(agent):
        raise RuntimeError(
            "`fork_session` is not supported with an async database. Please use `afork_session` instead."
        )

    source_session_id = source_session_id or agent.session_id
    if source_session_id is None:
        raise ValueError("source_session_id is required to fork a session.")

    agent.initialize_agent()
    source_session = read_or_create_session(agent, session_id=source_session_id, user_id=user_id)
    if not source_session.runs:
        raise ValueError("Source session has no runs to fork.")

    new_session = _build_forked_session(source_session, new_user_id=user_id)
    save_session(agent, session=new_session)
    return new_session.session_id


async def afork_session_dispatch(
    agent: Agent,
    *,
    source_session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    """Async variant of :func:`fork_session_dispatch`."""
    from agno.agent._init import has_async_db
    from agno.agent._session import asave_session, save_session
    from agno.agent._storage import aread_or_create_session, read_or_create_session

    source_session_id = source_session_id or agent.session_id
    if source_session_id is None:
        raise ValueError("source_session_id is required to fork a session.")

    agent.initialize_agent()

    if has_async_db(agent):
        source_session = await aread_or_create_session(agent, session_id=source_session_id, user_id=user_id)
    else:
        source_session = read_or_create_session(agent, session_id=source_session_id, user_id=user_id)

    if not source_session.runs:
        raise ValueError("Source session has no runs to fork.")

    new_session = _build_forked_session(source_session, new_user_id=user_id)

    if has_async_db(agent):
        await asave_session(agent, session=new_session)
    else:
        save_session(agent, session=new_session)

    return new_session.session_id


# ---------------------------------------------------------------------------
# Run cancellation — re-export from agno.run.cancel
# ---------------------------------------------------------------------------

cancel_run = cancel_run_global
acancel_run = acancel_run_global
